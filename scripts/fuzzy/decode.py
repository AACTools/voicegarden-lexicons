#!/usr/bin/env python3
"""Fuzzy phoneme decoder MVP — noisy-channel P2G over the lexicon.

Implements plan sequencing item 2: decode systematically-corrupted
phoneme sequences back to intended text by composing the lexicon FST
with an edit-distance-tolerant search.

Method (simple but effective for MVP):
  1. For each observed phoneme sequence, search the lexicon for entries
     within a phoneme edit distance threshold (severity-scaled).
  2. Score candidates by P(observed | canonical) using the process
     inventory as a corruption model — processes that explain the
     difference (e.g. "the t→k is an assimilation") cost less than
     unexplained substitutions.
  3. Return k-best candidates with the attributed process chain.

This is the Python prototype; the production version composes
profile-inverse WFSTs with the lexicon FST through the floravox stack.

Usage:
  python decode.py --lexicon ../../staging/eng/merged.tsv \
      --observed "ˈ m əʊ k ɹ ə n ˈ t ɹ ʌ l" --k 5
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import processes as P
from corruptor import PHONE_PROCESSES


def phoneme_edit_distance(a: list[str], b: list[str],
                          process_costs: dict | None = None) -> tuple[float, list[str]]:
    """Weighted edit distance where process-explainable changes cost less.

    Returns (cost, operations) where operations describe the cheapest
    corruption chain from `a` (canonical) to `b` (observed).
    """
    if process_costs is None:
        process_costs = {}

    n, m = len(a), len(b)
    # dp[i][j] = (cost, ops) for a[:i] -> b[:j]
    dp = [[(0.0, []) for _ in range(m + 1)] for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = (dp[i-1][0][0] + 1.0, dp[i-1][0][1] + [f"del:{a[i-1]}"])
    for j in range(1, m + 1):
        dp[0][j] = (dp[0][j-1][0] + 1.0, dp[0][j-1][1] + [f"ins:{b[j-1]}"])

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            candidates = []

            # substitution (or match)
            if a[i-1] == b[j-1]:
                candidates.append((dp[i-1][j-1][0], dp[i-1][j-1][1]))
            else:
                # check if a process explains this substitution
                cost = 0.4  # unexplained substitution penalty
                label = f"sub:{a[i-1]}→{b[j-1]}"
                for proc_name, fn in PHONE_PROCESSES.items():
                    result = fn(a[i-1])
                    if result == b[j-1]:
                        cost = process_costs.get(proc_name, 0.2)
                        label = f"{proc_name}:{a[i-1]}→{b[j-1]}"
                        break
                candidates.append((dp[i-1][j-1][0] + cost,
                                   dp[i-1][j-1][1] + [label]))

            # deletion (a[i-1] dropped)
            candidates.append((dp[i-1][j][0] + process_costs.get("deletion", 0.3),
                               dp[i-1][j][1] + [f"del:{a[i-1]}"]))

            # insertion
            candidates.append((dp[i][j-1][0] + process_costs.get("insertion", 0.5),
                               dp[i][j-1][1] + [f"ins:{b[j-1]}"]))

            dp[i][j] = min(candidates, key=lambda x: x[0])

    return dp[n][m]


def normalize_stress(phones: list[str]) -> list[str]:
    """Normalize stress-mark conventions: the lexicon attaches stress
    to the following vowel (ˈoʊ), some sources use separate tokens
    (ˈ oʊ). This merges separate stress marks into their vowel."""
    out: list[str] = []
    for ph in phones:
        if ph in P.STRESS and out:
            # attach to the NEXT vowel — we'll handle in the next iteration
            # For now, keep as-is but note the convention
            out.append(ph)
        else:
            out.append(ph)
    return out


def load_lexicon(path: Path) -> dict[str, list[str]]:
    """Load word → phonemes pairs (dictionary for exact-match fast path)."""
    entries = {}
    for line in path.open(encoding="utf-8"):
        word, _, pron = line.rstrip("\n").partition("\t")
        if word and pron and word not in entries:
            entries[word] = pron.split()
    return entries


def build_length_index(lexicon: dict[str, list[str]]) -> dict[int, list[tuple[str, list[str]]]]:
    """Pre-compute phone lengths so decode only searches similar-length entries."""
    index: dict[int, list[tuple[str, list[str]]]] = {}
    for word, phones in lexicon.items():
        plen = sum(1 for p in phones if p not in P.STRESS)
        index.setdefault(plen, []).append((word, phones))
    return index


def search_neighborhood(observed: list[str], index: dict,
                         radius: int | None = None) -> list[tuple[str, list[str]]]:
    """Get lexicon entries within the given phone-length radius of the
    observed sequence. Default radius derives from the cost model: each
    deletion costs ≥0.3, so the length difference is bounded by
    max_distance / 0.3. Use a tight radius (2) for the MVP prototype."""
    obs_len = sum(1 for p in observed if p not in P.STRESS)
    if radius is None:
        radius = 2  # MVP: tight is fast, and max_distance ≤ 1.5 can't
                     # produce length differences > 2 at these costs
    result = []
    for length in range(max(0, obs_len - radius), obs_len + radius + 1):
        result.extend(index.get(length, []))
    return result


def decode(observed: list[str], lexicon: dict[str, list[str]] | list,
           max_distance: float = 3.0, k: int = 5,
           process_costs: dict | None = None) -> list[tuple[float, str, list[str], list[str]]]:
    """Find the k-best candidate words for an observed phoneme sequence.

    Two-stage search for the Python prototype:
    1. Cheap pre-filter on first-phoneme compatibility (child speech
       preserves word onsets — gliding/fronting change them but the
       result is still a known phone)
    2. Full weighted edit distance on survivors

    The production version composes WFSTs; this proves the mechanism.
    """
    if isinstance(lexicon, dict):
        pairs = list(lexicon.items())
    else:
        pairs = lexicon

    # Pre-compute observed properties
    obs_core = [p for p in observed if p not in P.STRESS]
    obs_len = len(obs_core)
    obs_first = obs_core[0] if obs_core else ""
    obs_last = obs_core[-1] if obs_core else ""

    # Build the set of first phones that could map to the observed first
    # (for pre-filtering: exact match + common process outputs)
    compatible_first = {obs_first}
    for proc_name, fn in PHONE_PROCESSES.items():
        # What phones could produce obs_first via this process?
        # Inverse mapping: for each phone in our inventory, check if
        # the process maps it to obs_first
        for test_ph in ("ɹ", "r", "l", "s", "ʃ", "f", "θ", "k", "ɡ",
                        "p", "b", "t", "d", "v", "z", "ð", "m", "n"):
            if fn(test_ph) == obs_first:
                compatible_first.add(test_ph)
    # Also accept stress-marked variants
    compatible_first.add("ˈ" + obs_first)
    compatible_first.add("ˌ" + obs_first)

    candidates = []
    for word, phones in pairs:
        # Length filter
        phone_core = [p for p in phones if p not in P.STRESS]
        if abs(len(phone_core) - obs_len) > 3:
            continue
        # First-phoneme filter (cheap set lookup, no edit distance yet)
        first = phone_core[0] if phone_core else ""
        if first not in compatible_first and phones[0] not in compatible_first:
            continue
        cost, ops = phoneme_edit_distance(phones, observed, process_costs)
        if cost <= max_distance:
            proc_ops = [op for op in ops if not op.startswith("=")]
            candidates.append((cost, word, phones, proc_ops))

    candidates.sort(key=lambda x: x[0])
    return candidates[:k]


# Default process costs: how "expensive" each corruption type is.
# Lower = more likely (common processes cost less than rare ones).
# These are ILLUSTRATIVE — PhonBank calibration replaces them.
DEFAULT_COSTS = {
    "stopping": 0.2,
    "fronting": 0.2,
    "gliding": 0.15,
    "voicing_flip": 0.2,
    "deletion": 0.3,     # any phone deleted
    "insertion": 0.5,    # epenthesis is rarer
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lexicon", required=True)
    ap.add_argument("--observed", required=True,
                    help="space-separated observed phonemes (with stress marks)")
    ap.add_argument("--max-distance", type=float, default=3.0)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--costs", help="JSON file of process costs")
    args = ap.parse_args()

    costs = dict(DEFAULT_COSTS)
    if args.costs:
        costs.update(json.loads(Path(args.costs).read_text()))

    observed = args.observed.split()
    lexicon = load_lexicon(Path(args.lexicon))
    print(f"lexicon: {len(lexicon)} entries")
    print(f"observed: {' '.join(observed)}")
    print()

    results = decode(observed, lexicon, args.max_distance, args.k, costs)
    if not results:
        print("no candidates within distance threshold")
        return 1

    for i, (score, word, phones, ops) in enumerate(results, 1):
        print(f"  {i}. {word:<20} score={score:.2f}  "
              f"canonical={' '.join(phones)}")
        if ops:
            print(f"     processes: {', '.join(ops)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
