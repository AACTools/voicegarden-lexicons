#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fold Kazakh kaikki IPA to the kk voice's conventions.

kaikki Kazakh carries glide breves (ɪ̯), tongue-position diacritics
(o̙ ɑ̝ e̘ …) and aspiration (tʰ pʰ); the kk voice's inventory has none
of these (measured 6.1% per-word drop before the fold, on top of the
thin WikiPron base of 669 words).

Fold: glide breves stripped, advanced/retracted/raised/lowered/short
diacritics stripped, aspiration stripped. kaikki (2,205 words) fills
the WikiPron primary (669).

Usage: scripts/fold_kazakh.py  (staging/kaz/kaikki.tsv ->
       staging/kaz/kaikki.folded.tsv)
"""
from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "staging/kaz/kaikki.tsv"
DST = REPO / "staging/kaz/kaikki.folded.tsv"

STRIP = set("̯̘̙̝̆ʰ̞̥̽")


def fold_token(ph: str) -> list[str]:
    nfd = unicodedata.normalize("NFD", ph)
    cleaned = unicodedata.normalize("NFC", "".join(c for c in nfd if c not in STRIP))
    return [cleaned] if cleaned else []


def main() -> int:
    kept = n = 0
    with DST.open("w", encoding="utf-8") as dst:
        for line in SRC.open(encoding="utf-8"):
            word, _, pron = line.partition("\t")
            n += 1
            out = [t for ph in pron.split() for t in fold_token(ph)]
            if out:
                dst.write(f"{word}\t{' '.join(out)}\n")
                kept += 1
    print(f"folded {kept}/{n} -> {DST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
