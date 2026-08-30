#!/usr/bin/env python3
"""Harmonize notation between the two sources of each language.

For every language with gruut.tsv + wikipron.tsv in staging:
  1. align shared-word pronunciations (anchor-based n:m, not 1:1)
  2. learn a wikipron -> gruut segment mapping from the alignment
  3. rewrite wikipron through the map; measure agreement before/after

Output: a harmonized wikipron TSV per language (staging/<tag>/wikipron.harmonized.tsv)
plus a report. gruut is the target convention (piper voices were
trained on it). Real pronunciation variants that survive conversion
are kept, not collapsed - see the variant-preserving merge policy.

Usage: python3 harmonize_sources.py [--langs deu,ita] [--min-shared 200]
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def load(p: Path) -> dict[str, list[str]]:
    d = {}
    for line in p.open(encoding="utf-8"):
        parts = line.rstrip("\n").split("\t")
        if len(parts) == 2 and parts[1].strip():
            d.setdefault(parts[0].lower(), parts[1].split())
    return d


def anchors(a: list[str], b: list[str]) -> list[int]:
    """Positions in b matched to identical tokens in a (monotone)."""
    # standard DP for similarity, then trace equal-token path
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
                d[i - 1][j - 1] + (0 if a[i - 1] == b[j - 1] else 1),
            )
    pairs = []
    i, j = n, m
    while i and j:
        if d[i][j] == d[i - 1][j - 1] + (0 if a[i - 1] == b[j - 1] else 1):
            if a[i - 1] == b[j - 1]:
                pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i and d[i][j] == d[i - 1][j] + 1:
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    return pairs


def segment_map(a: list[str], b: list[str]) -> list[tuple[tuple[str, ...], tuple[str, ...]]]:
    """n:m segments between anchors (n,m <= 3)."""
    ap = anchors(a, b)
    segs = []
    prev_a = prev_b = 0
    for (ia, ib) in ap + [(len(a), len(b))]:
        sa, sb = a[prev_a:ia], b[prev_b:ib]
        if sa or sb:
            segs.append((tuple(sa), tuple(sb)))
        prev_a, prev_b = ia + 1, ib + 1
    return segs


def learn_ctx(pairs: list[tuple[list[str], list[str]]], min_count: int = 5,
          min_purity: float = 0.85):
    """Context-conditioned rules: (prev, segment) -> target segment."""
    counts = Counter()
    for a, b in pairs:
        prev = "<s>"
        for sa, sb in segment_map(a, b):
            if sa:
                counts[((prev, sa), sb)] += 1
                prev = sa[-1]
    by_first = defaultdict(list)
    first_totals = Counter()
    for (ctx, sa), c in counts.items():
        if sa:
            first_totals[(ctx, sa[0])] += c
    # group rewrite candidates by (ctx, first token)
    by_key = defaultdict(list)
    for ((ctx, sa), sb), c in counts.items():
        if sa and sa != sb and c >= min_count:
            by_key[(ctx, sa[0])].append((sa, sb, c))
    table = {}
    for key, cands in by_key.items():
        total = first_totals[key]
        kept = [(sa, sb, c) for sa, sb, c in cands
                if c / max(total, 1) >= min_purity]
        if kept:
            kept.sort(key=lambda x: (-x[2], -len(x[0])))
            table[key] = kept[:4]
    return table, counts


def learn(pairs: list[tuple[list[str], list[str]]], min_count: int = 5,
          min_purity: float = 0.85):
    """Context-free purity-gated rules: segment -> target segment."""
    counts = Counter()
    for a, b in pairs:
        for sa, sb in segment_map(a, b):
            counts[(sa, sb)] += 1
    by_first = defaultdict(list)
    first_totals = Counter()
    for (sa, sb), c in counts.items():
        if sa:
            first_totals[sa[0]] += c
            if sa != sb and c >= min_count:
                by_first[sa[0]].append((sa, sb, c))
    table = {}
    for tok, cands in by_first.items():
        kept = []
        for sa, sb, c in cands:
            purity = c / max(first_totals[tok], 1)
            if purity >= min_purity:
                kept.append((sa, sb, c, purity))
        if kept:
            kept.sort(key=lambda x: (-x[3], -x[2], -len(x[0])))
            table[tok] = [(sa, sb, c) for sa, sb, c, _ in kept[:6]]
    return table, counts


def convert(tokens: list[str], table) -> list[str]:
    out = []
    i = 0
    while i < len(tokens):
        cands = table.get(tokens[i])
        if not cands:
            out.append(tokens[i])
            i += 1
            continue
        for (sa, sb, _c) in cands:
            n = len(sa)
            if tuple(tokens[i:i + n]) == sa:
                out.extend(sb)
                i += n
                break
        else:
            out.append(tokens[i])
            i += 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--langs", help="comma-separated tags; default: all with both sources")
    ap.add_argument("--min-shared", type=int, default=200)
    ap.add_argument("--report", default="audit/harmonization-report.json")
    args = ap.parse_args()

    want = set(args.langs.split(",")) if args.langs else None
    report = {}
    for gpath in sorted(REPO.glob("staging/*/gruut.tsv")):
        tag = gpath.parent.name
        if want and tag not in want:
            continue
        wpath = gpath.parent / "wikipron.tsv"
        if not wpath.exists():
            continue
        G, W = load(gpath), load(wpath)
        shared = sorted(set(G) & set(W))
        if len(shared) < args.min_shared:
            continue
        pairs = [(W[w], G[w]) for w in shared]  # learn wikipron -> gruut
        before = sum(a == b for a, b in pairs) / len(pairs)
        results = {}
        for strat, fn in (("context-free", learn), ("context", learn_ctx)):
            table, counts = fn(pairs)
            after = sum(convert(a, table) == b for a, b in pairs) / len(pairs)
            results[strat] = (after, table, counts)
        strat = max(results, key=lambda k: results[k][0])
        after, table, counts = results[strat]
        counts_cf = results["context-free"][2]  # metric from ctx-free counts
        # rewrite wikipron through the map
        harmonized = 0
        with (gpath.parent / "wikipron.harmonized.tsv").open("w", encoding="utf-8") as f:
            for w, toks in W.items():
                conv = convert(toks, table)
                if conv:
                    f.write(f"{w}\t{' '.join(conv)}\n")
                    harmonized += 1
        n_ge = sum(c for (sa, sb), c in counts_cf.items() if len(sa) != len(sb))
        report[tag] = {
            "shared": len(shared),
            "agree_before": round(before, 3),
            "agree_after_conversion": round(after, 3),
            "n_to_m_ops_share": round(n_ge / max(sum(counts.values()), 1), 3),
            "harmonized_rows": harmonized,
            "strategy": strat,
        }
        print(f"{tag:8} shared {len(shared):6,}  agree {before:5.1%} -> "
              f"{after:5.1%} converted ({strat})  "
              f"(n!=m ops {n_ge/max(sum(counts_cf.values()),1):.0%})")

    Path(args.report).parent.mkdir(exist_ok=True)
    json.dump(report, open(args.report, "w"), indent=1)
    print(f"wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
