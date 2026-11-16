#!/usr/bin/env python3
"""Fold Vietnamese kaikki IPA to the piper vi voices' conventions.

kaikki/Wiktionary Vietnamese (Hanoi) writes tones as Chao tone-LETTER
runs (˧˧ ˧˦ ˧˨ ˨˩ ˧˩ ˦ˀ˥); the piper vi voices' espeak-derived
inventories carry tone DIGITS. The mapping follows espeak-ng's
phoneme definitions (phsource/ph_vietnam): 1=ngang, 2=huyền, 3=sắc,
4=hỏi, 5=ngã, 6=nặng. Note tone 7 is espeak's clause-final FALLING
variant of ngang — isolated-word checks mis-derive it, so mid-sentence
behavior is authoritative (verified: `echo "ma ba" | espeak-ng -v vi
-q -x` → tone 1 mid-clause, 7 only clause-final; use 1 here).

Also folded: unreleased/advanced stop diacritics (t̚ k̚ p̚ k̟̚ ŋ̟ →
plain), ï→i, stray superscript digit tone marks (⁶ ³ …) mapped through
the same table, nasalization ~ dropped; tie-bar labiovelars (k͡p) keep
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
SUPDIG = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
TONES = {
    "˧˧": "1",   # ngang (level 33) — tone 7 is its clause-final variant
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
    "˩": "6", "˨": "2", "˧": "1", "˦": "3", "˥": "3",  # single-letter residue
}
STRIP = "̟̚"


def fold_token(ph: str) -> list[str]:
    if ph == "~":
        return []
    ph = ph.translate({ord(c): None for c in STRIP}).replace("ï", "i")
    ph = ph.translate(SUPDIG)
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
                if toks[i][0] in TL or toks[i][0] in "⁰¹²³⁴⁵⁶⁷⁸⁹":
                    j = i
                    letters = []
                    digits = []
                    while j < len(toks) and (
                        toks[j][0] in TL or toks[j][0] in "⁰¹²³⁴⁵⁶⁷⁸⁹"
                    ):
                        if toks[j][0] in TL:
                            letters.append(toks[j])
                        else:
                            digits.append(toks[j].translate(SUPDIG))
                        j += 1
                    if letters:
                        tone = TONES.get("".join(letters))
                        if tone is None:  # unknown contour: level tone
                            tone = "1"
                            unmapped_tones += 1
                        out.append(tone)
                    # stray superscript digits are already tone digits;
                    # pass through as ASCII
                    out.extend(digits)
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
