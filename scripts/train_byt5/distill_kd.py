#!/usr/bin/env python3
"""Sequence-level knowledge distillation: teacher (small) -> student (tiny).

Two phases, so the expensive teacher inference runs once:

  1. GENERATE: the trained small model (e.g. runs-v3-small/g2p-byt5-small/
     final) produces outputs for every TRAIN row of the corpus, batched on
     GPU. Gold val/test splits are kept (symlinked) — the student is always
     evaluated against TRUTH, never against the teacher, so the numbers
     stay comparable with from-scratch training.

  2. TRAIN: invoke train.py --tiny --corpus <kd-dir>. Same machinery
     (balanced sampling, early stop, exact-match checkpoint selection);
     only the train targets are the teacher's sequences (Kim & Rush 2016
     sequence-level KD).

  The corpus dir layout mirrors corpus/: kd-dir/g2p.train.tsv (teacher
  targets), g2p.val.tsv + g2p.test.tsv (gold, symlinked).

Usage (on the training box):
  python3 distill_kd.py --task g2p \
      --teacher runs-v3-small/g2p-byt5-small/final \
      --corpus corpus --out corpus-kd-g2p
  python3 train.py --task g2p --tiny --corpus corpus-kd-g2p \
      --out runs-v3-kd-tiny

Then compare eval-onnx of runs-v3-kd-tiny vs runs-v3-tiny (from-scratch)
on the gold test split — the winner ships.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import torch
from transformers import AutoModelForSeq2SeqLM, ByT5Tokenizer

MAX_INPUT = 128
MAX_TARGET = 160


def load_rows(path: Path, task: str) -> list[tuple[str, str, str]]:
    """-> (lang, input_text, gold_target) — keeps the corpus line shape."""
    rows = []
    for line in path.open(encoding="utf-8"):
        parts = line.rstrip("\n").split("\t")
        if len(parts) != 3:
            continue
        lang, a, b = parts
        rows.append((lang, a, b))
    return rows


@torch.no_grad()
def batched_generate(model, tok, texts: list[str], batch: int) -> list[str]:
    """The same generation path the lexicon distiller uses (greedy,
    byte-level tokenizer, max_target 160) — teacher and pseudo-labeler
    inference stay identical."""
    preds: list[str] = []
    model.eval()
    for i in range(0, len(texts), batch):
        chunk = texts[i : i + batch]
        enc = tok(chunk, return_tensors="pt", padding=True,
                  truncation=True, max_length=MAX_INPUT).to("cuda")
        out = model.generate(**enc, max_length=MAX_TARGET, num_beams=1)
        preds.extend(tok.batch_decode(out, skip_special_tokens=True))
        if (i // batch) % 50 == 0:
            print(f"  {i + len(chunk)}/{len(texts)}", file=sys.stderr)
    return preds


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task", choices=["g2p", "p2g"], required=True)
    ap.add_argument("--teacher", required=True, help="trained small checkpoint dir")
    ap.add_argument("--corpus", default="corpus")
    ap.add_argument("--out", required=True, help="kd corpus dir to write")
    ap.add_argument("--batch", type=int, default=256)
    args = ap.parse_args()

    assert torch.cuda.is_available(), "teacher inference needs CUDA"
    model = AutoModelForSeq2SeqLM.from_pretrained(args.teacher).cuda().eval()
    tok = ByT5Tokenizer.from_pretrained(args.teacher)

    corpus = Path(args.corpus)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    train_path = corpus / f"{args.task}.train.tsv"
    rows = load_rows(train_path, args.task)
    print(f"{args.task}: {len(rows)} train rows -> teacher targets")

    texts = [f"<{lang}>: {a}" for lang, a, _ in rows]
    teacher_out = batched_generate(model, tok, texts, args.batch)

    agree = 0
    with (out / f"{args.task}.train.tsv").open("w", encoding="utf-8") as f:
        for (lang, a, gold), pred in zip(rows, teacher_out):
            f.write(f"{lang}\t{a}\t{pred}\n")
            agree += int(pred == gold)
    print(f"teacher train exact-match: {agree / len(rows) * 100:.1f}% "
          f"(the student's soft ceiling)")

    # gold val/test stay: student evals against truth, not the teacher
    for split in ("val", "test"):
        src = (corpus / f"{args.task}.{split}.tsv").resolve()
        dst = out / f"{args.task}.{split}.tsv"
        if not dst.exists():
            dst.symlink_to(src)
    # the other task's files are absent: train.py --task selects only this one
    print(f"kd corpus ready: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
