#!/usr/bin/env python3
"""Fold Nepali kaikki IPA to the piper ne voice's conventions.

kaikki/Wiktionary Nepali uses breathy-voiced IPA (ɡ ʱ as separate
tokens, ʌ̤ ä̤), the fronted ä for the long open vowel, and dental /
unreleased / laminal diacritics. The ne voices' espeak-derived token
inventories ship ʰ and ̃ as STANDALONE tokens (verified against
ne_NP-google-medium tokens.txt: ʰ ∈ vocab, ̃ ∈ vocab) — while espeak's
internal --pho notation writes g#/breathing its own way, the model
consumes the IPA decomposition.

Fold: standalone ʱ and trailing ʰ → a separate ʰ token after the
consonant; nasalized vowels → vowel + ̃; breathy-voice diacritic on
vowels stripped (the consonant aspiration carries the lexical
contrast); ä → aː; dental/unreleased/advanced/laminal diacritics and
glide breves stripped; link marks dropped.

Usage: scripts/fold_nepali.py  (staging/nep/kaikki.tsv ->
       staging/nep/kaikki.folded.tsv)
"""
from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "staging/nep/kaikki.tsv"
DST = REPO / "staging/nep/kaikki.folded.tsv"

STRIP = "̞̤̪̠̯͈̣̻̚"


def fold_token(ph: str) -> list[str]:
    if ph == "‿":
        return []
    ph = ph.translate({ord(c): None for c in STRIP})
    ph = ph.replace("ä", "aː").replace("ṳ", "u")
    if ph == "ʱ":
        return ["ʰ"]  # the model's inventory ships ʰ standalone
    # nasalized vowels: vowel + standalone combining tilde (both in the
    # model's phoneme_id_map)
    nfd = unicodedata.normalize("NFD", ph)
    if "̃" in nfd:
        base = nfd.replace("̃", "")
        return [unicodedata.normalize("NFC", base), "̃"]
    if ph.endswith("ʰ"):
        return [ph[:-1], "ʰ"]
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
