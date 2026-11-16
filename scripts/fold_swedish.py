#!/usr/bin/env python3
"""Fold Swedish pitch-accent marks out of the staged lexicon.

gruut's Swedish data marks tone accents with superscript digits,
standalone (annat → "² a …") or attached to the initial consonant
(söka → "²s …") — 12,633 of 45,364 rows. The sv voices' inventories
carry none of these (measured 27.7% per-word drop on the published
expanded swe bundle before this fold, counting the distill rows the
round-2 review found contaminated). espeak sv does not model pitch.

Fold: ¹ ² ³ stripped wherever they occur. Rewrites
staging/swe/merged.tsv in place; re-run after any re-harvest/merge.

Usage: scripts/fold_swedish.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TARGET = REPO / "staging/swe/merged.tsv"

TONES = "¹²³"


def fold(pron: str) -> str:
    out = []
    for ph in pron.split():
        ph = ph.translate({ord(c): None for c in TONES})
        if ph:
            out.append(ph)
    return " ".join(out)


def main() -> int:
    tmp = TARGET.with_suffix(".tsv.tmp")
    n = cleaned = 0
    with tmp.open("w", encoding="utf-8") as out:
        for line in TARGET.open(encoding="utf-8"):
            word, _, pron = line.partition("\t")
            n += 1
            folded = fold(pron)
            if folded != pron.strip():
                cleaned += 1
            if folded:
                out.write(f"{word}\t{folded}\n")
    tmp.replace(TARGET)
    print(f"swe: tone marks stripped from {cleaned}/{n} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
