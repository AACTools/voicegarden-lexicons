#!/usr/bin/env python3
"""Fold Ukrainian kaikki IPA to the piper uk voice's conventions.

kaikki/Wiktionary Ukrainian marks non-syllabic glides with the inverted
breve below (i̯ u̯ a̯) and occasional syllabicity/length diacritics
(ɐ̣ ‿). The espeak-derived inventory of `piper-uk_UA-lada` writes
glides as j/w and carries no breve-below tokens at all.

Fold: i̯→j, u̯→w, a̯→a (glide diacritic mapped to espeak's glide
letters), combining dot below stripped (ɐ̣→ɐ), link marks (‿ …)
dropped. Validated against lada tokens.txt.

Usage: scripts/fold_ukrainian.py  (staging/ukr/kaikki.tsv ->
       staging/ukr/kaikki.folded.tsv)
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "staging/ukr/kaikki.tsv"
DST = REPO / "staging/ukr/kaikki.folded.tsv"

GLIDES = {"i": "j", "u": "w", "o": "w", "a": "a", "e": "j"}
DROP = set("‿…")
DOT_BELOW = "\u0323"
BREVE_BELOW = "\u032f"


def fold_token(ph: str) -> list[str]:
    if ph in DROP:
        return []
    if ph.endswith(BREVE_BELOW):
        base = ph[:-1]
        return [GLIDES.get(base, base)]
    ph = ph.replace(DOT_BELOW, "")
    return [ph] if ph else []


def main() -> int:
    kept = n = 0
    with DST.open("w", encoding="utf-8") as dst:
        for line in SRC.open(encoding="utf-8"):
            word, _, pron = line.partition("\t")
            n += 1
            out: list[str] = []
            for ph in pron.split():
                out.extend(fold_token(ph))
            if out:
                dst.write(f"{word}\t{' '.join(out)}\n")
                kept += 1
    print(f"folded {kept}/{n} -> {DST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
