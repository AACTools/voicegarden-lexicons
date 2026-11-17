#!/usr/bin/env python3
"""Stochastic corruptor: canonical -> systematically-errorful surface.

Applies a weighted profile of phonological processes (processes.py) to
canonical phone sequences, producing (surface, canonical, attribution)
training pairs for the fuzzy decoder — the plan's sequencing item 1.

Severity = expected process applications per word; implemented as
per-process rates. A profile is a JSON dict
  {"process_name": rate, ...}
Rates are probabilities per applicable site. The shipped default
profiles are ILLUSTRATIVE (no clinical calibration yet — that is the
PhonBank stage; see the plan §2c/§6).

Usage:
  python corruptor.py --lexicon staging/eng/merged.tsv --profile english_child \
      --n 1000 --seed 7 --out fuzzy-corpus/en-child.tsv
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import processes as P

# ILLUSTRATIVE v0 profiles — shape only, no clinical calibration
DEFAULT_PROFILES = {
    # "four-year-old English" shape: deletion + place processes prominent
    "english_child": {
        "weak_syllable_deletion": 0.35,
        "final_consonant_deletion": 0.18,
        "cluster_reduction": 0.30,
        "stopping": 0.25,
        "fronting": 0.20,
        "gliding": 0.15,
        "voicing_flip": 0.10,
        "regressive_place_assimilation": 0.20,
        "vowel_neutralisation": 0.10,
    },
    # adult casual speech shape (Buckeye phenomena): reduction, not substitution
    "adult_casual": {
        "weak_syllable_deletion": 0.25,
        "final_consonant_deletion": 0.10,
        "cluster_reduction": 0.35,
        "vowel_neutralisation": 0.40,
        "regressive_place_assimilation": 0.25,
        "gliding": 0.02,
        "stopping": 0.01,
        "fronting": 0.01,
        "voicing_flip": 0.05,
    },
    # perceptual mishearing shape (rates unused for substitution; the
    # confusion table drives it — corruptor applies M-N top pairs)
    "perceptual": {},
}

# single-phone processes: name -> function
PHONE_PROCESSES = {
    "stopping": P.stopping,
    "fronting": P.fronting,
    "gliding": P.gliding,
    "voicing_flip": P.voicing_flip,
}
# sequence processes: name -> function returning (new, attribution) | other
SEQ_PROCESSES = {
    "final_consonant_deletion": P.final_consonant_deletion,
    "cluster_reduction": P.cluster_reduction,
    "regressive_place_assimilation": P.regressive_place_assimilation,
    "weak_syllable_deletion": P.weak_syllable_deletion,
    "vowel_neutralisation": P.vowel_neutralisation,
}


def corrupt(phones: list[str], profile: dict, rng: random.Random,
            max_applications: int = 3) -> tuple[list[str], list[str]]:
    """Apply the profile stochastically. Returns (surface, applied)."""
    cur = list(phones)
    applied: list[str] = []
    # sequence processes in RANDOM order per call — process interaction
    # is itself stochastic (deletion before/after reduction changes the
    # outcome), which the fixed-order version got wrong on the
    # remote-control chain
    seq_names = list(SEQ_PROCESSES.items())
    rng.shuffle(seq_names)
    for name, fn in seq_names:
        rate = profile.get(name, 0.0)
        if rate <= 0 or len(applied) >= max_applications:
            continue
        if rng.random() < rate:
            if name == "vowel_neutralisation":
                out = fn(cur)
                if out is not None:
                    cur = out
                    applied.append(name)
            else:
                res = fn(cur)
                if res is not None:
                    cur = res[0]
                    applied.append(name)
    out = []
    for ph in cur:
        if ph in P.STRESS:
            out.append(ph)
            continue
        newph = ph
        for name, fn in PHONE_PROCESSES.items():
            rate = profile.get(name, 0.0)
            if rate <= 0 or len(applied) >= max_applications:
                continue
            if rng.random() < rate:
                r = fn(newph)
                if r is not None and r != newph:
                    newph = r
                    applied.append(name)
        out.append(newph)
    return out, applied


def perceptual_corrupt(phones: list[str], rng: random.Random,
                       rate: float = 0.08) -> tuple[list[str], list[str]]:
    """Confusion-matrix substitution (Miller-Nicely top pairs, v0)."""
    out = []
    applied = []
    for ph in phones:
        cands = [(b, p) for (a, b), p in P.MILLER_NICELY_TOP.items() if a == ph]
        if cands and rng.random() < rate:
            # weighted pick
            total = sum(p for _, p in cands)
            x = rng.random() * total
            for b, p in cands:
                x -= p
                if x <= 0:
                    out.append(b)
                    applied.append(f"confuse:{ph}>{b}")
                    break
            else:
                out.append(ph)
        else:
            out.append(ph)
    return out, applied


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lexicon", required=True, help="word\\tphones TSV")
    ap.add_argument("--profile", default="english_child")
    ap.add_argument("--custom-profile", help="JSON file overriding the built-ins")
    ap.add_argument("--perceptual", action="store_true",
                    help="apply confusion substitutions instead of processes")
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--severity", type=float, default=1.0,
                    help="multiplier on all process rates")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", help="output TSV (word\\tcanonical\\tsurface\\tprocesses)")
    args = ap.parse_args()

    profile = dict(DEFAULT_PROFILES.get(args.profile, {}))
    if args.custom_profile:
        profile.update(json.loads(Path(args.custom_profile).read_text()))
    profile = {k: min(1.0, v * args.severity) for k, v in profile.items()}

    rng = random.Random(args.seed)
    rows = []
    with open(args.lexicon, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= args.n:
                break
            word, _, phones = line.rstrip("\n").partition("\t")
            if not phones:
                continue
            canonical = phones.split()
            if args.perceptual:
                surface, applied = perceptual_corrupt(canonical, rng)
            else:
                surface, applied = corrupt(canonical, profile, rng)
            if applied:
                rows.append((word, phones, " ".join(surface), ",".join(applied)))

    out = Path(args.out) if args.out else None
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as f:
            for word, canon, surf, proc in rows:
                f.write(f"{word}\t{canon}\t{surf}\t{proc}\n")
    n_proc = sum(1 for r in rows if r[3])
    print(f"{len(rows)} corrupted of {args.n} sampled; output: {out}")
    from collections import Counter
    counts = Counter(p for r in rows for p in r[3].split(","))
    for name, c in counts.most_common():
        print(f"  {name:<30} {c}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
