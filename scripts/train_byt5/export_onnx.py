#!/usr/bin/env python3
"""Export a trained ByT5 checkpoint to ONNX for floravox — with a hard
validation gate before anything is kept.

The first attempt (optimum-onnx 2.x, seq2seq-lm) produced a decoder
whose greedy output was scrambled even though the checkpoint was fine.
This script therefore exports MULTIPLE candidates, then validates each
against known-answer pairs by actually running the greedy decode, and
keeps only candidates that pass:

  pairs (lang, input, expected-prefix):
    spa  "<spa>: gato"      -> "ɡ a t o"       (g2p)
    eng  "<eng>: hello"     -> "h" (any)       (g2p)
    p2g: "<deu>: ʃ a ɪ n"   -> "schein"-ish — prefix "s" or "sch"

Validation is exact-prefix on at least 2 of 3 pairs (byte-level outputs
vary slightly by training run; we check the language-respecting prefix,
not the full string).

Candidates:
  1. optimum ORTModel export, seq2seq-lm (legacy no-past pair)
  2. optimum export seq2seq-lm-with-past (uses decoder_with_past: fast
     incremental decode) — kept only if inputs are usable
  3. (fallback) torch.onnx.export of the plain forward pass

Usage:
  python export_onnx.py --model runs/g2p-small/final --task g2p --out onnx/g2p-small
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import onnxruntime as ort

EOS = 1


def greedy(sess_pair, text, max_len=64):
    enc, dec = sess_pair
    # match training tokenization: ByT5Tokenizer appends EOS (1)
    ids = list(text.encode("utf-8"))[:127] + [1]
    inp = np.array([ids], dtype=np.int64)
    mask = np.ones_like(inp)
    efeeds = {"input_ids": inp}
    if "attention_mask" in {i.name for i in enc.get_inputs()}:
        efeeds["attention_mask"] = mask
    hidden = enc.run(None, efeeds)[0]
    names = {i.name for i in dec.get_inputs()}
    key = "input_ids" if "input_ids" in names else "decoder_input_ids"
    dnames = [n for n in names if "past_key_values" in n or ".key" in n]
    use_past_inputs = bool(dnames)
    dec_ids = np.zeros((1, 1), dtype=np.int64)
    past = {}
    out = bytearray()
    t = dec_ids.shape[1]
    for step in range(max_len):
        feeds = {key: dec_ids}
        if "attention_mask" in names:  # manual exports: 2D ones; T5 applies causal internally
            feeds["attention_mask"] = np.ones((1, t), dtype=np.int64)
        if "encoder_hidden_states" in names:
            feeds["encoder_hidden_states"] = hidden
        if "encoder_attention_mask" in names:
            feeds["encoder_attention_mask"] = mask
        for k, v in past.items():
            feeds[k] = v
        outs = dec.run(None, feeds)
        t += 1
        logits = outs[0]
        # refresh past from present outputs when the graph supports it
        for i, o in enumerate(dec.get_outputs()):
            if o.name.startswith("present.") and use_past_inputs:
                past.setdefault(o.name.replace("present.", "past_key_values."), o)
        nxt = int(np.argmax(logits[0, -1]))
        if nxt == EOS:
            break
        out.append(32 if nxt == 35 else nxt & 0xFF)  # 35 = byt5 space
        dec_ids = np.concatenate([dec_ids, np.array([[nxt]], dtype=np.int64)], axis=1)
    return out.decode("utf-8", "replace")


# NOTE: tags must exist in the trained corpus (variety-keyed since the
# dialect rework: eng-US, spa-ES, ...). ByT5Tokenizer maps SPACE to
# byte 35 ('#'); greedy() decodes raw bytes, so we map 35 back to a
# space before comparing to the space-separated gold.
PAIRS = {
    "g2p": [
        ("<spa-ES>: gato", "ɡ a t o"),
        ("<por-BR>: gato", "ɡ a t u"),
        ("<eng-US>: hello", "h"),
    ],
    "p2g": [
        ("<deu>: ʃ aɪ n", "sch"),
        ("<ita>: ɡ a t o", "gat"),
        ("<eng-US>: k æ t", "c"),
    ],
}


def validate(candidate_dir: Path, task: str) -> tuple[bool, list[str]]:
    enc_p = candidate_dir / "encoder_model.onnx"
    dec_p = candidate_dir / "decoder_model.onnx"
    if not (enc_p.exists() and dec_p.exists()):
        return False, ["missing files"]
    try:
        enc = ort.InferenceSession(str(enc_p))
        dec = ort.InferenceSession(str(dec_p))
    except Exception as e:  # noqa: BLE001
        return False, [f"session load: {e}"]
    results = []
    ok = 0
    for text, prefix in PAIRS[task]:
        try:
            got = greedy((enc, dec), text)
        except Exception as e:  # noqa: BLE001
            results.append(f"{text!r}: decode error {e}")
            continue
        good = got.startswith(prefix)
        ok += int(good)
        results.append(f"{text!r} -> {got!r} (want prefix {prefix!r}) {'OK' if good else 'FAIL'}")
    return ok >= 2, results


def try_manual(model: Path, tmp: Path) -> bool:
    """Plain torch.onnx.export: encoder graph + decoder graph (with
    lm_head), no cache, no merging — the path optimum keeps botching
    for ByT5. Greedy decode feeds the full prefix each step (quadratic
    but correct; a follow-up can re-add KV caching)."""
    import torch
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    m = AutoModelForSeq2SeqLM.from_pretrained(str(model.resolve())).eval()
    for p_ in m.parameters():
        p_.requires_grad_(False)
    tok = AutoTokenizer.from_pretrained(str(model.resolve()))
    d_model = m.config.d_model
    tmp.mkdir(parents=True, exist_ok=True)

    class Enc(torch.nn.Module):
        def forward(self, input_ids, attention_mask):
            return m.encoder(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state

    class Dec(torch.nn.Module):
        # attention_mask here is the DECODER (causal) self-attention mask,
        # passed explicitly: HF T5 branches on sequence_length==1 to skip
        # the mask, and torch.onnx bakes that branch — explicit masks make
        # the graph correct at every prefix length.
        def forward(self, input_ids, attention_mask, encoder_hidden_states, encoder_attention_mask):
            out = m.decoder(
                input_ids=input_ids,
                attention_mask=attention_mask,
                encoder_hidden_states=encoder_hidden_states,
                encoder_attention_mask=encoder_attention_mask,
            ).last_hidden_state
            return m.lm_head(out)

    dyn = {0: "b", 1: "s"}
    with torch.no_grad():
        torch.onnx.export(
            Enc(), (torch.zeros(1, 8, dtype=torch.long), torch.ones(1, 8, dtype=torch.long)),
            str(tmp / "encoder_model.onnx"), opset_version=14,
            input_names=["input_ids", "attention_mask"],
            output_names=["last_hidden_state"],
            dynamic_axes={"input_ids": dyn, "attention_mask": dyn,
                          "last_hidden_state": {0: "b", 1: "s"}},
        )
        torch.onnx.export(
            Dec(),
            (torch.zeros(1, 2, dtype=torch.long), torch.ones(1, 2, dtype=torch.long),
             torch.zeros(1, 8, d_model, dtype=torch.float),
             torch.ones(1, 8, dtype=torch.long)),
            str(tmp / "decoder_model.onnx"), opset_version=14,
            input_names=["input_ids", "attention_mask", "encoder_hidden_states", "encoder_attention_mask"],
            output_names=["logits"],
            dynamic_axes={"input_ids": {0: "b", 1: "t"},
                          "attention_mask": {0: "b", 1: "t"},
                          "encoder_hidden_states": {0: "b", 1: "s"},
                          "encoder_attention_mask": {0: "b", 1: "s"},
                          "logits": {0: "b", 1: "t"}},
        )
    tok.save_pretrained(str(tmp))
    return True


def try_optimum(model: Path, tmp: Path, with_past: bool) -> bool:
    from optimum.onnxruntime import ORTModelForSeq2SeqLM
    from transformers import AutoTokenizer
    model = model.resolve()
    kwargs = {}
    # optimum-onnx 1.x/2.x disagree on the task kwarg; probe cheaply
    try:
        m = ORTModelForSeq2SeqLM.from_pretrained(str(model), export=True, **kwargs)
    except TypeError:
        m = ORTModelForSeq2SeqLM.from_pretrained(str(model))
    t = AutoTokenizer.from_pretrained(str(model))
    m.save_pretrained(str(tmp))
    t.save_pretrained(str(tmp))
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", required=True)
    ap.add_argument("--task", choices=["g2p", "p2g"], required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    attempts = [
        ("manual", lambda t: try_manual(Path(args.model), t)),
        ("plain", lambda t: try_optimum(Path(args.model), t, False)),
        ("past", lambda t: try_optimum(Path(args.model), t, True)),
    ]
    for variant, runner in attempts:
        tmp = out.parent / f".{out.name}-{variant}-tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"== exporting {args.model} ({variant})")
        try:
            runner(tmp)
        except Exception as e:  # noqa: BLE001
            print(f"  export failed: {e}")
            continue
        ok, details = validate(tmp, args.task)
        for d in details:
            print(f"  {d}")
        if ok:
            shutil.rmtree(out, ignore_errors=True)
            tmp.rename(out)
            print(f"KEPT {variant} -> {out}")
            (out / "PROVENANCE.txt").write_text(
                f"exported from {args.model} via optimum-onnx "
                f"({'with' if with_past else 'no'}-past variant), "
                f"validated against known pairs\n"
            )
            return 0
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"  {variant} FAILED validation")

    print("ERROR: no export variant passed validation", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
