#!/usr/bin/env python3
"""Many-to-many EM aligner for source-pair notation harmonization.

The anchor-based rewrites in harmonize_sources.py are context-free and
stall on languages whose sources disagree deeply (eng, ita). This
module learns a proper joint segmentation:

  1. init: block counts from anchor-based alignment (identity-biased)
  2. EM:   hard-EM iterations - Viterbi align each pair under the
           current block distribution, then re-estimate
           P(target_seg | source_seg) over blocks seen so far
  3. apply: Viterbi-decode wikipron -> gruut; exact-match on shared
           words is the harmonization gate

Blocks are (src_tuple, tgt_tuple) with up to --max-len tokens per
side, pruned to those observed at initialization.

Usage:
  python3 m2m_align.py --lang deu [--iters 5]   # one language
  python3 m2m_align.py --all                    # every dual-source lang
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys_path = Path(__file__).resolve().parent
import sys  # noqa: E402

sys.path.insert(0, str(sys_path))
from harmonize_sources import load  # noqa: E402

MAX_BLOCK = 2  # raised via --max-block


def init_blocks(pairs):
    """Anchor-seeded block counts (identity-biased)."""
    counts = Counter()
    for a, b in pairs:
        # identity: zip equal-length prefix + naive tail pairing
        n = min(len(a), len(b))
        for i in range(n):
            counts[((a[i],), (b[i],))] += 1
        if len(a) > n:
            counts[(tuple(a[n:]), tuple(b[n:]))] += 1
        elif len(b) > n:
            counts[((), tuple(b[n:]))] += 1
    return counts


def viterbi(src, tgt, logp, blocks_by_first):
    """Best segmentation of src into blocks mapping to tgt segments."""
    n, m = len(src), len(tgt)
    NEG = float("inf")
    d = [[NEG] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    d[0][0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            if d[i][j] == NEG or (i == 0 and j == 0):
                continue
            # consider blocks ENDING at (i, j)
            for di in (1, 2):
                for dj in (1, 2):
                    pi, pj = i - di, j - dj
                    if pi < 0 or pj < 0 or d[pi][pj] == NEG:
                        continue
                    sa = tuple(src[pi:i])
                    sb = tuple(tgt[pj:j])
                    if sa not in blocks_by_first:
                        continue
                    key = (sa, sb)
                    p = logp.get(key)
                    if p is None:
                        continue
                    v = d[pi][pj] + p
                    if v < d[i][j]:
                        d[i][j] = v
                        back[i][j] = (pi, pj, sa, sb)
    if d[n][m] == NEG:
        return None
    ops = []
    i, j = n, m
    while (i, j) != (0, 0):
        pi, pj, sa, sb = back[i][j]
        ops.append((sa, sb))
        i, j = pi, pj
    ops.reverse()
    return ops


def reestimate(pairs, logp, blocks_by_first):
    counts = Counter()
    for a, b in pairs:
        ops = viterbi(a, b, logp, blocks_by_first)
        if ops:
            for sa, sb in ops:
                counts[(sa, sb)] += 1
        else:
            # fallback: identity on the overlap
            n = min(len(a), len(b))
            for i in range(n):
                counts[((a[i],), (b[i],))] += 1
    return counts


def build_dist(counts):
    """P(tgt | src) with light smoothing; also the DP block index."""
    src_tot = Counter()
    for (sa, _sb), c in counts.items():
        src_tot[sa] += c
    logp = {}
    for (sa, sb), c in counts.items():
        logp[(sa, sb)] = -math.log((c + 0.05) / (src_tot[sa] + 0.05 * 4))
    blocks_by_first = defaultdict(set)
    for (sa, _sb) in counts:
        if sa and len(sa) <= MAX_BLOCK:
            blocks_by_first[sa[0]].add(sa)
    return logp, blocks_by_first


def best_targets(logp, blocks_by_first):
    """Most probable target segment per source segment."""
    best = {}
    for (sa, sb), p in logp.items():
        if sa not in best or p < best[sa][1]:
            best[sa] = (sb, p)
    return best


def convert(tokens, best, blocks_by_first):
    """1-D Viterbi: consume source segments, emit their best targets.
    Unseen tokens pass through as identity with a penalty."""
    n = len(tokens)
    NEG = float("inf")
    d = [NEG] * (n + 1)
    d[0] = 0.0
    back = [None] * (n + 1)
    for i in range(1, n + 1):
        for length in (1, 2):
            pi = i - length
            if pi < 0 or d[pi] == NEG:
                continue
            sa = tuple(tokens[pi:i])
            if sa in best:
                sb, p = best[sa]
                v = d[pi] + p
                if v < d[i]:
                    d[i] = v
                    back[i] = (pi, sb)
            elif length == 1:
                v = d[pi] + 4.0  # unseen-token identity penalty
                if v < d[i]:
                    d[i] = v
                    back[i] = (pi, sa)
    out = []
    i = n
    while i:
        pi, sb = back[i]
        out.extend(sb)
        i = pi
    out.reverse()
    return out


def harmonize(tag: str, iters: int, min_shared: int) -> dict | None:
    d = REPO / "staging" / tag
    G, W = load(d / "gruut.tsv"), load(d / "wikipron.tsv")
    shared = sorted(set(G) & set(W))
    if len(shared) < min_shared:
        return None
    pairs = [(W[w], G[w]) for w in shared]
    before = sum(a == b for a, b in pairs) / len(pairs)

    counts = init_blocks(pairs)
    logp, blocks = build_dist(counts)
    for _it in range(iters):
        counts = reestimate(pairs, logp, blocks)
        logp, blocks = build_dist(counts)
    best = best_targets(logp, blocks)

    hit = sum(convert(a, best, blocks) == b for a, b in pairs) / len(pairs)
    print(f"{tag:8} shared {len(shared):6,}  agree {before:5.1%} -> {hit:5.1%} (M2M EM, {iters} iters)")
    return {
        "tag": tag, "shared": len(shared),
        "agree_before": round(before, 3),
        "agree_after_m2m": round(hit, 3),
        "iterations": iters,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--iters", type=int, default=5)
    ap.add_argument("--max-block", type=int, default=2)
    ap.add_argument("--min-shared", type=int, default=200)
    ap.add_argument("--report", default="audit/m2m-report.json")
    args = ap.parse_args()

    global MAX_BLOCK
    MAX_BLOCK = args.max_block
    langs = ([args.lang] if args.lang else
             sorted(p.parent.name for p in REPO.glob("staging/*/gruut.tsv")
                    if (p.parent / "wikipron.tsv").exists())
             if args.all else [])
    results = []
    for tag in langs:
        r = harmonize(tag, args.iters, args.min_shared)
        if r:
            results.append(r)
    out = REPO / args.report
    json.dump(results, out.open("w"), indent=1)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
