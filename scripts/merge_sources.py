#!/usr/bin/env python3
"""Merge gruut + WikiPron staging TSVs into one lexicon.txt per language.

Inputs (any may be missing):
  staging/<lang>/gruut.tsv      word\tph1 ph2 ...   (segmented, stress-marked)
  staging/<lang>/wikipron.tsv   word\tpʰ1 pʰ2 ...  (broad phonemic, spaced)

Output: staging/<lang>/merged.tsv

Rules:
- gruut rows win on word conflicts (consistent segmentation + stress is
  what the voices expect).
- --strategy union: WikiPron fills words gruut lacks. WARNING: the two
  sources use conflicting IPA conventions (stress marks, diacritics);
  union is only safe once a normaliser exists — measured on German it
  dropped P2G exact from 50% (gruut-only) to 16% (union).
- --strategy gruut-only (default when gruut exists): keep gruut alone.
- --strategy wikipron-only: keep wikipron alone (for comparison rows).
- --strategy variants: merged.tsv follows the auto rule (bigger source
  wins), and a variants.tsv sidecar records every non-identical row of
  the OTHER source (real dialect variants + convention-clashed
  duplicates + words the primary lacks) so the variant-preserving
  lexicon and ranked-candidates API can use them without poisoning
  the primary training data.
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
    ap.add_argument("--strategy", choices=["auto", "union", "gruut-only",
                    "wikipron-only", "variants"], default="auto",
                    help="auto = gruut-only when gruut exists, else wikipron-only")
    args = ap.parse_args()

    d = Path(args.staging) / args.lang
    gruut = load(d / "gruut.tsv")
    wiki = load(d / "wikipron.tsv")

    strategy = args.strategy
    if strategy == "auto":
        strategy = "gruut-only" if len(gruut) >= len(wiki) else "wikipron-only"

    if strategy == "variants":
        # primary follows the auto rule (bigger source keeps merged.tsv);
        # the sidecar preserves the OTHER source's non-identical rows.
        primary_is_gruut = len(gruut) >= len(wiki)
        if primary_is_gruut:
            source, source_name = gruut, "gruut"
            other_name, other = "wikipron", wiki
        else:
            source, source_name = wiki, "wikipron"
            other_name, other = "gruut", gruut
        new = 0
        n_var = n_conflict = n_oov = 0
        src_cf = {k.casefold(): v for k, v in source.items()}
        with (d / "variants.tsv").open("w", encoding="utf-8") as vf:
            for w in sorted(other):
                cf = w.casefold()
                if cf in src_cf:
                    if other[w] != src_cf[cf]:
                        vf.write(f"{w}\t{other[w]}\n")
                        n_conflict += 1
                else:
                    vf.write(f"{w}\t{other[w]}\n")
                    n_oov += 1
                n_var = n_conflict + n_oov
        strategy_note = (f"primary {source_name}; variants {n_var} "
                         f"({n_conflict} clashes, {n_oov} primary-OOV) "
                         f"from {other_name}")
    elif strategy == "gruut-only":
        source, source_name = gruut, "gruut"
        new = 0
    elif strategy == "wikipron-only":
        source, source_name = wiki, "wikipron"
        new = 0
    else:
        source = dict(gruut)
        source_name = "union(gruut+wikipron)"
        new = 0
        for w, p in wiki.items():
            if w not in source:
                source[w] = p
                new += 1

    merged = source

    out = d / "merged.tsv"
    with out.open("w", encoding="utf-8") as f:
        for w in sorted(merged):
            f.write(f"{w}\t{merged[w]}\n")

    extra = f"; {strategy_note}" if strategy == "variants" else ""
    print(
        f"{args.lang}: gruut {len(gruut)} + wikipron {len(wiki)} "
        f"[{strategy}, +{new} new] -> {len(merged)} in {out}{extra}"
    )
    note = strategy_note if strategy == "variants" else strategy
    (d / "merge-strategy.txt").write_text(note + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
