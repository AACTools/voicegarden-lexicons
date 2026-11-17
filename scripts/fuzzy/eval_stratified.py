#!/usr/bin/env python3
"""Severity-stratified, k-best evaluation for the fuzzy phoneme decoder.

Top-1 exact on the whole corrupted test set mixes easy (1 corrupted
site) and brutal (4+) examples into one number. For an AAC input
method the shape that matters is: exact-match by severity band, and how
far down the beam the right answer sits when top-1 misses.

Severity proxy: normalised edit distance between the observed input and
the canonical gold (0 = identity, higher = heavier corruption). No
severity metadata is needed from the corpus generator — it is derived
per row.

Beam search runs over the exported ONNX pair (no KV cache; the decoder
re-feeds the full prefix each step, same as the greedy reference).

Usage:
  python eval_stratified.py --onnx ONNX_DIR --corpus DIR \
      [--task g2p] [--sample 500] [--beam 5] [--seed 7]
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

import numpy as np
import onnxruntime as ort


def levenshtein(a, list_b):
    b = list_b
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def load_sessions(d: Path):
    enc = ort.InferenceSession(str(d / "encoder_model.onnx"))
    dec = ort.InferenceSession(str(d / "decoder_model.onnx"))
    return enc, dec


def encode_text(text: str) -> np.ndarray:
    ids = [b + 3 for b in text.encode("utf-8")][:127] + [1]
    return np.array([ids], dtype=np.int64)


def beam_decode(enc, dec, text: str, beam: int = 5, max_len: int = 64):
    """Byte-level beam search; returns list of (string, logprob) desc.

    Termination is standard: stop only when every active candidate is
    already worse than the beam's worst finished hypothesis — NOT when
    `beam` hypotheses happen to have emitted EOS (early low-probability
    EOS must not evict a strong active continuation).
    """
    inp = encode_text(text)
    mask = np.ones_like(inp)
    hidden = enc.run(None, {"input_ids": inp, "attention_mask": mask})[0]

    # candidate: (logprob, ids, mask); bootstrap [pad, pad-masked] so the
    # traced length-2 graph computes true step-1 logits at the last slot
    start = np.zeros((1, 2), dtype=np.int64)
    start_mask = np.array([[1, 0]], dtype=np.int64)
    active = [(0.0, start, start_mask)]
    finished: list[tuple[float, np.ndarray, np.ndarray]] = []
    for _ in range(max_len):
        next_round = []
        for lp, ids, m in active:
            logits = dec.run(None, {
                "input_ids": ids, "attention_mask": m,
                "encoder_hidden_states": hidden,
                "encoder_attention_mask": mask,
            })[0][0, -1]
            logp = logits - logits.max()
            logp = logp - np.log(np.exp(logp).sum())
            for t in np.argsort(-logp)[: beam]:
                nlp = lp + float(logp[t])
                if int(t) == 1:  # EOS
                    finished.append((nlp, ids, m))
                else:
                    next_round.append((nlp,
                                       np.concatenate([ids, [[int(t)]]], axis=1),
                                       np.concatenate([m, [[1]]], axis=1)))
        next_round.sort(key=lambda c: -c[0])
        active = next_round[:beam]
        if not active:
            break
        finished.sort(key=lambda c: -c[0])
        if len(finished) >= beam and finished[beam - 1][0] >= active[0][0]:
            break
    finished.sort(key=lambda c: -c[0])
    out = []
    for lp, ids, m in finished[:beam]:
        byts = bytes(int(x) - 3 for x in ids[0, 2:] if int(x) - 3 >= 0)
        out.append((byts.decode("utf-8", "replace"), lp))
    return out


def severity(observed: str, gold: str) -> float:
    o, g = observed.split(), gold.split()
    return levenshtein(o, g) / max(len(g), 1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--onnx", required=True)
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--task", default="g2p")
    ap.add_argument("--sample", type=int, default=500)
    ap.add_argument("--beam", type=int, default=5)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    rows = []
    with open(Path(args.corpus) / f"{args.task}.test.tsv", encoding="utf-8") as f:
        for line in f:
            p = line.rstrip("\n").split("\t")
            if len(p) == 3:
                rows.append(p)
    rng = random.Random(args.seed)
    rng.shuffle(rows)
    rows = [r for r in rows if r[1] != r[2]][: args.sample]  # corrupted only
    print(f"{len(rows)} corrupted test rows")

    enc, dec = load_sessions(Path(args.onnx))

    bands = {"0-0.15": [], "0.15-0.35": [], "0.35-0.6": [], "0.6+": []}
    topk_hits = [0] * (args.beam + 1)
    n = 0
    for lang, observed, gold in rows:
        text = f"<{lang}>: {observed}"
        cands = beam_decode(enc, dec, text, beam=args.beam)
        sev = severity(observed, gold)
        hit = 0
        for k, (s, _lp) in enumerate(cands, 1):
            if s == gold:
                hit = k
                break
        if hit:
            for k in range(hit, args.beam + 1):
                topk_hits[k] += 1
        n += 1
        band = ("0-0.15" if sev <= 0.15 else "0.15-0.35" if sev <= 0.35
                else "0.35-0.6" if sev <= 0.6 else "0.6+")
        bands[band].append(hit == 1)
        if n % 50 == 0:
            print(f"  {n}/{len(rows)}  top1={topk_hits[1]/n:.3f} "
                  f"top{args.beam}={topk_hits[args.beam]/n:.3f}")

    report = {
        "n": n,
        "beam": args.beam,
        "top1_exact": topk_hits[1] / n,
        "by_band": {b: {"n": len(v), "top1_exact": (sum(v) / len(v)) if v else None}
                    for b, v in bands.items()},
        "topk_cumulative": {f"top{k}": topk_hits[k] / n
                            for k in range(1, args.beam + 1)},
    }
    print(json.dumps(report, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
