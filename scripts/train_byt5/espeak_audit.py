#!/usr/bin/env python3
"""espeak-ng quality on our held-out test split (the owed head-to-head).

Same 200-word sample as distill_audit.py (seed 42). espeak's IPA
conventions differ from the corpus (ɐ for reduced vowels, ɒ, ɔː,
tie-bar diphthongs), so three scorings:
  raw    token exact match
  fold   joined strings, strip length/tie diacritics, ɒ→ɑ ɛ→e ɐ→ə
  foldW  fold + ɐ treated as matching æ OR ə (espeak merges them;
         counted correct if either global substitution matches)

Usage: espeak_audit.py --lang eng --voice en-us --n 200
"""
from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
from pathlib import Path

REPO = Path("/home/willwade/GitHub/AACTools/voicegarden-lexicons")

STRIP = "ː:͡ʲ"  # length/tie; stress marks KEPT (they are scored)


def load_test(tag: str) -> list[tuple[str, str]]:
    rows = []
    for line in open(REPO / "corpus/g2p.test.tsv", encoding="utf-8"):
        parts = line.rstrip("\n").split("\t")
        if len(parts) != 3 or parts[0] != tag:
            continue
        if re.fullmatch(r"[^\W\d_]{2,}", parts[1], re.UNICODE):
            rows.append((parts[1], parts[2]))
    return rows


def fold(s: str, a_sub: str) -> str:
    s = s.translate(str.maketrans({"ɒ": "ɑ", "ɛ": "e", "ɐ": a_sub}))
    s = "".join(c for c in s if c not in STRIP)
    return "".join(s.split())


def espeak_word(voice: str, w: str) -> str:
    r = subprocess.run(
        ["espeak-ng", "-q", "--ipa", "--sep= ", "-v", voice, w],
        capture_output=True, text=True,
    )
    return r.stdout.strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", required=True)
    ap.add_argument("--voice", required=True)
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rows = load_test(args.lang)
    random.seed(args.seed)
    random.shuffle(rows)
    rows = rows[: args.n]

    n = raw = fold_hits = wild_hits = 0
    for word, truth in rows:
        got = espeak_word(args.voice, word)
        if not got:
            continue
        n += 1
        raw += got == truth
        f_truth = fold(truth, "ɐ")
        f_got = fold(got, "ɐ")
        fold_hits += f_got == f_truth
        wild_hits += (fold(got, "æ") == fold(truth, "æ")
                      or fold(got, "ə") == fold(truth, "ə"))

    out = {
        "lang": args.lang, "voice": args.voice, "n": n,
        "exact_raw": round(raw / max(n, 1), 3),
        "exact_folded": round(fold_hits / max(n, 1), 3),
        "exact_folded_wildcard": round(wild_hits / max(n, 1), 3),
    }
    json.dump(out, open(REPO / "audit" / f"{args.lang}.espeak.json", "w"), indent=1)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
