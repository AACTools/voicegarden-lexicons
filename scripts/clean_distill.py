#!/usr/bin/env python3
"""Clean convention artifacts from the v2 distillation data.

The ByT5-distilled rows (distill-v2/*.tsv) were generated from the
pre-fold merged corpora, so they still carry the marks the voice folds
strip: the Finnish juncture ˣ and the Scandinavian pitch-accent tone
digits (¹ ²). These files feed build_expanded_v2.sh/py directly —
the published fin/swe/nob expanded bundles inherited the artifacts
(caught by the round-2 review: fin 9,029 rows).

Rules (pronunciation column only — accented HEADWORDS are fine):
  all files:   standalone ¹ ² ³ tokens dropped
  fin:         ˣ stripped wherever it occurs (juncture mark, not a phone)

Idempotent; re-run after any re-distillation until the distillation
corpus is rebuilt from folded sources (ByT5 v3 — see
docs/data-sources.md).

Usage: scripts/clean_distill.py [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DISTILL = REPO / "distill-v2"

TONE_TOKENS = {"¹", "²", "³"}


def clean(pron: str, strip_juncture: bool) -> str:
    out = []
    for ph in pron.split():
        if ph in TONE_TOKENS:
            continue
        # tone digits also attach to the initial consonant (swe: ²s ²f …)
        ph = ph.translate({ord(c): None for c in TONE_TOKENS})
        if strip_juncture:
            ph = ph.replace("ˣ", "")
        if ph:
            out.append(ph)
    return " ".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    total_cleaned = 0
    for f in sorted(DISTILL.glob("*.tsv")):
        juncture = f.name.startswith(("fin", "swe", "nob"))
        cleaned = n = 0
        rows = []
        for line in f.open(encoding="utf-8"):
            word, _, pron = line.partition("\t")
            n += 1
            folded = clean(pron, strip_juncture=juncture or "ˣ" in pron)
            if folded != pron.strip():
                cleaned += 1
            rows.append((word, folded))
        if cleaned and not args.dry_run:
            tmp = f.with_suffix(".tsv.tmp")
            with tmp.open("w", encoding="utf-8") as out:
                for w, p in rows:
                    if p:
                        out.write(f"{w}\t{p}\n")
            tmp.replace(f)
        total_cleaned += cleaned
        if cleaned:
            print(f"{f.name}: cleaned {cleaned}/{n} rows"
                  f"{' (dry-run)' if args.dry_run else ''}")
    print(f"total: {total_cleaned} rows cleaned")
    return 0


if __name__ == "__main__":
    sys.exit(main())
