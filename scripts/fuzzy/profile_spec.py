#!/usr/bin/env python3
"""Profile specification: the swappable corruption model for the fuzzy decoder.

A profile is a data file that describes HOW a person (or population)
corrupts phonemes. It's the key abstraction from the plan:

  canonical phonemes --[profile]--> surface phonemes (expression)
  surface phonemes   --[profile-inverse]--> canonical (decoding)

Profiles ship in the same download/SHA-256 manifest system as lexicon
bundles. Clinicians can author them; researchers can calibrate them
from PhonBank; the corruptor generates training data from them.

Format (JSON):
{
  "name": "english_child_moderate",
  "description": "Typical 4-year-old English speaker",
  "language": "en",
  "population": "children 3;0-5;0",
  "severity": 0.6,
  "source": "calibrated from PhonBank Davis+Providence (CC BY-NC-SA, weights are facts)",
  "processes": {
    "stopping": 0.25,
    "fronting": 0.20,
    "gliding": 0.15,
    "voicing_flip": 0.10,
    "final_consonant_deletion": 0.18,
    "cluster_reduction": 0.30,
    "weak_syllable_deletion": 0.35,
    "regressive_place_assimilation": 0.20,
    "vowel_neutralisation": 0.10
  },
  "perceptual_confusions": {
    "p→t": 0.18,
    "t→k": 0.22
  }
}

Usage:
  python profile_spec.py --list
  python profile_spec.py --show english_child
  python profile_spec.py --validate my-profile.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from corruptor import DEFAULT_PROFILES
from calibrate_phonbank import classify_substitution

# The known process names (must match corruptor.py's PHONE_PROCESSES + SEQ_PROCESSES)
KNOWN_PROCESSES = {
    "stopping", "fronting", "gliding", "voicing_flip",
    "final_consonant_deletion", "cluster_reduction",
    "regressive_place_assimilation", "weak_syllable_deletion",
    "vowel_neutralisation",
}

# Built-in profiles (illustrative + calibrated)
BUILTIN_PROFILES = {
    "english_child": {
        "name": "english_child",
        "description": "Illustrative 4-year-old English speaker (NOT clinically calibrated)",
        "language": "en",
        "population": "children 3;0-5;0",
        "severity": 1.0,
        "source": "illustrative — see profile-calibrated.json for PhonBank-calibrated weights",
        "processes": DEFAULT_PROFILES["english_child"],
    },
    "adult_casual": {
        "name": "adult_casual",
        "description": "Illustrative adult casual speech (Buckeye-style reduction)",
        "language": "en",
        "population": "adults",
        "severity": 1.0,
        "source": "illustrative",
        "processes": DEFAULT_PROFILES["adult_casual"],
    },
    "perceptual": {
        "name": "perceptual",
        "description": "Perceptual mishearing (Miller-Nicely confusions)",
        "language": "any",
        "population": "listeners under noise",
        "severity": 1.0,
        "source": "Miller & Nicely 1955; Wang & Bilger 1973",
        "processes": {},
        "perceptual_confusions": {
            "p→t": 0.18, "t→k": 0.22, "k→p": 0.12,
            "f→θ": 0.30, "s→θ": 0.26, "v→b": 0.15,
        },
    },
}


def validate_profile(data: dict) -> list[str]:
    """Validate a profile JSON. Returns a list of issues (empty = valid)."""
    issues = []
    for field in ("name", "description", "language", "processes"):
        if field not in data:
            issues.append(f"missing required field: {field}")
    if "processes" in data:
        for proc in data["processes"]:
            if proc not in KNOWN_PROCESSES:
                issues.append(f"unknown process: {proc}")
        for proc, rate in data["processes"].items():
            if not isinstance(rate, (int, float)) or not 0 <= rate <= 1:
                issues.append(f"process {proc}: rate must be 0-1, got {rate}")
    if "perceptual_confusions" in data:
        for confusion, rate in data["perceptual_confusions"].items():
            if not isinstance(rate, (int, float)) or not 0 <= rate <= 1:
                issues.append(f"confusion {confusion}: rate must be 0-1, got {rate}")
            if "→" not in confusion:
                issues.append(f"confusion {confusion}: expected format 'from→to'")
    if "severity" in data:
        s = data["severity"]
        if not isinstance(s, (int, float)) or not 0 < s <= 2:
            issues.append(f"severity must be 0-2, got {s}")
    return issues


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--show", help="show a specific profile")
    ap.add_argument("--validate", help="validate a JSON profile file")
    args = ap.parse_args()

    if args.list:
        print("Built-in profiles:")
        for name, profile in BUILTIN_PROFILES.items():
            n_procs = len(profile.get("processes", {}))
            print(f"  {name:<20} {n_procs} processes | {profile['description'][:60]}")
        return 0

    if args.show:
        profile = BUILTIN_PROFILES.get(args.show)
        if not profile:
            print(f"unknown profile: {args.show}")
            return 1
        print(json.dumps(profile, indent=2))
        return 0

    if args.validate:
        data = json.loads(Path(args.validate).read_text())
        issues = validate_profile(data)
        if issues:
            print("INVALID:")
            for issue in issues:
                print(f"  - {issue}")
            return 1
        print("VALID")
        print(f"  {len(data.get('processes', {}))} processes")
        print(f"  severity: {data.get('severity', 1.0)}")
        print(f"  language: {data.get('language', '?')}")
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
