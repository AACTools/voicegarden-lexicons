#!/usr/bin/env python3
"""Calibrate corruptor process weights from PhonBank alignment data.

Parses .cha files' %phoaln tiers (phone-level target↔produced
alignments) and measures the frequency of each phonological process,
replacing the illustrative DEFAULT_PROFILES weights with clinically
grounded ones.

Output: a JSON profile with measured weights + a summary of
observed vs expected process distributions.

Usage:
  python calibrate_phonbank.py --phonbank-dir /path/to/phonbank --out profile-calibrated.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import processes as P


def parse_phoaln(line: str) -> list[tuple[str, str]]:
    """Parse a %phoaln alignment line into (target, produced) pairs.

    Format: comma-separated target↔produced pairs, e.g.:
      ˈ↔ˈ,ʌ↔ʌ,m↔m ˈ↔ˈ,n↔n,o↔o,ʊ↔∅
    ∅ = deleted (produced nothing), * = not attempted
    """
    pairs = []
    # Split by spaces (word boundaries) then commas (phone pairs)
    for word in line.split():
        for pair in word.split(","):
            if "↔" not in pair:
                continue
            target, produced = pair.split("↔", 1)
            pairs.append((target, produced))
    return pairs


def classify_substitution(target: str, produced: str) -> str | None:
    """Which process explains this target→produced substitution?"""
    if target == produced or target in ("ˈ", "ˌ") or produced in ("ˈ", "ˌ"):
        return None
    if produced == "∅":
        return "deletion"
    if target == "∅":
        return "insertion"
    if target == "*":
        return "not_attempted"
    # Try each single-phone process
    for proc_name, fn in [
        ("stopping", P.stopping),
        ("fronting", P.fronting),
        ("gliding", P.gliding),
        ("voicing_flip", P.voicing_flip),
    ]:
        if fn(target) == produced:
            return proc_name
    return "unexplained_substitution"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phonbank-dir", required=True)
    ap.add_argument("--out", default="profile-calibrated.json")
    ap.add_argument("--max-files", type=int, default=0, help="0 = all")
    args = ap.parse_args()

    pb_dir = Path(args.phonbank_dir)
    cha_files = sorted(pb_dir.glob("**/*.cha"))
    if args.max_files:
        cha_files = cha_files[:args.max_files]

    # Counters
    process_counts: Counter = Counter()
    total_pairs = 0
    total_aligned = 0
    match_count = 0
    corpus_stats: Counter = Counter()
    # Track specific substitution patterns for the unexplained ones
    substitution_patterns: Counter = Counter()

    for cha in cha_files:
        corpus = str(cha).split("/")[1] if "/" in str(cha) else "?"
        try:
            content = cha.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        for line in content.splitlines():
            if not line.startswith("%phoaln:"):
                continue
            pairs = parse_phoaln(line[8:])
            for target, produced in pairs:
                if target in ("ˈ", "ˌ", "*") or produced in ("ˈ", "ˌ"):
                    continue
                total_pairs += 1
                corpus_stats[corpus] += 1

                if target == produced:
                    match_count += 1
                    total_aligned += 1
                    continue
                total_aligned += 1

                proc = classify_substitution(target, produced)
                if proc:
                    process_counts[proc] += 1
                elif produced != "∅" and target != "∅":
                    substitution_patterns[f"{target}→{produced}"] += 1
                    process_counts["unexplained_substitution"] += 1

    # Compute rates
    if total_aligned == 0:
        print("no aligned pairs found")
        return 1

    rates = {proc: count / total_aligned for proc, count in process_counts.items()}

    print(f"PhonBank calibration from {len(cha_files)} files")
    print(f"  total phone pairs: {total_pairs:,}")
    print(f"  aligned (excl. stress/*): {total_aligned:,}")
    print(f"  exact matches: {match_count:,} ({match_count/total_aligned*100:.1f}%)")
    print(f"\nProcess frequencies (per aligned phone):")
    for proc, rate in sorted(rates.items(), key=lambda x: -x[1]):
        print(f"  {proc:<30} {rate*100:5.2f}%  ({process_counts[proc]:,})")

    print(f"\nTop unexplained substitutions:")
    for pattern, count in substitution_patterns.most_common(15):
        print(f"  {pattern:<15} {count:,}")

    # Build the calibrated profile
    # Map measured rates to corruptor weights
    # The corruptor uses per-word rates; these are per-phone rates.
    # A word has ~4 phones, so per-word ≈ per-phone × 4 (rough)
    avg_word_len = 4.0
    profile = {}
    for proc in ("stopping", "fronting", "gliding", "voicing_flip"):
        if proc in rates:
            profile[proc] = min(1.0, rates[proc] * avg_word_len)
    if "deletion" in rates:
        profile["final_consonant_deletion"] = min(0.5, rates["deletion"] * 2)
    # Cluster reduction and assimilation need sequence analysis;
    # use conservative estimates from the unexplained rate
    unexplained = rates.get("unexplained_substitution", 0)
    profile["cluster_reduction"] = min(0.4, unexplained * 2)
    profile["regressive_place_assimilation"] = min(0.2, unexplained)

    output = {
        "source": "PhonBank (TalkBank) — CC BY-NC-SA (calibration only, "
                  "weights are facts)",
        "files_analyzed": len(cha_files),
        "total_aligned_phones": total_aligned,
        "exact_match_rate": match_count / total_aligned,
        "measured_process_rates": rates,
        "calibrated_profile": profile,
        "top_substitutions": dict(substitution_patterns.most_common(30)),
    }
    Path(args.out).write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"\nCalibrated profile written to {args.out}")
    print(f"  profile: {json.dumps(profile, indent=2)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
