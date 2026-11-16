#!/usr/bin/env python3
"""Fold Vietnamese kaikki IPA to the piper vi voices' conventions.

kaikki/Wiktionary Vietnamese (Hanoi) writes tones as Chao tone-LETTER
runs (˧˧ ˧˦ ˧˨ ˨˩ ˧˩ ˦ˀ˥); the piper vi voices' espeak-derived
inventories carry tone DIGITS. The mapping below was derived from
espeak-ng itself (`espeak-ng -v vi --pho` on the six-tone ma-set:
ngang=7, huyền=2, sắc=3, hỏi=4, ngã=5, nặng=6) and the observed
kaikki contours (má/mà/mả/mã/mạ spot-verified).

Also folded: unreleased/advanced stop diacritics (t̚ k̚ p̚ k̟̚ ŋ̟ →
plain), ï→i, nasalization ~ dropped; tie-bar labiovelars (k͡p) keep
their tie for the runtime ladder to char-split.

Usage: scripts/fold_vietnamese.py  (staging/vie/kaikki.tsv ->
       staging/vie/kaikki.folded.tsv)
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "staging/vie/kaikki.tsv"
DST = REPO / "staging/vie/kaikki.folded.tsv"

TL = set("˧˨˦˩˥ˀ")
TONES = {
    "˧˧": "7",   # ngang (level 33)
    "˧˦": "3",   # sắc (rising 35)
    "˧˥": "3",   # sắc variant 35
    "˨˥": "3",
    "˨˩": "2",   # huyền (falling 21)
    "˧˩": "4",   # hỏi (falling 31, kaikki's simplified dipping)
    "˧˩˧": "4",  # hỏi dipping
    "˦ˀ˥": "5",  # ngã (creaky rising)
    "˨ˀ˨ˀ": "5",
    "˧˨": "6",   # nặng (glottalized fall 32)
    "˩˩": "6",
    "˩": "6", "˨": "2", "˧": "7", "˦": "3", "˥": "3",  # single-letter residue
}
STRIP = "̟̚"


def fold_token(ph: str) -> list[str]:
    if ph == "~":
        return []
    ph = ph.translate({ord(c): None for c in STRIP}).replace("ï", "i")
    return [ph] if ph else []


def main() -> int:
    kept = n = unmapped_tones = 0
    with DST.open("w", encoding="utf-8") as dst:
        for line in SRC.open(encoding="utf-8"):
            word, _, pron = line.partition("\t")
            n += 1
            toks = pron.split()
            out: list[str] = []
            i = 0
            while i < len(toks):
                if toks[i][0] in TL:
                    j = i
                    while j < len(toks) and toks[j][0] in TL:
                        j += 1
                    run = "".join(toks[i:j])
                    tone = TONES.get(run)
                    if tone is None:  # unknown contour: level tone
                        tone = "7"
                        unmapped_tones += 1
                    out.append(tone)
                    i = j
                    continue
                out.extend(fold_token(toks[i]))
                i += 1
            if out:
                dst.write(f"{word}\t{' '.join(out)}\n")
                kept += 1
    print(f"folded {kept}/{n} -> {DST} (unmapped tone runs: {unmapped_tones})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
