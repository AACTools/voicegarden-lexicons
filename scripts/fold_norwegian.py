#!/usr/bin/env python3
"""Fold Norwegian Bokmål pitch accents to the voice's conventions.

WikiPron nob carries Norwegian tonal accents as superscript digits (² ¹)
and circumflex-marked long vowels (ôː ê â …). The no voice's espeak-
derived inventory carries none of these (measured 6.0% per-word drop
before the fold).

Fold: tone digits dropped; circumflex/acute/grave accents stripped with
length preserved. Norwegian pitch accent is lost by design — espeak no
does not model it.

Usage: scripts/fold_norwegian.py  (rewrites staging/nob/merged.tsv and
       staging/nor/merged.tsv in place; re-run after re-harvest/merge)
"""
from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TARGETS = [REPO / "staging/nob/merged.tsv", REPO / "staging/nor/merged.tsv"]

STRIP = set("́̂̀̆̌̈̌")
TONES = set("¹²³⁴")


def fold(pron: str) -> str:
    out = []
    for ph in pron.split():
        if set(ph) <= TONES:
            continue
        nfd = unicodedata.normalize("NFD", ph)
        cleaned = "".join(c for c in nfd if c not in STRIP and c not in TONES)
        cleaned = unicodedata.normalize("NFC", cleaned)
        if cleaned:
            out.append(cleaned)
    return " ".join(out)


def main() -> int:
    for path in TARGETS:
        if not path.exists():
            continue
        tmp = path.with_suffix(".tsv.tmp")
        n = cleaned = 0
        with tmp.open("w", encoding="utf-8") as out:
            for line in path.open(encoding="utf-8"):
                word, _, pron = line.partition("\t")
                n += 1
                folded = fold(pron)
                if folded != pron.strip():
                    cleaned += 1
                if folded:
                    out.write(f"{word}\t{folded}\n")
        tmp.replace(path)
        print(f"{path.name}: accents stripped from {cleaned}/{n} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
