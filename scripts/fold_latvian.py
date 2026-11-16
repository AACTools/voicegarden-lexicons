#!/usr/bin/env python3
"""Fold Latvian kaikki IPA to the piper lv voice's conventions.

kaikki/Wiktionary Latvian (only ~1.7k entries — en.wiktionary is thin
there) marks the three Latvian pitch accents with accented vowels
(à â ǣ …) and macrons plus explicit length (āː). espeak-ng Latvian —
what the lv voice consumes — writes plain long vowels (verified:
`espeak-ng -v lv --pho` renders māja as m'a:ja, no tone markers).

Fold: any vowel carrying a macron or pitch-accent mark becomes base
vowel + ː (tone information is lost — espeak loses it too); glide
breves stripped (i̯ → i, same as the Ukrainian fold); laminal /
dental / linking marks stripped. Tone information is lost by design —
espeak lv marks no tones. Thin scrape, NOTICE-flagged like kk/lt.

Usage: scripts/fold_latvian.py  (staging/lav/kaikki.tsv ->
       staging/lav/kaikki.folded.tsv)
"""
from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "staging/lav/kaikki.tsv"
DST = REPO / "staging/lav/kaikki.folded.tsv"

# length/pitch marks on Latvian vowels (macron, grave, circumflex,
# breve, caron, diaeresis, double macron below)
MARKS = set("̄̀̂̆̌̈̿")
# other marks stripped outright (glide breve, laminal, dental, linking)
STRIP = set("̯̻̪‿")


def fold_token(ph: str) -> list[str]:
    ph = "".join(c for c in ph if c not in STRIP)
    nfd = unicodedata.normalize("NFD", ph)
    if any(c in MARKS for c in nfd):
        base = "".join(
            c for c in nfd
            if c not in MARKS and unicodedata.category(c) != "Mn"
        )
        base = unicodedata.normalize("NFC", base)
        if base and base != "ː":
            return [base, "ː"]
        return []
    return [ph] if ph else []


def main() -> int:
    kept = n = 0
    with DST.open("w", encoding="utf-8") as dst:
        for line in SRC.open(encoding="utf-8"):
            word, _, pron = line.partition("\t")
            n += 1
            out: list[str] = []
            for ph in pron.split():
                for t in fold_token(ph):
                    if t == "ː" and out and out[-1].endswith("ː"):
                        continue  # macron + explicit length: one length mark
                    out.append(t)
            if out:
                dst.write(f"{word}\t{' '.join(out)}\n")
                kept += 1
    print(f"folded {kept}/{n} -> {DST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
