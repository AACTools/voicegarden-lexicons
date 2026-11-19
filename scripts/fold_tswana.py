#!/usr/bin/env python3
"""Fold VoxCommunis cvu Tswana phones to the mimic3-tn voice inventory.

The cvu alignment dictionary writes Tswana with an aspiration series
(ɬʰ sʰ tʰ χʰ pʰ kʰ ʃʰ), lax vowels (ɪ, and ɪ inside falling diphthongs
aɪ ʊɪ …), and ʒ — none of which the mimic3-tn_ZA-google-nwu voice's
espeak-derived inventory distinguishes (46 tokens, no aspiration marks,
no ɪ, no ʒ). The fold:

- aspiration marks stripped (the voice merges aspirated/ejective/
  tenuis — same class of merge as fold_korean.py's laryngeal collapse);
- ɪ → i everywhere (also repairs the diphthongs: aɪ → ai, ʊɪ → ʊi …);
- ʒ → ʃ (the inventory lacks the voiced fricative).

Usage: scripts/fold_tswana.py  (staging/tsn/voxcommunis.tsv ->
       staging/tsn/voxcommunis.folded.tsv)
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "staging/tsn/voxcommunis.tsv"
DST = REPO / "staging/tsn/voxcommunis.folded.tsv"


def fold_token(ph: str) -> str:
    ph = ph.replace("ʰ", "")
    ph = ph.replace("ʒ", "ʃ")
    ph = ph.replace("ɪ", "i")
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
