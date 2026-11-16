#!/usr/bin/env python3
"""Fold Afrikaans IPA to the mimic3 voice's conventions.

The WikiPron broad scrape uses ʋ, ɦ, ɲ, ɫ, χ and glide breves
(ə̯ i̯ …); the mimic3-af_ZA voice's inventory has none of those (it
does carry x, ŋ, ə, ʃ, ʔ). Measured 43.8% per-word drop before the
fold.

Fold: χ→x (espeak af's own /x/ for <g> — verified via `espeak-ng -v af
--pho`), ɦ→h, ʋ→v, ɲ→n, ɫ→l, glide breves stripped (ə̯→ə …).

Usage: scripts/fold_afrikaans.py  (rewrites staging/afr/merged.tsv in
       place; re-run after re-harvest/merge)
"""
from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TARGET = REPO / "staging/afr/merged.tsv"

MAP = {"χ": "x", "ɦ": "h", "ʋ": "v", "ɲ": "n", "ɫ": "l"}
BREVE = "\u032f"


def fold(pron: str) -> str:
    out = []
    for ph in pron.split():
        ph = MAP.get(ph) or ph
        if ph.endswith(BREVE):
            ph = ph[:-1]
        nfd = unicodedata.normalize("NFD", ph)
        cleaned = unicodedata.normalize("NFC", "".join(
            c for c in nfd if c != BREVE
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
    print(f"afr: folded {cleaned}/{n} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
