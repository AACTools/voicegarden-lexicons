#!/usr/bin/env python3
"""Fold kaikki Georgian IPA to the broad conventions and write staging.

kaikki/Wiktionary Georgian IPA varies by transcriber: fronted vowels
(ä e̞ o̞), devoiced-stop spellings (b̥ d̥ ɡ̊), tap r (ɾ), uvular ʁ,
labialized series (bʷ ɡʷ …), ejectives split into base + modifier
letter apostrophe (t ʼ), dental diacritics (d̪), and stray Mtavruli
characters. The SIGMORPHON 2020 G2P geo data (same upstream Wiktionary,
human-normalized) uses the clean broad set: ɑ ɛ ɔ i u r b d ɡ ɣ l
tʼ kʼ pʼ sʼ ʃʼ qʼ … — this script folds kaikki to that set.

SIGMORPHON itself is NOT ingested (its repo carries no explicit
license; kaikki alone is CC BY-SA via Wiktionary) — it is used as the
convention reference and validation only.

Usage: scripts/fold_georgian.py  (reads staging/kat/kaikki.tsv,
       writes staging/kat/kaikki.folded.tsv)
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "staging/kat/kaikki.tsv"
DST = REPO / "staging/kat/kaikki.folded.tsv"

# vowel symbol fold (kaikki -> broad)
VOWELS = {"ä": "ɑ", "e̞": "ɛ", "o̞": "ɔ", "ɘ": "ɑ", "oː": "ɔ", "o": "ɔ",
          "a": "ɑ", "e": "ɛ"}
# consonant symbol fold
CONS = {"ɾ": "r", "d̥": "d", "b̥": "b", "ɡ̊": "ɡ", "ʁ": "ɣ", "ɫ": "l",
        "d̪": "d", "t̪": "t", "n̪": "n", "χ": "x"}
# strip labialization (lost in the modern standard)
DELAB = re.compile("ʷ")
# ejectives: the piper ka voices' espeak-derived token inventories do
# not distinguish glottalized stops (no ʼ in natia tokens.txt at all),
# so the compatible fold merges them into the plain series
DEGLOTT = re.compile("ʼ")


def fold(pron: str) -> list[str] | None:
    phones = pron.split()
    out: list[str] = []
    for ph in phones:
        ph = DEGLOTT.sub("", DELAB.sub("", ph))
        if ph == "ʼ":
            # stray ejective marker with no host: drop
            continue
        ph = VOWELS.get(ph) or CONS.get(ph) or ph
        out.append(ph)
    return out if out else None


def main() -> int:
    dropped = Counter()
    n = kept = 0
    with DST.open("w", encoding="utf-8") as dst:
        for line in SRC.open(encoding="utf-8"):
            word, _, pron = line.partition("\t")
            n += 1
            folded = fold(pron.strip())
            if folded is None or any(ord(c) > 0x2D00 for c in word):
                dropped["unfolds"] += 1
                continue
            bad = [p for p in folded
                   if len(p) > 2 and "\u0361" not in p and p[-1:] != "ʼ"]
            if bad:
                # report anything exotic we did not fold away
                dropped.update(bad)
                continue
            dst.write(f"{word}\t{' '.join(folded)}\n")
            kept += 1
    print(f"folded {kept}/{n} entries -> {DST}")
    if dropped:
        print("dropped/unfolded:", dropped.most_common(15))
    return 0


if __name__ == "__main__":
    sys.exit(main())
