#!/usr/bin/env python3
"""Fold Korean narrow IPA (WikiPron/kaikki) to the ko voices' conventions.

WikiPron and kaikki Korean are narrow transcriptions: lowered vowels
(a̠ e̞ o̞), tense vowels (ʌ̹), aspirated consonants (pʰ tʰ kʰ sʰ),
fortis series (k͈ t͈ p͈ s͈), unreleased finals (k̚), and palatal/velar
fricative variants (ç x ʝ ɣ). The ko voice family (mimic3-ko_KO-kss)
was trained on espeak-ng Korean, whose token inventory distinguishes
none of the laryngeal contrasts: plain consonants only, plus ʲ and ː.

Fold (validated against kss tokens.txt): laryngeal series merged to
plain (pʰ=k͈=p̚→p, …), narrow vowels to the espeak set
(a̠→ɐ, ʌ̹→ʌ, o̞→o, e̞→e, ɘː→əː), h-variants (ɦ ç x)→h, ɲ→n ʲ,
ʎ→l ʲ, ɭ→l, lenition variants (β ɸ ɣ)→b p ɡ, glides ɥ ɰ→w, ~ dropped.
Affricates (t͡ɕ …) keep their tie bars — the runtime ladder char-splits
them (t ɕ are both in vocab).

Usage: scripts/fold_korean.py  (staging/kor/kaikki.tsv ->
       staging/kor/kaikki.folded.tsv)
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "staging/kor/kaikki.tsv"
DST = REPO / "staging/kor/kaikki.folded.tsv"

MAP = {
    # vowels
    "a̠": "ɐ", "a̠ː": "ɐː", "ʌ̹": "ʌ", "ʌ̹ː": "ʌː", "o̞": "o",
    "o̞ː": "oː", "ɔ": "o", "e̞": "e", "e̞ː": "eː", "ɘː": "əː",
    "ɤ": "ʌ", "ɰ": "w", "ɥ": "w",
    # h-variants
    "ɦ": "h", "ç": "h", "x": "h",
    # laterals and nasals
    "ɭ": "l", "ʎ": "lʲ", "ɲ": "nʲ",
    # lenition variants
    "β": "b", "ɸ": "p", "ɸʷ": "p", "ɣ": "ɡ", "c": "k", "ʝ": "j",
    # unreleased finals
    "k̚": "k", "t̚": "t", "p̚": "p",
}
# laryngeal diacritics merged to plain: aspiration ʰ, fortis ◌͈
STRIP = ("ʰ", "͈")


def fold_token(ph: str) -> list[str]:
    if ph == "~":
        return []
    mapped = MAP.get(ph)
    if mapped:
        return mapped.split()
    for mark in STRIP:
        ph = ph.replace(mark, "")
    ph = ph.replace("ʷ", "")
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
