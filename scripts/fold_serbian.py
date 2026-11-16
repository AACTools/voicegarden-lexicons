#!/usr/bin/env python3
"""Fold Serbo-Croatian (hbs) pitch accents to the voices' conventions.

WikiPron/Wiktionary hbs transcriptions carry the four-way Serbo-
Croatian pitch-accent system as diacritics: short rising (caron: ǎ),
long rising (caron + length: ǎː), short falling (grave-legacy, mostly
merged: à), long falling (circumflex: â, ê …), plus inverted-breve
(late) variants and syllabic markers. The piper sr voice's espeak-
derived inventory (piper-sr_RS-serbski_institut-medium, 156 tokens)
carries NONE of these marks — measured 98.7% per-word drop before this
fold. espeak sr does not model pitch accent, so the compatible
convention is plain vowels with length preserved.

Fold: pitch-accent diacritics (caron, circumflex, grave, acute,
double grave, double inverted breve) stripped, length (ː) kept;
syllabic marker (vertical line below) stripped; rare dental/minus
marks stripped. Applies to both scripts (lexicon-sr Cyrillic,
lexicon-hr Latin).

Usage: scripts/fold_serbian.py  (rewrites staging/hbs/lexicon-{sr,hr}.tsv
       in place from the pitch-marked sources in merged.tsv)
"""
from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HBS = REPO / "staging/hbs"

STRIP = set("̩̪̠̯̠̂̌̀́̏̑")
CROSS = {"⁻", "‿"}
KEEP = "ː"


def fold(pron: str) -> str:
    out = []
    for ph in pron.split():
        if ph in CROSS:
            continue
        nfd = unicodedata.normalize("NFD", ph)
        cleaned = "".join(c for c in nfd if c not in STRIP)
        cleaned = unicodedata.normalize("NFC", cleaned)
        if cleaned:
            out.append(cleaned)
    return " ".join(out)


def main() -> int:
    # both script splits derive from merged.tsv (which still carries the
    # accents); fold the union, then re-split by script so the fold is
    # idempotent
    merged = HBS / "merged.tsv"
    rows = []
    for line in merged.open(encoding="utf-8"):
        word, _, pron = line.partition("\t")
        rows.append((word, fold(pron.strip())))
    with (HBS / "merged.folded.tsv").open("w", encoding="utf-8") as f:
        for w, p in rows:
            if p:
                f.write(f"{w}\t{p}\n")
    # regenerate the script splits from the folded union
    hr = (HBS / "lexicon-hr.tsv").open("w", encoding="utf-8")
    sr = (HBS / "lexicon-sr.tsv").open("w", encoding="utf-8")
    n_hr = n_sr = 0
    for w, p in rows:
        if not p:
            continue
        if any("CYRILLIC" in unicodedata.name(c, "") for c in w[:3]):
            sr.write(f"{w}\t{p}\n")
            n_sr += 1
        else:
            hr.write(f"{w}\t{p}\n")
            n_hr += 1
    hr.close()
    sr.close()
    print(f"folded hbs: hr (Latin) {n_hr}, sr (Cyrillic) {n_sr} -> lexicon-{{hr,sr}}.tsv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
