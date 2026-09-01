#!/usr/bin/env python3
"""Many-to-many EM aligner for IPA notation harmonisation.

Learns a joint segmentation between two transcription systems (e.g.
gruut and WikiPron) and can convert one into the other. Can be used as
a standalone CLI for any source-pair TSVs, or within the repo's
staging workflow.

Usage (within the repo):
  python3 m2m_align.py --lang deu [--iters 5]      # one language
  python3 m2m_align.py --all [--apply]              # every dual-source lang

Usage (standalone, any two TSV files):
  python3 m2m_align.py --source gruut.tsv wikipron.tsv \\
    --out-map deu-map.json --out-tsv deu-converted.tsv

  python3 m2m_align.py --apply-map deu-map.json \\
    --in-tsv more-wikipron.tsv --out-tsv more-converted.tsv
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

MAX_BLOCK = 2  # raised via --max-block


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_tsv(path: Path) -> dict[str, list[str]]:
    """Load a word\tphoneme TSV into a dict."""
    rows: dict[str, list[str]] = {}
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        word, _, pron = line.partition("\t")
        word = word.strip()
        pron = pron.strip()
        if not word or not pron:
            continue
        rows.setdefault(word, []).extend(pron.split())
    return rows


def load_tsv_simple(path: Path) -> dict[str, list[str]]:
    """Load a word\tphoneme TSV, overwriting duplicates with last."""
    rows: dict[str, list[str]] = {}
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.rstrip("\n").split("\t")
        if len(parts) != 2:
            continue
        word, pron = parts
        word = word.strip()
        pron = pron.strip()
        if not word or not pron:
            continue
        rows[word] = pron.split()
    return rows


# ---------------------------------------------------------------------------
# Alignment helpers
# ---------------------------------------------------------------------------

def init_blocks(pairs):
    """Anchor-seeded block counts (identity-biased)."""
    counts = Counter()
    for a, b in pairs:
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
            for di in range(1, MAX_BLOCK + 1):
                for dj in range(1, MAX_BLOCK + 1):
                    pi, pj = i - di, j - dj
                    if pi < 0 or pj < 0 or d[pi][pj] == NEG:
                        continue
                    if src[pi] not in blocks_by_first:
                        continue
                    sa = tuple(src[pi:i])
                    sb = tuple(tgt[pj:j])
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


def reestimate(pairs, logp, blocks_by_first, stats=None):
    counts = Counter()
    for a, b in pairs:
        ops = viterbi(a, b, logp, blocks_by_first)
        if ops:
            for sa, sb in ops:
                counts[(sa, sb)] += 1
        else:
            if stats is not None:
                stats["fallback_pairs"] += 1
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
    """1-D Viterbi: consume source segments, emit their best targets."""
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
                v = d[pi] + 4.0
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


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train_map(source_dict: dict, target_dict: dict,
              iters: int = 5, min_shared: int = 200,
              verbose: bool = True) -> dict | None:
    """Learn an M2M map from source_dict to target_dict over shared words.

    Args:
        source_dict: word -> [phoneme tokens] from the source system.
        target_dict: word -> [phoneme tokens] from the target system.
        iters: EM iterations.
        min_shared: minimum shared words to bother.

    Returns:
        A dict with keys: tag, shared, agree_before, agree_after_m2m,
        iterations, best (serializable block map), logp (serializable).
        None if fewer than min_shared words are shared.
    """
    shared = sorted(set(source_dict) & set(target_dict))
    if len(shared) < min_shared:
        return None

    pairs = [(source_dict[w], target_dict[w]) for w in shared]
    before = sum(a == b for a, b in pairs) / len(pairs)

    counts = init_blocks(pairs)
    logp, blocks = build_dist(counts)
    fallback_stats = {"fallback_pairs": 0}
    for _it in range(iters):
        counts = reestimate(pairs, logp, blocks, fallback_stats)
        logp, blocks = build_dist(counts)
    best = best_targets(logp, blocks)

    hit = sum(convert(a, best, blocks) == b for a, b in pairs) / len(pairs)
    if verbose:
        print(f"shared {len(shared):,}  agree {before:.1%} -> {hit:.1%} (M2M EM, {iters} iters)",
              file=sys.stderr)
        if fallback_stats["fallback_pairs"]:
            print(f"  unreconstructible pairs: {fallback_stats['fallback_pairs']}",
                  file=sys.stderr)

    return {
        "shared": len(shared),
        "agree_before": round(before, 3),
        "agree_after_m2m": round(hit, 3),
        "iterations": iters,
        "best": _serialize_best(best, blocks),
    }


def _serialize_best(best, blocks_by_first):
    """Convert best map to JSON-safe format: src_tuple -> (tgt_tuple, score)."""
    out = {}
    for (sa, (sb, score)) in best.items():
        key = " ".join(sa)
        out[key] = {"tgt": " ".join(sb), "score": round(score, 4)}
    return out


def _deserialize_best(data: dict) -> tuple[dict, defaultdict]:
    """Restore best map from JSON format."""
    best = {}
    blocks_by_first: defaultdict = defaultdict(set)
    for key, val in data.items():
        sa = tuple(key.split())
        sb = tuple(val["tgt"].split())
        best[sa] = (sb, val["score"])
        if sa:
            blocks_by_first[sa[0]].add(sa)
    return best, blocks_by_first


def apply_map(source_dict: dict, best_data: dict,
              verbose: bool = True) -> dict[str, str]:
    """Convert source_dict to target conventions using a learned map.

    Args:
        source_dict: word -> [phoneme tokens] from the source system.
        best_data: the 'best' dict from `train_map()` output.

    Returns:
        word -> space-joined phoneme string (converted).
    """
    best, blocks_by_first = _deserialize_best(best_data)
    out = {}
    skipped = 0
    for w, tokens in source_dict.items():
        conv = convert(tokens, best, blocks_by_first)
        if conv:
            out[w] = " ".join(conv)
        else:
            skipped += 1
    if verbose and skipped:
        print(f"  skipped {skipped} words (conversion failed)", file=sys.stderr)
    return out


# ---------------------------------------------------------------------------
# Staging workflow (original repo usage)
# ---------------------------------------------------------------------------

def harmonize_staging(tag: str, iters: int, min_shared: int,
                      apply: bool = False) -> dict | None:
    """Run the aligner on a staging/<tag>/ language pair."""
    import os  # noqa: E402
    d = Path(__file__).resolve().parents[2] / "staging" / tag
    G = load_tsv(d / "gruut.tsv")
    W = load_tsv(d / "wikipron.tsv")
    tag = tag

    result = train_map(W, G, iters=iters, min_shared=min_shared, verbose=True)
    if result is None:
        return None
    result["tag"] = tag

    if apply and result:
        # Write harmonized merged.tsv: gruut primary + converted wikipron fill
        best, blocks_by_first = _deserialize_best(result["best"])
        out_rows = [(w, " ".join(G[w])) for w in sorted(G)]
        added = 0
        for w in sorted(W):
            if w not in G:
                conv = convert(W[w], best, blocks_by_first)
                if conv:
                    out_rows.append((w, " ".join(conv)))
                    added += 1
        out_rows.sort()
        with (d / "merged.tsv").open("w", encoding="utf-8") as f:
            for w, p in out_rows:
                f.write(f"{w}\t{p}\n")
        print(f"  {tag}: harmonized merged.tsv = {len(G):,} gruut + {added:,} converted wikipron")
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="M2M EM aligner for IPA notation harmonisation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Staging mode (repo-internal)
    staging = ap.add_argument_group("staging mode (repo-internal)")
    staging.add_argument("--lang", help="staging language tag (e.g. deu)")
    staging.add_argument("--all", action="store_true",
                         help="run on every dual-source staging language")
    staging.add_argument("--apply", action="store_true",
                         help="rewrite staging/<lang>/merged.tsv with harmonised data")

    # Standalone mode (any TSV files)
    standalone = ap.add_argument_group("standalone mode (any TSV files)")
    standalone.add_argument("--source", nargs=2, metavar=("SOURCE", "TARGET"),
                            help="learn map from SOURCE.tsv to TARGET.tsv word\tphoneme files")
    standalone.add_argument("--apply-map", metavar="MAP_JSON",
                            help="apply a previously learned map JSON")
    standalone.add_argument("--in-tsv", metavar="TSV",
                            help="input TSV to convert (with --apply-map)")
    standalone.add_argument("--out-tsv", metavar="TSV",
                            help="write converted TSV here")
    standalone.add_argument("--out-map", metavar="JSON",
                            help="write learned map JSON here")

    # Common options
    common = ap.add_argument_group("common options")
    common.add_argument("--iters", type=int, default=5)
    common.add_argument("--max-block", type=int, default=2)
    common.add_argument("--min-shared", type=int, default=200)
    common.add_argument("--report", default="audit/m2m-report.json",
                        help="staging report path (default: audit/m2m-report.json)")

    args = ap.parse_args()
    global MAX_BLOCK
    MAX_BLOCK = args.max_block

    # --- Standalone: apply existing map ---
    if args.apply_map:
        if not args.in_tsv:
            print("--apply-map requires --in-tsv", file=sys.stderr)
            return 1
        map_data = json.loads(Path(args.apply_map).read_text())
        best_data = map_data.get("best", map_data)
        source = load_tsv_simple(Path(args.in_tsv))
        converted = apply_map(source, best_data)
        if args.out_tsv:
            with open(args.out_tsv, "w", encoding="utf-8") as f:
                for w in sorted(converted):
                    f.write(f"{w}\t{converted[w]}\n")
            print(f"wrote {len(converted)} entries to {args.out_tsv}")
        else:
            for w, p in sorted(converted.items()):
                print(f"{w}\t{p}")
        return 0

    # --- Standalone: learn map ---
    if args.source:
        src_path, tgt_path = args.source
        source = load_tsv_simple(Path(src_path))
        target = load_tsv_simple(Path(tgt_path))
        print(f"source: {Path(src_path).name} ({len(source)} words)",
              file=sys.stderr)
        print(f"target: {Path(tgt_path).name} ({len(target)} words)",
              file=sys.stderr)
        result = train_map(source, target, iters=args.iters,
                           min_shared=args.min_shared)
        if result is None:
            print(f"too few shared words (< {args.min_shared})", file=sys.stderr)
            return 1
        if args.out_map:
            Path(args.out_map).write_text(
                json.dumps(result, indent=1, ensure_ascii=False))
            print(f"wrote map to {args.out_map}", file=sys.stderr)
        if args.out_tsv:
            best_data = result["best"]
            converted = apply_map(source, best_data)
            with open(args.out_tsv, "w", encoding="utf-8") as f:
                for w in sorted(converted):
                    f.write(f"{w}\t{converted[w]}\n")
            print(f"wrote {len(converted)} entries to {args.out_tsv}", file=sys.stderr)
        return 0

    # --- Staging mode ---
    REPO = Path(__file__).resolve().parents[2]
    if args.lang or args.all:
        if args.lang:
            langs = [args.lang]
        else:
            langs = sorted(p.parent.name for p in REPO.glob("staging/*/gruut.tsv")
                           if (p.parent / "wikipron.tsv").exists())
        results = []
        for tag in langs:
            r = harmonize_staging(tag, args.iters, args.min_shared,
                                  apply=args.apply)
            if r:
                results.append(r)
        report_path = REPO / args.report
        report_path.parent.mkdir(parents=True, exist_ok=True)
        json.dump(results, report_path.open("w"), indent=1)
        print(f"wrote {report_path}")
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())