#!/usr/bin/env python3
"""Fold WikiPron Mandarin (cmn) IPA to the piper zh voices' conventions.

WikiPron cmn writes Chao tone contours as runs of superscript digits
per syllable (⁵⁵ ³⁵ ²¹⁴ ⁵¹ …) with ⁻ marking sandhi-modified tones and
⁽⁾ optional ones; the espeak-derived token inventories of the piper
zh_CN voices carry plain tone digits 1–5 and no tie-bar affricates.

Fold (validated against piper-zh_CN-huayan-medium tokens.txt, 151
tokens): contours -> tone category {55:1, 35:2, 214:3, 21:3(half-third),
51:4, 53:4, 4:4, singles: identity}; sandhi/optional markers dropped;
ä->a; devoicing ring stripped (d̥->d); labialization stripped (ɻʷ->ɻ);
tie-bar affricates left as single units for the runtime ladder to
char-split; glide diacritics left attached (the vocab ships ̯ as a
standalone token, so the ladder also decomposes).

Usage: scripts/fold_mandarin.py  (staging/cmn/wikipron.tsv ->
       staging/cmn/wikipron.folded.tsv)
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "staging/cmn/wikipron.tsv"
DST = REPO / "staging/cmn/wikipron.folded.tsv"

SUP = set("⁰¹²³⁴⁵⁶⁷⁸⁹")
TONES = {"55": "1", "35": "2", "214": "3", "21": "3", "51": "4",
         "53": "4", "4": "4", "11": "3", "24": "2", "15": "1"}
DROP = set("⁻⁽⁾")


def fold_tokens(phones: list[str]) -> list[str] | None:
    out: list[str] = []
    i = 0
    while i < len(phones):
        ph = phones[i]
        if ph[0] in SUP:
            j = i
            while j < len(phones) and phones[j][0] in SUP:
                j += 1
            contour = "".join(
                c for p in phones[i:j] for c in p if c in SUP
            ).translate(str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789"))
            tone = TONES.get(contour)
            if tone is None:
                # unknown contour: fall back to the leading digit as the
                # tone category (audible but unnuanced)
                tone = contour[:1]
            out.append(tone)
            i = j
            continue
        if ph in DROP:
            i += 1
            continue
        ph = ph.replace("ä", "a").replace("̧", "")
        ph = ph.replace("̥", "").replace("̊", "")  # devoicing rings
        ph = ph.replace("ʷ", "").replace("g", "ɡ")
        if ph.startswith("ˀ"):
            # preglottalized vowel: split into glottal stop + vowel
            out.append("ʔ")
            ph = ph[1:] or "ə"
        if not ph:
            i += 1
            continue
        out.append(ph)
        i += 1
    return out or None


def main() -> int:
    kept = n = 0
    fallback = Counter()
    with DST.open("w", encoding="utf-8") as dst:
        for line in SRC.open(encoding="utf-8"):
            word, _, pron = line.partition("\t")
            n += 1
            folded = fold_tokens(pron.split())
            if folded is None:
                continue
            dst.write(f"{word}\t{' '.join(folded)}\n")
            kept += 1
    print(f"folded {kept}/{n} -> {DST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
