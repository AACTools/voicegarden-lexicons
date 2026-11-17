#!/usr/bin/env python3
"""The WhatsApp case as the plan's standing unit test (§4.4).

A child said "remote control" as [ˈməʊkrən ˈtrʌl]. The v0 corruptor
must be able to produce, from the canonical pronunciation of "remote
control", a surface that exhibits the same processes (weak-syllable
deletion, t->k assimilation) and lands within a small edit distance of
the observed form. This pins the *mechanism*, not a phonetic
transcript — the observed form also has vowel drift the v0 inventory
does not model (əʊ -> əʊ ok, əʊ -> ʌ in "trʌl").

Run: python test_remote_control.py
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from corruptor import corrupt, DEFAULT_PROFILES

CANONICAL_REMOTE = "r ɪ ˈ m oʊ t k ən ˈ t ɹ oʊ l".split()
OBSERVED = "ˈ m əʊ k ɹ ə n ˈ t ɹ ʌ l".split()


def edit_distance(a: list[str], b: list[str]) -> int:
    dp = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        dp[i][0] = i
    for j in range(len(b) + 1):
        dp[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1,
                           dp[i - 1][j - 1] + (a[i - 1] != b[j - 1]))
    return dp[-1][-1]


def main() -> int:
    profile = DEFAULT_PROFILES["english_child"]
    best = None
    best_d = 99
    best_procs = None
    # deterministic sweep: 500 seeds, keep the surface closest to observed
    for seed in range(500):
        rng = random.Random(seed)
        surface, applied = corrupt(CANONICAL_REMOTE, profile, rng,
                                   max_applications=4)
        d = edit_distance(surface, OBSERVED)
        if d < best_d:
            best_d, best, best_procs = d, surface, applied
            if d == 0:
                break

    print("canonical:", " ".join(CANONICAL_REMOTE))
    print("observed: ", " ".join(OBSERVED))
    print("best      ", " ".join(best))
    print("distance:", best_d, "| processes:", best_procs)

    # Mechanism assertions (the plan's test): the corruption machinery
    # must reproduce the documented process chain — weak-syllable
    # deletion of the pretonic initial + t->k regressive assimilation —
    # and land close. The residual distance (vowel drift əʊ/ʌ, the
    # epenthetic ɹ) belongs to processes v0 deliberately does not model
    # yet; the test pins the mechanism, not the transcript.
    assert "weak_syllable_deletion" in best_procs, \
        f"weak-syllable deletion missing from chain: {best_procs}"
    assert "regressive_place_assimilation" in best_procs, \
        f"t->k assimilation missing from chain: {best_procs}"
    assert best_d <= 6, f"surface too far from observed ({best_d})"
    assert edit_distance(best, OBSERVED) < edit_distance(CANONICAL_REMOTE, OBSERVED), \
        "corruption did not move toward the observed form"
    print("REMOTE CONTROL TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
