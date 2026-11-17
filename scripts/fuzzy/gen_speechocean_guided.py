#!/usr/bin/env python3
"""Generate (guided-corrupted -> canonical) training pairs from speechocean762.

Why "guided": speechocean762's annotations tell us WHICH phones expert
annotators judged wrong and how badly (phones-accuracy, 0-2 scale where
2.0 = correct) — but NOT what was actually said. The earlier
parse_speechocean.py run was doubly broken: it applied a <8 threshold to
a 0-2 scale (marking every phone an error) and emitted canonical phones
in both columns (identity pairs, useless for fine-tuning).

This generator keeps what is real — the error SITES, their severity,
their position in the word, and the speaker population (Mandarin-L1
English learners, half children) — and supplies the surface realization
ourselves: a severity-banded corruption applied at exactly the annotated
sites, using the same feature-based operators as the synthetic corpus
(processes.py). Real error topology, synthetic realizations.

Severity bands (phones-accuracy):
  hard  s <= 0.8   deletion or feature substitution
  mild  1.0-1.6    vowel reduction / voicing / slight quality shift
  near  1.8        stress-mark change only

Output format matches the fuzzy corpus: lang<TAB>observed<TAB>canonical,
phones space-separated IPA, stress as Unicode ˈ/ˌ on the vowel.

Speaker-disjoint test split (utterance id embeds the speaker: utt
007650174 -> speaker 0765): held-out speakers' words never appear in
train. License: speechocean762 is CC BY 4.0 — safe to train and ship.

Usage:
  python gen_speechocean_guided.py --dir /path/speechocean762 \
      --out-dir speechocean-guided [--samples-per-word 2]
"""

from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent))
from processes import (  # noqa: E402
    is_vowel, stopping, fronting, gliding, voicing_flip,
)

# ARPAbet -> IPA (vowels carry stress digits in ARPAbet: AH0/AH1/AH2)
ARPABET_IPA = {
    "AA": "ɑ", "AE": "æ", "AH": "ʌ", "AO": "ɔ", "AW": "aʊ", "AY": "aɪ",
    "B": "b", "CH": "t͡ʃ", "D": "d", "DH": "ð", "EH": "e", "ER": "ɚ",
    "EY": "eɪ", "F": "f", "G": "ɡ", "HH": "h", "IH": "ɪ", "IY": "i",
    "JH": "d͡ʒ", "K": "k", "L": "l", "M": "m", "N": "n", "NG": "ŋ",
    "OW": "oʊ", "OY": "ɔɪ", "P": "p", "R": "ɹ", "S": "s", "SH": "ʃ",
    "T": "t", "TH": "θ", "UH": "ʊ", "UW": "u", "V": "v", "W": "w",
    "Y": "j", "Z": "z", "ZH": "ʒ",
}


def arpa_to_ipa(tokens: list[str]) -> list[str] | None:
    """['W','IY1'] -> ['w','ˈi']; returns None on unknown symbols."""
    out = []
    for tok in tokens:
        m = re.match(r"^([A-Z]+?)([0-2])?$", tok)
        if not m:
            return None
        base, stress = m.group(1), m.group(2)
        if base not in ARPABET_IPA:
            return None
        ipa = ARPABET_IPA[base]
        if stress == "1":
            out.append("ˈ" + ipa)
        elif stress == "2":
            out.append("ˌ" + ipa)
        else:
            out.append(ipa)
    return out


def strip_stress(ph: str) -> str:
    return ph.lstrip("ˈˌ")


def has_stress(ph: str) -> bool:
    return ph[0] in "ˈˌ" if ph else False


def substitute_site(ph: str, rng: random.Random) -> str | None:
    """Feature-based substitution of a single phone; None if no operator applies."""
    base = strip_stress(ph)
    ops = [op for op in (stopping, fronting, gliding, voicing_flip)
           if op(base) is not None]
    if not ops:
        return None
    new = rng.choice(ops)(base)
    return ("ˈ" if has_stress(ph) and new[0] not in "ˈˌ" else "") + new


