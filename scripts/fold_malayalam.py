#!/usr/bin/env python3
"""Fold Malayalam IPA to the piper ml voice's conventions.

WikiPron mal uses ä for the long open vowel (like Nepali), ɨ̆ (central
vowel with breve), and voiced-aspirated dentals (d̪ʱ bʱ ɡʱ …). The
piper ml voice's inventory carries none of these (measured 6.6%
per-word drop before the fold).

Fold: ä→aː, breve stripped from ɨ̆, dental diacritic stripped, ʱ→ʰ
(the voice ships ʰ-style aspiration like the ne voices), stray
dotted-circle marks dropped.

Usage: scripts/fold_malayalam.py  (rewrites staging/mal/merged.tsv in
       place; re-run after re-harvest/merge)
"""
from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TARGET = REPO / "staging/mal/merged.tsv"

STRIP = set("̪̆◌")


def fold(pron: str) -> str:
    out = []
    for ph in pron.split():
        if set(ph) <= STRIP:
            continue
        ph = ph.replace("ä", "aː")
        nfd = unicodedata.normalize("NFD", ph)
        cleaned = unicodedata.normalize("NFC", "".join(
            c for c in nfd if c not in STRIP
        ))
        cleaned = cleaned.replace("ʱ", "ʰ")
        if cleaned:
            out.append(cleaned)
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
    print(f"mal: folded {cleaned}/{n} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
