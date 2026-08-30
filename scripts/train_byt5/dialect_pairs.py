#!/usr/bin/env python3
"""Learn a US<->UK phoneme mapping from Wiktionary dialect pairs, then
audit our own eng-US vs eng-UK varieties through it.

Inputs (produced by the kaikki extraction + floravox-g2p ipa_seg):
  word\tUK\ttok tok ...\tUS\ttok tok ...   -- or a split seg file:
  word\tCLASS\ttok tok ...

Steps:
  1. token-level DP alignment of each UK/US pair
  2. correspondence counts -> per-US-token most-likely UK form
  3. post-conversion exact-match rate (the harmonization gate)
  4. apply the same learned map to staging/eng-US vs staging/eng-UK
     shared words: agreement before and after conversion

Usage:
  python3 dialect_pairs.py --pairs ukus-seg.tsv \
      --staging-us staging/eng-US/merged.tsv --staging-uk staging/eng-UK/merged.tsv
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def align(a: list[str], b: list[str]) -> list[tuple[str, str]]:
    """DP alignment; returns (a_tok or '', b_tok or '') operations."""
    n, m = len(a), len(b)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        d[i][0] = i
    for j in range(1, m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i][j] = min(
                d[i - 1][j] + 1,
                d[i][j - 1] + 1,
                d[i - 1][j - 1] + (a[i - 1] != b[j - 1]),
            )
    ops = []
    i, j = n, m
    while i or j:
        if i and j and d[i][j] == d[i - 1][j - 1] + (a[i - 1] != b[j - 1]):
            ops.append((a[i - 1], b[j - 1]))
            i, j = i - 1, j - 1
        elif i and d[i][j] == d[i - 1][j] + 1:
            ops.append((a[i - 1], ""))
            i -= 1
        else:
            ops.append(("", b[j - 1]))
            j -= 1
    ops.reverse()
    return ops


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", required=True, help="segmented pairs file")
    ap.add_argument("--staging-us", default="staging/eng-US/merged.tsv")
    ap.add_argument("--staging-uk", default="staging/eng-UK/merged.tsv")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--out", default="audit/us-uk-mapping.json")
    args = ap.parse_args()

    # group per word
    pron = defaultdict(dict)
    for line in open(args.pairs, encoding="utf-8"):
        parts = line.rstrip("\n").split("\t")
        if len(parts) == 3 and parts[0] and parts[2] and parts[1] not in pron[parts[0]]:
            pron[parts[0]][parts[1]] = parts[2].split()
    pairs = [(v["UK"], v["US"]) for v in pron.values() if "UK" in v and "US" in v]
    print(f"paired words: {len(pairs):,}")

    # 1+2: align and count
    corr = Counter()
    for uk, us in pairs:
        for a, b in align(uk, us):
            corr[(b, a)] += 1  # (US, UK)
    total_ops = sum(corr.values())
    print(f"aligned operations: {total_ops:,}")

    mapping = {}
    us_tokens = {u for (u, _) in corr}
    for u in us_tokens:
        best, n = corr.most_common()[0][0], 0
        cands = [(k, c) for (us_t, k), c in corr.items() if us_t == u]
        (k, n) = max(cands, key=lambda x: x[1])
        mapping[u] = k

    # 3: post-conversion exact match
    def convert(us: list[str]) -> list[str]:
        return [t for t in (mapping.get(x, x) for x in us) if t]

    hit = sum(convert(us) == uk for uk, us in pairs)
    print(f"post-conversion exact match: {hit/len(pairs):.1%} "
          f"(baseline identity: {sum(u == k for k, u in pairs)/len(pairs):.1%})")

    # top correspondences with the counts
    top = []
    for (u, k), c in corr.most_common(args.top * 3):
        share = c / max(sum(v for (uu, _), v in corr.items() if uu == u), 1)
        top.append({"us": u, "uk": k, "count": c, "purity": round(share, 3)})
    print(f"\ntop {args.top} correspondences (US -> UK):")
    for t in top[: args.top]:
        print(f"  {t['us'] or 'Ø':6} -> {t['uk'] or 'Ø':6} {t['count']:7,}  ({t['purity']:.0%})")

    # 4: audit our own staging varieties through the learned map
    def load(p):
        d = {}
        for line in open(p, encoding="utf-8"):
            parts = line.rstrip("\n").split("\t")
            if len(parts) == 2:
                d.setdefault(parts[0].lower(), parts[1].split())
        return d

    if (REPO / args.staging_us).exists() and (REPO / args.staging_uk).exists():
        us_d, uk_d = load(REPO / args.staging_us), load(REPO / args.staging_uk)
        shared = sorted(set(us_d) & set(uk_d))
        raw = sum(us_d[w] == uk_d[w] for w in shared)
        conv = sum(convert(us_d[w]) == uk_d[w] for w in shared)
        print(f"\nstaging eng-US vs eng-UK ({len(shared):,} shared words):")
        print(f"  identical before conversion: {raw/len(shared):.1%}")
        print(f"  identical after conversion:  {conv/len(shared):.1%}")

    Path(args.out).parent.mkdir(exist_ok=True)
    json.dump({"pairs": len(pairs), "mapping": mapping, "top": top},
              open(args.out, "w"), ensure_ascii=False, indent=1)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
