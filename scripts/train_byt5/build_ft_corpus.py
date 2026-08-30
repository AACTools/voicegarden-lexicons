#!/usr/bin/env python3
"""Build the English fine-tune corpus (corpus-ft/).

For retraining the published ByT5 models on English: eng-US + eng-UK
staging dictionaries, CMUDict converted to IPA (via floravox-g2p's
cmu2tsv example — only ~2k words are genuinely new; gruut already
absorbed the rest), and a replay sample from the existing corpus so
the other languages are not forgotten.

Word-alphabetical holdout split (near-duplicate spellings must not
leak across splits), same rule as build_corpus.py.

Usage:
  python3 build_ft_corpus.py --cmu cmu.tsv --replay 300000 --out corpus-ft
"""
from __future__ import annotations

import argparse
import random
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def read(p: Path, default_tag: str) -> list[tuple[str, str, str]]:
    rows = []
    for line in p.open(encoding="utf-8"):
        parts = line.rstrip("\n").split("\t")
        if len(parts) == 2:
            rows.append((default_tag, parts[0], parts[1]))
        elif len(parts) == 3:
            rows.append((parts[0], parts[1], parts[2]))
    return rows


def alpha_split(rows: list, frac: float = 0.02):
    rows = sorted(set(rows), key=lambda r: (r[1], r[2]))
    cut = int(len(rows) * (1 - frac))
    return rows[:cut], rows[cut:]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cmu", required=True, help="cmu.tsv from cmu2tsv")
    ap.add_argument("--replay", type=int, default=300_000)
    ap.add_argument("--out", default="corpus-ft")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    random.seed(args.seed)
    out = Path(args.out)
    out.mkdir(exist_ok=True)

    eng = read(REPO / "staging/eng-US/merged.tsv", "eng-US")
    eng_uk = read(REPO / "staging/eng-UK/merged.tsv", "eng-UK")
    cmu = [("eng-US", w, p) for w, p in
           (l.rstrip("\n").split("\t") for l in open(args.cmu, encoding="utf-8"))]

    seen: dict = {}
    for r in eng + eng_uk:
        seen[(r[0], r[1].lower())] = r
    cmu_new = [r for r in cmu
               if (r[0], r[1].lower()) not in seen
               and seen.setdefault((r[0], r[1].lower()), r) is r]

    pool = []
    for line in (REPO / "corpus/g2p.train.tsv").open(encoding="utf-8"):
        parts = line.rstrip("\n").split("\t")
        if len(parts) == 3 and not parts[0].startswith("eng"):
            pool.append(tuple(parts))
    random.shuffle(pool)
    replay = pool[: args.replay]

    eng_tr, eng_te = alpha_split(eng)
    uk_tr, uk_te = alpha_split(eng_uk)
    cmu_tr, cmu_te = alpha_split(cmu_new)

    train = eng_tr + uk_tr + cmu_tr + replay
    test = eng_te + uk_te + cmu_te
    random.shuffle(train)
    random.shuffle(test)

    def write(name: str, rows, invert: bool):
        with (out / name).open("w", encoding="utf-8") as f:
            for t, a, b in rows:
                f.write(f"{t}\t{b}\t{a}\n" if invert else f"{t}\t{a}\t{b}\n")

    write("g2p.train.tsv", train, False)
    write("g2p.val.tsv", test[:2000], False)
    write("g2p.test.tsv", test[2000:], False)
    write("p2g.train.tsv", train, True)
    write("p2g.val.tsv", test[:2000], True)
    write("p2g.test.tsv", test[2000:], True)
    print(f"train {len(train):,} (eng-US {len(eng_tr):,}, eng-UK {len(uk_tr):,}, "
          f"cmudict-new {len(cmu_tr):,}, replay {len(replay):,}); "
          f"eng holdout {len(test) - 2000:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
