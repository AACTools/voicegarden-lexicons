#!/usr/bin/env python3
"""Fold Lithuanian kaikki IPA to the bundle's conventions.

kaikki Lithuanian (25,783 words — 59x the WikiPron base of 437)
carries tone digits (² …), tongue-position diacritics (ʊ̟ ɑ̝ …) and
half-length marks (ɪˑ) that the WikiPron primary does not. The only
lt voice is a coqui grapheme model, so there is no voice inventory to
satisfy — the fold aligns the fill data with the primary's convention
style so the merged lexicon stays single-convention.

Fold: tone digits dropped; advanced/retracted/raised/lowered
diacritics stripped; half-long ˑ stripped.

Usage: scripts/fold_lithuanian.py  (staging/lit/kaikki.tsv ->
       staging/lit/kaikki.folded.tsv)
"""
from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "staging/lit/kaikki.tsv"
DST = REPO / "staging/lit/kaikki.folded.tsv"

STRIP = set("̟̘̙̝ˑ")
TONES = set("¹²³⁰")


def fold_token(ph: str) -> list[str]:
    if set(ph) <= TONES:
        return []
    nfd = unicodedata.normalize("NFD", ph)
    cleaned = unicodedata.normalize(
        "NFC", "".join(c for c in nfd if c not in STRIP and c not in TONES)
    )
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
