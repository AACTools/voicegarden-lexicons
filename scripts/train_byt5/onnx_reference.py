#!/usr/bin/env python3
"""Minimal, correct ONNX inference for the floravox ByT5 G2P/P2G models.

This is THE reference consumer — it encodes every convention the models
were trained with. If your integration produces garbage, compare it
against this script before anything else.

THE CONVENTIONS (each one cost us hours; skip none):

1. id = byte + 3. ByT5Tokenizer reserves ids 0/1/2 (pad/eos/unk) and
   maps bytes to byte+3. Feeding raw bytes produces confident nonsense.
2. EOS (id 1) is appended to the ENCODER input, exactly as
   ByT5Tokenizer(add_special_tokens=True) did at training time.
3. Language tag: "<iso3>:" prefix, optionally variety-suffixed
   (<eng-US>, <por-BR>, <spa-ES> ...). The tag must exist in training.
4. The decoder graph needs an explicit causal attention mask (HF T5
   bakes a mask-less branch at length 1 into traced graphs) and must
   never be called with a length-1 prefix — bootstrap with [0, 0]
   under mask [1, 0], which is mathematically the true first step.
5. Outputs: id 1 = stop; anything else is byte = id - 3. Phonemes are
   space-separated: "ɡ a t o".

Usage:
  python3 onnx_reference.py --dir onnx/small-g2p --text "<spa-ES>: gato"
  python3 onnx_reference.py --dir onnx/small-p2g --text "<deu>: ʃ aɪ n"

Requirements: onnxruntime, numpy.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import onnxruntime as ort

EOS = 1
MAX_INPUT = 127  # leave room for EOS
MAX_GEN = 64


def load(dirname: str) -> tuple[ort.InferenceSession, ort.InferenceSession]:
    d = Path(dirname)
    enc = ort.InferenceSession(str(d / "encoder_model.onnx"))
    dec = ort.InferenceSession(str(d / "decoder_model.onnx"))
    return enc, dec


def run(enc: ort.InferenceSession, dec: ort.InferenceSession, text: str) -> str:
    # 1+2: byte+3 ids, EOS appended
    ids = [b + 3 for b in text.encode("utf-8")][:MAX_INPUT] + [EOS]
    inp = np.array([ids], dtype=np.int64)
    mask = np.ones_like(inp)
    hidden = enc.run(None, {"input_ids": inp, "attention_mask": mask})[0]

    names = {i.name for i in dec.get_inputs()}
    key = "input_ids" if "input_ids" in names else "decoder_input_ids"

    # 4: length-2 bootstrap, masked pad
    dec_ids = np.zeros((1, 2), dtype=np.int64)
    dec_mask = np.array([[1, 0]], dtype=np.int64)
    out = bytearray()
    for _ in range(MAX_GEN):
        feeds = {key: dec_ids}
        if "attention_mask" in names:
            feeds["attention_mask"] = dec_mask
        if "encoder_hidden_states" in names:
            feeds["encoder_hidden_states"] = hidden
        if "encoder_attention_mask" in names:
            feeds["encoder_attention_mask"] = mask
        logits = dec.run(None, feeds)[0]
        nxt = int(np.argmax(logits[0, -1]))
        if nxt == EOS:
            break
        # 5: byte = id - 3 (space = 35-3 = 32 falls out naturally)
        out.append(nxt - 3)
        dec_ids = np.concatenate([dec_ids, np.array([[nxt]], dtype=np.int64)], axis=1)
        dec_mask = np.concatenate([dec_mask, np.ones((1, 1), dtype=np.int64)], axis=1)
    return out.decode("utf-8", "replace")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", required=True, help="dir with encoder/decoder .onnx")
    ap.add_argument("--text", required=True, help='e.g. "<spa-ES>: gato"')
    args = ap.parse_args()
    enc, dec = load(args.dir)
    print(run(enc, dec, args.text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
