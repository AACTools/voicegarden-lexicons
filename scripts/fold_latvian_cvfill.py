#!/usr/bin/env python3
"""Fold the CV-alignment harvest (new-word rows) to the aivars voice
inventory, for the staged `lv` cv-fill.

The alignment phones come from MFA's Phonetisaurus G2P trained on the
kaikki seed, so they already share its conventions; three artifacts
remain versus the piper-lv_LV-aivars inventory:

- vʷ → v (labiovelar glide merged; the inventory carries plain v)
- U+035C stray tie ('͜', the G2P's double-inverted-breve leak — distinct
  from the legitimate affricate tie U+0361) → dropped
- ̟ (advanced) → dropped, leaving the plain phone + any length

Usage: scripts/fold_latvian_cvfill.py  (runs-cv-scope/lv-new.tsv ->
       staging/lav/cv-fill.tsv)
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "runs-cv-scope/lv-new.tsv"
DST = REPO / "staging/lav/cv-fill.tsv"


def fold_token(ph: str) -> str:
    ph = ph.replace("vʷ", "v")
    ph = ph.replace("\u035c", "")
    ph = ph.replace("\u031f", "")
    return ph


def main() -> int:
    n = changed = 0
    with SRC.open(encoding="utf-8") as src, DST.open("w", encoding="utf-8") as dst:
        for line in src:
            word, _, pron = line.partition("\t")
            folded = " ".join(t for t in (fold_token(p) for p in pron.split()) if t)
            if folded != pron.strip():
                changed += 1
            dst.write(f"{word}\t{folded}\n")
            n += 1
    print(f"folded {n} rows ({changed} changed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
