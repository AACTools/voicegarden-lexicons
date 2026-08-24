#!/usr/bin/env python3
"""Build the multilingual G2P + P2G training corpus from staging/.

Reads every staging/<lang>/merged.tsv, filters junk rows, splits
word-alphabetically (not randomly — near-duplicate spellings must not
leak across splits), and writes:

  corpus/g2p.tsv      <lang>: word -> IPA          (train/val/test)
  corpus/p2g.tsv      <lang>: IPA -> word          (train/val/test)
  corpus/meta.json    counts, vocab stats, splits

Row format (one example per line, tab-separated):
  g2p:  <lang>\tword\tIPA
  p2g:  <lang>\tIPA\tword

The <lang> tag is prepended to the input text at training time
(PolyIPA convention: "<eng>: hello"); this script keeps the columns raw
so the tag format can evolve without a rebuild.

Quality filters:
  - drop rows with control chars, tabs/newlines in fields, empty fields
  - drop words > 40 chars or pronunciations > 60 phoneme tokens
  - drop languages with < 200 usable rows (too small to help)
  - deterministic: same staging -> same corpus (sorted languages/words)
"""

from __future__ import annotations

import argparse
import json
import random
import unicodedata
from collections import Counter
from pathlib import Path

MAX_WORD_CHARS = 40
MAX_PHONE_TOKENS = 60
MIN_LANG_ROWS = 200
VAL_FRAC = 0.01
TEST_FRAC = 0.01
SEED = 7


def clean_word(w: str) -> str | None:
    if not w or len(w) > MAX_WORD_CHARS:
        return None
    for c in w:
        if unicodedata.category(c).startswith("C") or c in "\t\n\r":
            return None
    return w


def clean_pron(p: str) -> str | None:
    if not p:
        return None
    toks = p.split()
    if not toks or len(toks) > MAX_PHONE_TOKENS:
        return None
    for t in toks:
        if any(unicodedata.category(c).startswith("C") for c in t):
            return None
    return " ".join(toks)


def split_words(rows: list[tuple[str, str]]) -> dict[str, list[tuple[str, str]]]:
    """Alphabetical split: sort by word, take even slices. Near-duplicate
    spellings (cat/cats) stay in the same split — random splits leak."""
    rows = sorted(rows)
    n = len(rows)
    n_val = max(1, int(n * VAL_FRAC))
    n_test = max(1, int(n * TEST_FRAC))
    return {
        "test": rows[:n_test],
        "val": rows[n_test : n_test + n_val],
        "train": rows[n_test + n_val :],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--staging", default="staging")
    ap.add_argument("--out", default="corpus")
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args()

    random.seed(args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    langs: dict[str, list[tuple[str, str]]] = {}
    skipped = 0
    for d in sorted(Path(args.staging).iterdir()):
        merged = d / "merged.tsv"
        if not merged.exists():
            continue
        rows: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for line in merged.read_text(encoding="utf-8").splitlines():
            word, _, pron = line.partition("\t")
            w, p = clean_word(word), clean_pron(pron)
            if not w or not p or (w, p) in seen:
                skipped += 1
                continue
            seen.add((w, p))
            rows.append((w, p))
        if len(rows) >= MIN_LANG_ROWS:
            langs[d.name] = rows

    meta = {
        "seed": args.seed,
        "skipped_rows": skipped,
        "languages": len(langs),
        "entries": sum(len(r) for r in langs.values()),
        "per_language": {k: len(v) for k, v in sorted(langs.items())},
        "splits": {},
    }

    files = {
        (task, split): (out / f"{task}.{split}.tsv").open("w", encoding="utf-8")
        for task in ("g2p", "p2g")
        for split in ("train", "val", "test")
    }
    try:
        for lang, rows in langs.items():
            for split, srows in split_words(rows).items():
                meta["splits"].setdefault(split, 0)
                meta["splits"][split] += len(srows)
                for w, p in srows:
                    files[("g2p", split)].write(f"{lang}\t{w}\t{p}\n")
                    files[("p2g", split)].write(f"{lang}\t{p}\t{w}\n")
    finally:
        for f in files.values():
            f.close()

    # vocab stats (for the model card / sanity)
    phone_vocab = Counter()
    for rows in langs.values():
        for _, p in rows:
            phone_vocab.update(p.split())
    meta["phone_symbols"] = len(phone_vocab)
    meta["top_phones"] = phone_vocab.most_common(20)

    (out / "meta.json").write_text(json.dumps(meta, indent=1, sort_keys=True))
    print(
        f"{meta['languages']} languages, {meta['entries']:,} entries "
        f"({meta['skipped_rows']:,} skipped) -> {out}/ "
        f"splits {meta['splits']}, {meta['phone_symbols']} phone symbols"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
