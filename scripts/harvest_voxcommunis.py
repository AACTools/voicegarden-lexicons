#!/usr/bin/env python3
"""Harvest word→phone pairs from VoxCommunis TextGrids (CC0).

VoxCommunis (pacscilab/VoxCommunis, CC0-1.0) publishes MFA word+phone
alignments of Common Voice's validated splits. This script turns a set
of TextGrids into a lexicon TSV with the campaign's confidence gate:

- per word, pronunciations are collected across every clip, then
  majority-voted: a pronunciation ships only when it wins >= --min-votes
  alignments AND holds >= --min-ratio of that word's aligned instances
  (repeated coverage across speakers is the alignment-world equivalent
  of a second annotator);
- words with digits/punctuation, empty or `spn`-bearing phone spans are
  dropped; words are NFC + casefolded to staging conventions;
- phones are kept verbatim — convention folds to the target voice's
  inventory happen in the existing fold_* scripts / staging step.

Provenance note: the audio behind these grids is Common Voice (CC0 for
versions <= 20); grids carry VoxCommunis' own CC0-1.0 mark. Rows derived
here license-label as CC0 in the bundle NOTICE.

Usage: scripts/harvest_voxcommunis.py --grid-dir runs-cv-scope/voxcommunis/kmr \
       --out staging/kur/voxcommunis.tsv [--min-votes 3] [--min-ratio 0.6]
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

# Praat long-format interval blocks; tolerant of trailing spaces
TIER_RE = re.compile(
    r'class = "IntervalTier"\s*\n\s*name = "([^"]+)"')
INTERVAL_RE = re.compile(
    r"intervals \[(\d+)\]:\s*\n\s*xmin = ([\d.e+-]+)\s*\n"
    r"\s*xmax = ([\d.e+-]+)\s*\n\s*text = \"((?:[^\"]|\"\")*)\"")
BAD_PHONES = {"spn", "sil", "sp", "<unk>", "laugh", "noise"}
WORD_OK = re.compile(r"^[\w'’-]+$", re.UNICODE)


def phone_plausible(token: str) -> bool:
    """Phones are short: base letters/digits + combining marks, <=3 base
    chars. Catches G2P failure artifacts where whole grapheme words leak
    into the phone stream (e.g. 'cilvēks' as a single 'phone')."""
    base = [c for c in token if unicodedata.category(c)[0] != "M"]
    return 0 < len(base) <= 3


def parse_textgrid(path: Path) -> list[dict]:
    """Return [{'words': [(t0,t1,txt)...], 'phones': [...]}] per tier."""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    tiers: list[dict] = []
    for m in TIER_RE.finditer(text):
        name = m.group(1)
        body = text[m.end():]
        nxt = TIER_RE.search(body)
        if nxt:
            body = body[:nxt.start()]
        intervals = [
            (float(a), float(b), t.replace('""', '"'))
            for _n, a, b, t in INTERVAL_RE.findall(body)
        ]
        tiers.append({"name": name, "intervals": intervals})
    return tiers


def harvest(grid_dir: Path) -> tuple[Counter, int]:
    """(word -> Counter[pron], files parsed)."""
    counts: dict[str, Counter] = {}
    files = grid_dir.rglob("*.TextGrid")
    n = 0
    for path in files:
        n += 1
        tiers = parse_textgrid(path)
        by_name = {t["name"]: t["intervals"] for t in tiers}
        words = by_name.get("words") or by_name.get("word")
        phones = by_name.get("phones") or by_name.get("phone")
        if not words or not phones:
            continue
        for w0, w1, wtext in words:
            wtext = unicodedata.normalize("NFC", wtext).strip().casefold()
            if not wtext or not WORD_OK.match(wtext) or len(wtext) < 1 \
                    or any(c.isdigit() for c in wtext):
                continue
            span = [(p0, p1, pt) for p0, p1, pt in phones
                    if (p0 + p1) / 2 >= w0 and (p0 + p1) / 2 <= w1
                    and pt.strip()]
            if not span or any(pt.strip() in BAD_PHONES for _x, _y, pt in span) \
                    or any(not phone_plausible(pt.strip()) for _x, _y, pt in span):
                counts.setdefault(wtext, Counter())["<bad>"] += 1
                continue
            pron = " ".join(pt.strip() for _x, _y, pt in span)
            counts.setdefault(wtext, Counter())[pron] += 1
    flat: Counter = Counter()
    for w, prons in counts.items():
        for pron, c in prons.items():
            flat[(w, pron)] = c
    return flat, n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--grid-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--min-votes", type=int, default=3)
    ap.add_argument("--min-ratio", type=float, default=0.6)
    args = ap.parse_args()

    pair_counts, n_files = harvest(args.grid_dir)
    if not pair_counts:
        print("no pairs harvested", file=sys.stderr)
        return 1
    words = Counter()
    for (w, pron), c in pair_counts.items():
        words[w] += c

    kept: list[tuple[str, str, int]] = []
    rejected_ratio = rejected_votes = 0
    for w, total in words.items():
        bad = pair_counts.get((w, "<bad>"), 0)
        prons = Counter({p: c for (ww, p), c in pair_counts.items()
                         if ww == w and p != "<bad>"})
        if not prons:
            continue
        pron, votes = prons.most_common(1)[0]
        denom = total - bad
        if votes < args.min_votes:
            rejected_votes += 1
            continue
        if votes / max(denom, 1) < args.min_ratio:
            rejected_ratio += 1
            continue
        kept.append((w, pron, votes))

    kept.sort(key=lambda r: (-r[2], r[0]))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for w, pron, votes in sorted(kept):
            f.write(f"{w}\t{pron}\n")

    amb = sum(1 for w in words if len({p for (ww, p), _ in
              pair_counts.items() if ww == w and p != "<bad>"}) > 1)
    print(f"files={n_files}  instances={sum(words.values()):,}  "
          f"distinct words={len(words):,} (ambiguous {amb:,})")
    print(f"kept {len(kept):,} rows "
          f"(min {args.min_votes} votes, {args.min_ratio:.0%} majority); "
          f"rejected: {rejected_votes:,} low-vote, "
          f"{rejected_ratio:,} low-ratio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
