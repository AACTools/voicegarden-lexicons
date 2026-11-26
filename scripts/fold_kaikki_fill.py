#!/usr/bin/env python3
"""Fold a kaikki fill through the language's existing fold + a narrow
cleanup, and report agreement against the seed.

kaikki rows for a language carry the same raw Wiktionary conventions
the WikiPron scrape did, so the per-language fold scripts
(scripts/fold_<language>.py) apply as-is — then a final cleanup removes
what the fold leaves behind: narrow-transcription diacritics (lowered
`̞`, raised `̝`, advanced `̟`, mid-centralized `̽`, voiceless rings `̥`)
that broad conventions never carry. Combining marks are stripped except
length `ː`, syllabic `̩` and the affricate tie `͡`; a per-language
EXTRA map handles the few base-letter leftovers.

Rows are seed-disjoint by construction of the merge (the caller unions
them behind the seed); this script only folds and reports.

Usage: scripts/fold_kaikki_fill.py --iso afr \
          [--seed staging/afr/merged.tsv] [--out staging/afr/kaikki.folded.tsv]
"""

from __future__ import annotations

import argparse
import importlib
import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

# iso -> (fold module, extra base-letter map, tokens that drop a row)
FILLS = {
    "afr": ("fold_afrikaans", {"ä": "a", "ɾ": "r", "ɨ": "ə"}, {"~"}),
    "nob": ("fold_norwegian", {}, set()),
}
KEEP_MARKS = {"\u02d0", "\u0329", "\u0361"}  # ː length, ̩ syllabic, ͡ tie


def strip_narrow(token: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFC", token)
                   if unicodedata.category(c)[0] != "M" or c in KEEP_MARKS)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--iso", required=True, choices=sorted(FILLS))
    ap.add_argument("--seed", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    module_name, extra, drop = FILLS[args.iso]
    fold = importlib.import_module(module_name).fold

    src = REPO / f"staging/{args.iso}/kaikki.tsv"
    seed_path = args.seed or REPO / f"staging/{args.iso}/merged.tsv"
    out = args.out or REPO / f"staging/{args.iso}/kaikki.folded.tsv"

    seed: dict[str, str] = {}
    if seed_path.exists():
        for line in seed_path.read_text(encoding="utf-8").splitlines():
            w, _, p = line.partition("\t")
            if p:
                seed[w] = p.strip()

    kept: dict[str, str] = {}
    dropped = 0
    for line in src.read_text(encoding="utf-8").splitlines():
        word, _, pron = line.partition("\t")
        word = word.strip()
        if not word or not pron.strip() or " " in word:
            dropped += 1
            continue
        toks = []
        for t in fold(pron.strip()).split():
            for a, b in extra.items():
                t = t.replace(a, b)
            t = strip_narrow(t)
            if t and t not in drop:
                toks.append(t)
        if not toks:
            dropped += 1
            continue
        kept[word] = " ".join(toks)

    shared = set(seed) & set(kept)
    agree = sum(1 for w in shared if seed[w] == kept[w])
    new = set(kept) - set(seed)
    out.write_text("".join(f"{w}\t{p}\n" for w, p in sorted(kept.items())),
                   encoding="utf-8")
    print(f"{args.iso}: {len(kept):,} folded rows ({dropped} dropped); "
          f"shared with seed {len(shared):,} (agree {agree / max(len(shared), 1):.1%}); "
          f"new {len(new):,}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
