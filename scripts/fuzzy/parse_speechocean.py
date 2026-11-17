#!/usr/bin/env python3
"""Parse speechocean762 into (observed, canonical) phone pairs.

The corpus has two key files:
  resource/text-phone  — canonical phone transcriptions (ARPABET with
                          positional markers: W_B IY0_E = "WE" with
                          Begin/End markers)
  resource/scores.json — per-utterance, per-word, per-phone accuracy
                          scores (1-10 scale) against the canonical

This script:
1. Loads the canonical phone transcriptions
2. Loads the accuracy scores to identify which phones the speaker
   got wrong (score < 8) vs right (score >= 8)
3. Outputs a TSV: lang\tobserved\tcanonical
   where "observed" is the canonical phones with wrong-scoring phones
   marked, and "canonical" is the clean target

Note: speechocean762 scores tell us WHICH phones were wrong, not what
the speaker actually said (no substituted-phone annotation). For the
fuzzy decoder, the value is:
- Identifying the DISTRIBUTION of error locations (word-final, unstressed,
  clusters, etc.) — calibrates the corruptor's site-selection
- The per-word accuracy provides a severity signal per utterance

For real (observed→canonical) pairs, PhonBank's %phoaln is the gold
source (we already have 3.18M aligned pairs from calibration).

Usage:
  python parse_speechocean.py --dir /path/to/speechocean762 --out speechocean-pairs.tsv
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


def parse_text_phone(path: Path) -> dict[str, list[str]]:
    """Parse canonical phone transcriptions.

    Format: utterance_id.0\tW_B IY0_E  (word boundaries by position markers)
    Multiple words per utterance, one line per word.
    """
    words: dict[str, list[str]] = {}
    for line in path.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        # Split utterance_id.word_index from phones
        utt_key, _, phones = line.partition("\t")
        if not phones:
            continue
        # utt_key format: "000010011.0" (utterance.word_index)
        utt_id = utt_key.split(".")[0]
        word_idx = utt_key.split(".")[1] if "." in utt_key else "0"
        key = f"{utt_id}.{word_idx}"
        words[key] = phones.split()
    return words


def parse_scores(path: Path) -> dict[str, dict]:
    """Load per-utterance accuracy scores."""
    return json.load(path.open(encoding="utf-8"))


def strip_position_markers(phone: str) -> str:
    """Remove _B, _I, _E, _S position markers from ARPABET phones."""
    return re.sub(r"_[BIES]$", "", phone)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", required=True, help="speechocean762 root")
    ap.add_argument("--out", default="speechocean-pairs.tsv")
    ap.add_argument("--threshold", type=int, default=8,
                    help="phone score below this = error (1-10 scale)")
    args = ap.parse_args()

    root = Path(args.dir)
    text_phone = root / "resource" / "text-phone"
    scores_path = root / "resource" / "scores.json"

    if not text_phone.exists():
        print(f"no text-phone at {text_phone}")
        return 1
    if not scores_path.exists():
        print(f"no scores.json at {scores_path}")
        return 1

    canonical_words = parse_text_phone(text_phone)
    scores = parse_scores(scores_path)

    print(f"canonical words: {len(canonical_words)}")
    print(f"scored utterances: {len(scores)}")

    # Analyze error patterns
    total_phones = 0
    error_phones = 0
    error_by_position: Counter = Counter()  # initial, medial, final
    error_by_phone: Counter = Counter()
    word_accuracy_dist: Counter = Counter()  # buckets

    pairs = []
    for utt_id, utt_data in scores.items():
        words = utt_data.get("words", [])
        for word_data in words:
            word_text = word_data.get("text", "").lower()
            phone_scores = word_data.get("phones-accuracy", [])
            canonical_phones = word_data.get("phones", [])

            if not canonical_phones or not phone_scores:
                continue

            total_phones += len(phone_scores)
            word_errors = sum(1 for s in phone_scores if s < args.threshold)
            error_phones += word_errors

            # Word accuracy bucket
            word_acc = word_data.get("accuracy", 10)
            bucket = int(word_acc)
            word_accuracy_dist[bucket] += 1

            # Position analysis
            n = len(phone_scores)
            for i, score in enumerate(phone_scores):
                if score < args.threshold:
                    pos = "initial" if i == 0 else "final" if i == n - 1 else "medial"
                    error_by_position[pos] += 1
                    phone = canonical_phones[i] if i < len(canonical_phones) else "?"
                    error_by_phone[strip_position_markers(phone)] += 1

            # Output pair: phones with errors marked
            clean_phones = [strip_position_markers(p) for p in canonical_phones]
            if word_errors > 0:
                # Mark error phones with * prefix
                observed = []
                for i, (phone, score) in enumerate(
                        zip(canonical_phones, phone_scores)):
                    clean = strip_position_markers(phone)
                    if score < args.threshold:
                        observed.append(f"*{clean}")
                    else:
                        observed.append(clean)
                pairs.append((word_text, " ".join(observed), " ".join(clean_phones)))

    print(f"\nPhone accuracy analysis (threshold={args.threshold}):")
    print(f"  total phones: {total_phones:,}")
    print(f"  error phones: {error_phones:,} ({error_phones/total_phones*100:.1f}%)")

    print(f"\nError by position:")
    for pos, count in error_by_position.most_common():
        print(f"  {pos:<10} {count:>6} ({count/error_phones*100:.1f}%)")

    print(f"\nMost-error-prone phones:")
    for phone, count in error_by_phone.most_common(15):
        print(f"  {phone:<8} {count:>6}")

    print(f"\nWord accuracy distribution:")
    for bucket in sorted(word_accuracy_dist):
        print(f"  score {bucket}: {word_accuracy_dist[bucket]:>6} words")

    # Write pairs
    out = Path(args.out)
    with out.open("w", encoding="utf-8") as f:
        for word, observed, canonical in pairs:
            f.write(f"eng\t{observed}\t{canonical}\n")
    print(f"\n{len(pairs)} error-annotated pairs -> {out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
