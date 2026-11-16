#!/usr/bin/env python3
"""Fold Finnish juncture marks out of the staged lexicon.

Wiktionary Finnish IPA marks syllable-boundary/hiatus juncture with
the modifier letter ˣ (U+02E3), attached to the preceding vowel
(ɑːˣ) in WikiPron rows and as a separate token in kaikki rows. The
piper fi voices' espeak-derived inventory (piper-fi_FI-harri-medium)
does not carry ˣ at all — measured 15.50% per-word corpus drop from
this single symbol before the fold (26,967 of 174,010 words).

Fold: ˣ removed wherever it occurs (attached or standalone). No
segmental information is lost — it is a juncture notation, not a
phone. Rewrites staging/fin/merged.tsv in place (sources untouched);
re-run merge_sources.py + this fold after any re-harvest.

Usage: scripts/fold_finnish.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MERGED = REPO / "staging/fin/merged.tsv"


def fold(pron: str) -> str:
    return " ".join(ph.replace("ˣ", "") for ph in pron.split()) \
        .replace("  ", " ").strip()


def main() -> int:
    tmp = MERGED.with_suffix(".tsv.tmp")
    n = cleaned = 0
    with tmp.open("w", encoding="utf-8") as out:
        for line in MERGED.open(encoding="utf-8"):
            word, _, pron = line.partition("\t")
            n += 1
            folded = fold(pron)
            if folded != pron.strip():
                cleaned += 1
            if folded:
                out.write(f"{word}\t{folded}\n")
    tmp.replace(MERGED)
    print(f"fin: ˣ stripped from {cleaned}/{n} rows -> {MERGED}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