def corrupt_site(phones: list[str], i: int, score: float,
                 rng: random.Random) -> list[str]:
    """Apply a severity-banded corruption at exactly site i."""
    ph = phones[i]
    base = strip_stress(ph)
    if score <= 0.8:  # hard
        is_final = i == len(phones) - 1
        if is_vowel(base) and not has_stress(ph) and rng.random() < 0.5:
            return phones[:i] + phones[i + 1:]          # unstressed vowel drop
        if is_final and not is_vowel(base) and rng.random() < 0.5:
            return phones[:i] + phones[i + 1:]          # final C deletion
        sub = substitute_site(ph, rng)
        if sub is not None:
            return phones[:i] + [sub] + phones[i + 1:]
        return phones[:i] + phones[i + 1:]              # fallback: drop
    if score <= 1.6:  # mild
        if is_vowel(base):
            red = "ə" if not has_stress(ph) else "ɐ"
            mark = "ˈ" if has_stress(ph) else ""
            return phones[:i] + [mark + red] + phones[i + 1:]
        sub = voicing_flip(base)
        if sub is not None:
            return phones[:i] + [sub] + phones[i + 1:]
        return phones
    # near (1.8): stress-mark change only
    if has_stress(ph):
        return phones[:i] + [strip_stress(ph)] + phones[i + 1:]
    if is_vowel(base) and i < len(phones) - 1 and rng.random() < 0.5:
        return phones[:i] + ["ˈ" + base] + phones[i + 1:]
    return phones


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", required=True, help="speechocean762 root")
    ap.add_argument("--out-dir", default="speechocean-guided")
    ap.add_argument("--samples-per-word", type=int, default=2,
                    help="independent corruptions per errored word")
    ap.add_argument("--identity-rate", type=float, default=0.5,
                    help="fraction of error-free words kept as pass-through pairs")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--test-speaker-frac", type=float, default=0.1)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    scores = json.load(open(Path(args.dir) / "resource" / "scores.json",
                            encoding="utf-8"))

    # collect words grouped by speaker
    by_speaker: dict[str, list[dict]] = {}
    for utt_id, u in scores.items():
        speaker = utt_id[3:7]  # 007650174 -> 0765
        for w in u.get("words", []):
            acc = w.get("phones-accuracy", [])
            if not acc or not w.get("phones"):
                continue
            by_speaker.setdefault(speaker, []).append({
                "phones": w["phones"], "acc": acc,
            })

    speakers = sorted(by_speaker)
    rng.shuffle(speakers)
    n_test = max(1, int(len(speakers) * args.test_speaker_frac))
    test_speakers = set(speakers[:n_test])

    train_pairs, test_pairs = [], []
    stats = Counter()
    for speaker, words in by_speaker.items():
        bucket = test_pairs if speaker in test_speakers else train_pairs
        for w in words:
            ipa = arpa_to_ipa(w["phones"])
            if ipa is None:
                stats["unmapped"] += 1
                continue
            err_sites = [i for i, s in enumerate(w["acc"]) if s < 2.0]
            if not err_sites:
                if rng.random() < args.identity_rate:
                    bucket.append((ipa, ipa))
                    stats["identity"] += 1
                continue
            # test split: one deterministic corruption (seed from content)
            if bucket is test_pairs:
                r2 = random.Random(hash((speaker, tuple(w["phones"]))) & 0xFFFF)
                corrupted = ipa
                for i in sorted(err_sites, reverse=True):
                    corrupted = corrupt_site(corrupted, i, w["acc"][i], r2)
                if corrupted != ipa:
                    test_pairs.append((corrupted, ipa))
                    stats["test"] += 1
                continue
            for s_i in range(args.samples_per_word):
                corrupted = ipa
                # right-to-left: deletions at higher indices never shift
                # the positions of the remaining annotated sites
                for i in sorted(err_sites, reverse=True):
                    corrupted = corrupt_site(corrupted, i, w["acc"][i], rng)
                if corrupted != ipa:
                    train_pairs.append((corrupted, ipa))
                    stats["train"] += 1

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rng.shuffle(train_pairs)
    n_val = max(1, len(train_pairs) // 20)
    splits = {
        "g2p.train.tsv": train_pairs[n_val:],
        "g2p.val.tsv": train_pairs[:n_val],
        "g2p.test.tsv": test_pairs,
    }
    for name, rows in splits.items():
        with (out / name).open("w", encoding="utf-8") as f:
            for observed, canonical in rows:
                f.write(f"eng\t{' '.join(observed)}\t{' '.join(canonical)}\n")
        print(f"{name}: {len(rows):,} rows")

    print(f"\nstats: {dict(stats)}")
    print(f"speakers: {len(speakers)} total, {len(test_speakers)} held out")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
