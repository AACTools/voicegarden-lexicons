#!/usr/bin/env python3
"""Merge gruut + WikiPron staging TSVs into one lexicon.txt per language.

Inputs (any may be missing):
  staging/<lang>/gruut.tsv      word\tph1 ph2 ...   (segmented, stress-marked)
  staging/<lang>/wikipron.tsv   word\tpʰ1 pʰ2 ...  (broad phonemic, spaced)

Output: staging/<lang>/merged.tsv

Rules:
- gruut rows win on word conflicts (consistent segmentation + stress is
  what the voices expect); WikiPron fills words gruut lacks.
- --prefer wikipron flips that for languages where gruut is thin.
- Both files normalised to NFC; word keys casefolded for Latin scripts.
"""

from __future__ import annotations

import argparse
import unicodedata
from pathlib import Path


def load(path: Path) -> dict[str, str]:
    rows: dict[str, str] = {}
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        word, _, pron = line.partition("\t")
        word = word.strip()
        pron = unicodedata.normalize("NFC", pron.strip())
        if not word or not pron:
            continue
        w = word.lower() if word.isascii() else unicodedata.normalize("NFC", word)
        rows.setdefault(w, pron)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("lang")
    ap.add_argument("--staging", default="staging")
    ap.add_argument("--prefer", choices=["gruut", "wikipron"], default="gruut")
    args = ap.parse_args()

    d = Path(args.staging) / args.lang
    gruut = load(d / "gruut.tsv")
    wiki = load(d / "wikipron.tsv")
    primary, secondary = (
        (gruut, wiki) if args.prefer == "gruut" else (wiki, gruut)
    )

    merged = dict(primary)
    new = 0
    for w, p in secondary.items():
        if w not in merged:
            merged[w] = p
            new += 1

    out = d / "merged.tsv"
    with out.open("w", encoding="utf-8") as f:
        for w in sorted(merged):
            f.write(f"{w}\t{merged[w]}\n")

    print(
        f"{args.lang}: gruut {len(gruut)} + wikipron {len(wiki)} "
        f"(+{new} new words) -> {len(merged)} in {out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
