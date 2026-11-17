#!/usr/bin/env python3
"""Generate the synthetic fuzzy-decode training corpus.

Corrupts staging lexicons at multiple severity levels to produce
(surface_phonemes, canonical_phonemes, word) triples for training the
ByT5 surface→canonical decoder (plan item 3). Each triple becomes:

  input:  "<lang>: surface_phonemes"     (what was observed)
  target: "canonical_phonemes"           (what was intended)

Multiple profiles (english_child, adult_casual, perceptual) and
severity sweeps (0.5, 1.0, 1.5) generate diverse corruption patterns.
Canonical (uncorrupted) pairs are included as ~20% of the corpus so the
model also learns identity mapping (important for the decoder to not
over-correct).

Output format: same TSV as the ByT5 corpus builder:
  lang\tword\tcanonical\tsurface\tprocesses

Usage:
  python gen_synthetic.py --lexicon ../../staging/eng/merged.tsv \
      --lang eng --n 50000 --out fuzzy-corpus/
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from corruptor import (corrupt, perceptual_corrupt, DEFAULT_PROFILES)


def generate_pairs(lexicon_path: Path, lang: str, n: int, seed: int = 7,
                   include_clean: bool = True) -> list[dict]:
    """Generate corrupted/canonical pairs at multiple severities."""
    rng = random.Random(seed)

    # Load lexicon
    entries = []
    for line in lexicon_path.open(encoding="utf-8"):
        word, _, pron = line.rstrip("\n").partition("\t")
        if word and pron:
            entries.append((word, pron))
    if not entries:
        return []

    # Sample n entries (with replacement for diversity if n > len)
    rng.shuffle(entries)
    result = []

    profiles = list(DEFAULT_PROFILES.keys()) + ["perceptual"]
    severities = [0.5, 1.0, 1.5]

    for i in range(n):
        word, canonical = entries[i % len(entries)]

        # 15% clean pairs (identity mapping — the decoder must learn
        # not to over-correct)
        if include_clean and rng.random() < 0.15:
            result.append({
                "lang": lang, "word": word,
                "canonical": canonical, "surface": canonical,
                "processes": "",
            })
            continue

        # Pick a profile and severity, retry until at least one
        # process fires (short words often escape all processes)
        profile_name = rng.choice(profiles)
        severity = rng.choice(severities)

        surface_tokens = None
        applied = []
        for _ in range(5):  # retry up to 5 times
            if profile_name == "perceptual":
                surface_tokens, applied = perceptual_corrupt(
                    canonical.split(), rng, rate=0.08 * severity)
            else:
                profile = DEFAULT_PROFILES[profile_name]
                scaled = {k: min(1.0, v * severity) for k, v in profile.items()}
                surface_tokens, applied = corrupt(
                    canonical.split(), scaled, rng)
            if applied:
                break
            # Retry with a different profile/severity
            profile_name = rng.choice(profiles)
            severity = rng.choice(severities)

        if not applied:
            # After 5 retries, include as clean pair
            result.append({
                "lang": lang, "word": word,
                "canonical": canonical, "surface": canonical,
                "processes": "",
            })
            continue

        surface = " ".join(surface_tokens) if surface_tokens else canonical
        if not surface:
            surface = canonical

        result.append({
            "lang": lang, "word": word,
            "canonical": canonical, "surface": surface,
            "processes": ",".join(applied),
            "profile": profile_name, "severity": severity,
        })

    return result


def write_corpus(pairs: list[dict], out_dir: Path, lang: str) -> None:
    """Write train/val/test splits in the ByT5 corpus format."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # Split: 98% train, 1% val, 1% test
    rng = random.Random(7)
    rng.shuffle(pairs)
    n_test = max(10, len(pairs) // 100)
    n_val = max(10, len(pairs) // 100)
    test = pairs[:n_test]
    val = pairs[n_test:n_test + n_val]
    train = pairs[n_test + n_val:]

    for split, data in [("train", train), ("val", val), ("test", test)]:
        path = out_dir / f"fuzzy-{split}.tsv"
        with path.open("w", encoding="utf-8") as f:
            for p in data:
                # ByT5 corpus format: lang\tinput\toutput
                # For surface→canonical: input=surface, output=canonical
                f.write(f"{lang}\t{p['surface']}\t{p['canonical']}\n")
        print(f"  {split}: {len(data)} -> {path}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lexicon", required=True)
    ap.add_argument("--lang", required=True, help="corpus lang tag (e.g. eng)")
    ap.add_argument("--n", type=int, default=50000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="fuzzy-corpus")
    args = ap.parse_args()

    lexicon_path = Path(args.lexicon)
    out_dir = Path(args.out)

    print(f"Generating {args.n} pairs from {lexicon_path}")
    pairs = generate_pairs(lexicon_path, args.lang, args.n, args.seed)
    print(f"  generated {len(pairs)} pairs")

    write_corpus(pairs, out_dir, args.lang)

    # Stats
    clean = sum(1 for p in pairs if p["surface"] == p["canonical"])
    print(f"\nStats:")
    print(f"  clean (identity): {clean} ({clean/len(pairs)*100:.0f}%)")
    print(f"  corrupted: {len(pairs) - clean} ({(len(pairs)-clean)/len(pairs)*100:.0f}%)")

    from collections import Counter
    proc_counts = Counter()
    for p in pairs:
        if p.get("processes"):
            for proc in p["processes"].split(","):
                proc_counts[proc] += 1
    print(f"\nProcess distribution:")
    for proc, count in proc_counts.most_common(10):
        print(f"  {proc:<30} {count:>6} ({count/len(pairs)*100:.1f}%)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
