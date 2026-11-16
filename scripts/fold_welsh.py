#!/usr/bin/env python3
"""Fold Welsh circumflex length marks to the voice's conventions.

In Welsh orthography the circumflex (tô, tê, tî ...) marks a LONG
vowel — WikiPron carries it as a precomposed circumflexed vowel
(ô ê î û ŵ ŷ). The cy voices' inventories carry none of those
(measured 4.7% per-word drop before the fold).

Fold: voiceless sonorants (r̥ ŋ̊ m̥ n̥ r̊) → their plain counterparts —
the cy voices' inventories carry no ring marks (Welsh <rh nh mh> lose
their voicelessness, as espeak cy does); lowered vowels (ɨ̞ i̞)
un-lowered; circumflexed vowels would map to base + ː (none occur in
the current scrape); stress accents stripped plain.

Usage: scripts/fold_welsh.py  (rewrites staging/cym/merged.tsv in
       place; re-run after re-harvest/merge)
"""
from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TARGET = REPO / "staging/cym/merged.tsv"

CIRC = "\u0302"
PLAIN = set("̞̥́̀̈̊")


def fold(pron: str) -> str:
    out = []
    for ph in pron.split():
        nfd = unicodedata.normalize("NFD", ph)
        if CIRC in nfd:
            base = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
            base = unicodedata.normalize("NFC", base)
            out.append(base + "ː")
            continue
        cleaned = unicodedata.normalize("NFC", "".join(
            c for c in nfd if c not in PLAIN
        ))
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
    print(f"cym: folded {cleaned}/{n} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
