#!/usr/bin/env python3
"""Variant builder: strip/normalise IPA stress marks from a lexicon TSV.

gruut marks stress as a prefix char on the stressed vowel ("k ˈæ t").
Stress multiplies the phoneme inventory and hurts WFST generalisation;
this tool emits a stressless variant for training experiments (the TTS
side loses stress placement — for piper-family voices that is usually
fine, their models rarely use stress).

Usage:
  scripts/strip_stress.py IN.tsv OUT.tsv        # remove ˈ and ˌ
  scripts/strip_stress.py IN.tsv OUT.tsv --keep # keep as separate symbols
"""

from __future__ import annotations

import argparse
import sys

STRESS = {"\u02c8": "", "\u02cc": ""}  # ˈ ˌ


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--keep", action="store_true",
                    help="keep stress as standalone phonemes instead of stripping")
    args = ap.parse_args()

    kept = stripped = rows = 0
    with open(args.src, encoding="utf-8") as f, \
         open(args.dst, "w", encoding="utf-8") as out:
        for line in f:
            word, _, pron = line.rstrip("\n").partition("\t")
            if not pron:
                continue
            rows += 1
            if "\u02c8" in pron or "\u02cc" in pron:
                if args.keep:
                    parts = []
                    for sym in pron.split():
                        if sym[0] in STRESS and len(sym) > 1:
                            parts.extend((sym[0], sym[1:]))
                        else:
                            parts.append(sym)
                    pron = " ".join(parts)
                    kept += 1
                else:
                    pron = "".join(STRESS.get(c, c) for c in pron)
                    pron = " ".join(pron.split())
                    stripped += 1
            out.write(f"{word}\t{pron}\n")
    print(f"{rows} rows: {stripped} stress-stripped, {kept} stress-split, {rows - stripped - kept} untouched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
