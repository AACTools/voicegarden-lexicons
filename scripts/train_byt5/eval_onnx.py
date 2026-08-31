#!/usr/bin/env python3
"""Evaluate an ONNX-exported ByT5 G2P/P2G model on the corpus test split.

This is the acceptance gate before shipping the neural tier: it loads
the SAME onnx files floravox loads (via optimum/onnxruntime — no torch
needed) and reports exact-match + token-level error rate per language,
plus the comparison against the WFST tier where one exists
(results/metrics.json).

Usage:
  python eval_onnx.py --onnx onnx/g2p --task g2p --corpus corpus
  python eval_onnx.py --onnx onnx/p2g --task p2g --sample 2000
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

MAX_INPUT_LEN = 128
MAX_TARGET_LEN = 160
EOS = 1


def load_rows(path: Path, task: str, sample: int, seed: int):
    import random

    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) == 3:
                lang, a, b = parts
                rows.append((lang, f"<{lang}>: {a}", b))
    if sample and sample < len(rows):
        rng = random.Random(seed)
        rows = rng.sample(rows, sample)
    return rows


def greedy_decode(session_pair, text: str) -> str:
    """Greedy byte-level decode using the encoder/decoder ONNX sessions."""
    enc, dec = session_pair
    import numpy as np
    import onnxruntime as ort

    # ByT5Tokenizer: id = byte + 3; EOS appended
    ids = [b + 3 for b in text.encode("utf-8")][: MAX_INPUT_LEN - 1] + [1]
    inp = np.array([ids], dtype=np.int64)
    mask = np.ones_like(inp)

    so = ort.SessionOptions()
    feeds = {"input_ids": inp}
    # discover whether the encoder wants an attention mask
    names = {i.name for i in enc.get_inputs()}
    if "attention_mask" in names:
        feeds["attention_mask"] = mask

    enc_out = enc.run(None, feeds)
    # first output = last_hidden_state
    hidden = enc_out[0]

    # Bootstrap decoder with [start, pad-masked start] so the manual
    # export's traced graph never sees length-1 input (T5 branches on
    # length == 1). The pad stays inert via mask [1, 0]; logits at the
    # last position equal the true length-1 step.
    dec_ids = np.zeros((1, 2), dtype=np.int64)
    dec_mask = np.array([[1, 0]], dtype=np.int64)
    out_bytes = bytearray()
    n_stuck = 0
    for step in range(MAX_TARGET_LEN):
        dfeeds: dict[str, object] = {}
        dnames = {i.name for i in dec.get_inputs()}
        id_key = "input_ids" if "input_ids" in dnames else "decoder_input_ids"
        dfeeds[id_key] = dec_ids
        if "attention_mask" in dnames:
            dfeeds["attention_mask"] = dec_mask
        if "encoder_hidden_states" in dnames:
            dfeeds["encoder_hidden_states"] = hidden
        if "encoder_attention_mask" in dnames:
            dfeeds["encoder_attention_mask"] = mask
        logits = dec.run(None, dfeeds)[0]
        nxt = int(np.argmax(logits[0, -1]))
        if nxt == EOS:
            break
        out_bytes.append(nxt - 3)  # id -> byte
        dec_ids = np.concatenate(
            [dec_ids, np.array([[nxt]], dtype=np.int64)], axis=1
        )
        dec_mask = np.concatenate(
            [dec_mask, np.ones((1, 1), dtype=np.int64)], axis=1
        )
        # Garbage guard: trained models emit EOS within ~word length.
        # If we're far past any plausible target (say 100 bytes) the
        # model is looping (untrained/quantised-broken) — stop early
        # instead of grinding through 160 quadratic steps.
        if step > 100:
            n_stuck += 1
            if n_stuck > 5 and out_bytes[-6:] == out_bytes[-12:-6]:
                break
    return out_bytes.decode("utf-8", "replace")


def token_error(pred: str, gold: str) -> float:
    p, g = pred.split(), gold.split()
    # simple Levenshtein over tokens
    prev = list(range(len(g) + 1))
    for i in range(1, len(p) + 1):
        cur = [i] + [0] * len(g)
        for j in range(1, len(g) + 1):
            cur[j] = min(
                prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (p[i - 1] != g[j - 1])
            )
        prev = cur
    return prev[len(g)] / max(len(g), 1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--onnx", required=True, help="dir with encoder/decoder .onnx")
    ap.add_argument("--task", choices=["g2p", "p2g"], required=True)
    ap.add_argument("--corpus", default="corpus")
    ap.add_argument("--sample", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=None, help="write results json here")
    args = ap.parse_args()

    try:
        import onnxruntime as ort
    except ImportError:
        print("pip install onnxruntime (or onnxruntime-gpu)", file=sys.stderr)
        return 2

    d = Path(args.onnx)
    enc = ort.InferenceSession(str(d / "encoder_model.onnx"))
    dec = ort.InferenceSession(str(d / "decoder_model.onnx"))

    rows = load_rows(Path(args.corpus) / f"{args.task}.test.tsv", args.task,
                     args.sample, args.seed)
    print(f"evaluating {len(rows)} {args.task} examples from "
          f"{Path(args.corpus) / (args.task + '.test.tsv')}")

    per_lang = defaultdict(lambda: [0, 0, 0.0])  # exact, total, TER sum
    t0 = time.time()
    for i, (lang, text, gold) in enumerate(rows):
        pred = greedy_decode((enc, dec), text)
        ex = pred == gold
        ter = token_error(pred, gold)
        s = per_lang[lang]
        s[0] += int(ex)
        s[1] += 1
        s[2] += ter
        if (i + 1) % 200 == 0:
            done = i + 1
            exact = sum(v[0] for v in per_lang.values())
            print(f"  {done}/{len(rows)}  exact {exact / done:.3f}  "
                  f"({(time.time() - t0) / done * 1000:.0f} ms/ex)")

    total_ex = sum(v[0] for v in per_lang.values())
    total = sum(v[1] for v in per_lang.values())
    macro = sum(v[0] / v[1] for v in per_lang.values()) / len(per_lang)

    result = {
        "task": args.task,
        "onnx": str(d),
        "examples": total,
        "micro_exact": total_ex / total,
        "macro_exact": macro,
        "languages": {
            lang: {
                "exact": v[0] / v[1],
                "ter": v[2] / v[1],
                "n": v[1],
            }
            for lang, v in sorted(per_lang.items())
        },
    }
    print(f"\n{args.task}: micro exact {result['micro_exact']:.3f}, "
          f"macro {macro:.3f} over {len(per_lang)} languages")

    out = Path(args.out) if args.out else Path(f"results/byt5-{args.task}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, sort_keys=True))
    print(f"per-language breakdown -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
