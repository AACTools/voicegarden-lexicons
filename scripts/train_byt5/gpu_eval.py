#!/usr/bin/env python3
"""GPU acceptance eval: batched generate over the test split.

Uses the saved HF checkpoints (runs/<task>-byt5-small/final) with the
Trainer's own generation path — the exact same setup that evaluated
2,000 val examples in ~4 min during training. Writes the same JSON
shape as eval_onnx.py (results/byt5-<task>.json) plus per-language
breakdown, so the gates/leaderboard comparisons are unchanged.

Usage:
  python3 gpu_eval.py --task g2p --sample 4000
  python3 gpu_eval.py --task p2g --sample 4000
"""

from __future__ import annotations

import argparse
import json
import random
import time
from collections import defaultdict
from pathlib import Path

MAX_TARGET_LEN = 160


def load_rows(path: Path, task: str):
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) == 3:
                lang, a, b = parts
                rows.append((lang, f"<{lang}>: {a}", b))
    return rows


def token_error(pred: str, gold: str) -> float:
    p, g = pred.split(), gold.split()
    prev = list(range(len(g) + 1))
    for i in range(1, len(p) + 1):
        cur = [i] + [0] * len(g)
        for j in range(1, len(g) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1,
                         prev[j - 1] + (p[i - 1] != g[j - 1]))
        prev = cur
    return prev[len(g)] / max(len(g), 1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task", choices=["g2p", "p2g"], required=True)
    ap.add_argument("--model", default=None)
    ap.add_argument("--corpus", default="corpus")
    ap.add_argument("--sample", type=int, default=4000)
    ap.add_argument("--batch", type=int, default=128)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    import torch
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    model_dir = args.model or f"runs/{args.task}-byt5-small/final"
    tok = AutoTokenizer.from_pretrained(model_dir)
    model = AutoModelForSeq2SeqLM.from_pretrained(model_dir)
    model.to("cuda").eval()

    rows = load_rows(Path(args.corpus) / f"{args.task}.test.tsv", args.task)
    if args.sample and args.sample < len(rows):
        rng = random.Random(args.seed)
        rows = rng.sample(rows, args.sample)
    print(f"{args.task}: {len(rows)} test examples, batch {args.batch}")

    per_lang: dict[str, list] = defaultdict(lambda: [0, 0, 0.0])
    t0 = time.time()
    done = 0
    for i in range(0, len(rows), args.batch):
        chunk = rows[i : i + args.batch]
        enc = tok([r[1] for r in chunk], return_tensors="pt", padding=True,
                  truncation=True, max_length=128).to("cuda")
        with torch.no_grad():
            out = model.generate(**enc, max_length=MAX_TARGET_LEN,
                                 num_beams=1)  # greedy, matching the runtime
        preds = tok.batch_decode(out, skip_special_tokens=True)
        for (lang, _inp, gold), pred in zip(chunk, preds, strict=True):
            s = per_lang[lang]
            s[0] += int(pred == gold)
            s[1] += 1
            s[2] += token_error(pred, gold)
        done += len(chunk)
        rate = done / (time.time() - t0)
        exact = sum(v[0] for v in per_lang.values()) / done
        print(f"  {done}/{len(rows)}  exact {exact:.3f}  {rate:.0f} ex/s",
              flush=True)

    total = sum(v[1] for v in per_lang.values())
    micro = sum(v[0] for v in per_lang.values()) / total
    macro = sum(v[0] / v[1] for v in per_lang.values()) / len(per_lang)
    ter = sum(v[2] for v in per_lang.values()) / total

    result = {
        "task": args.task,
        "model": model_dir,
        "examples": total,
        "micro_exact": micro,
        "macro_exact": macro,
        "token_error_rate": ter,
        "languages": {
            lang: {"exact": v[0] / v[1], "ter": v[2] / v[1], "n": v[1]}
            for lang, v in sorted(per_lang.items())
        },
    }
    out_path = Path(f"results/byt5-{args.task}.json")
    out_path.write_text(json.dumps(result, indent=1, sort_keys=True))
    print(f"\n{args.task}: micro {micro:.3f}  macro {macro:.3f}  TER {ter:.3f}"
          f"  over {len(per_lang)} languages -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
