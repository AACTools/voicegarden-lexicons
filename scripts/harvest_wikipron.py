#!/usr/bin/env python3
"""Harvest WikiPron scraped lexicons into voicegarden staging TSVs.

WikiPron (CUNY-CL/wikipron, CC BY-SA 4.0) publishes per-language TSVs at
data/scrape/tsv/{lang}_{script}_{broad|narrow}.tsv — "word\tIPA". This
script reads the repo summary, selects languages meeting a minimum entry
count, downloads each file, normalises to our lexicon.txt format
(NFC, lowercased word where the language is cased, single pronunciation
per word — first wins), and writes staging/<lang>/wikipron.tsv.

Idempotent + resumable: a language with an existing .done marker is
skipped; --force redoes everything.

Usage:
  scripts/harvest_wikipron.py [--min 1000] [--broad] [--langs a,b,c]
                              [--out staging] [--limit N]
"""

from __future__ import annotations

import argparse
import sys
import time
import unicodedata
import urllib.request
from pathlib import Path

SUMMARY_URL = (
    "https://raw.githubusercontent.com/CUNY-CL/wikipron/master/"
    "data/scrape/summary.tsv"
)
RAW_URL = (
    "https://raw.githubusercontent.com/CUNY-CL/wikipron/master/"
    "data/scrape/tsv/{file}"
)

# gruut already covers these better (segmented, stress-marked, larger):
# WikiPron is still merged for them, but flagged so the merge step can
# prefer gruut on conflicts.
GRUUT_LANGS = {
    "ca", "cs", "de", "en", "es", "fa", "fr", "it", "nl", "pt", "ru",
    "sv", "sw",
}


def fetch(url: str, retries: int = 3) -> bytes:
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 - network ops
            if attempt == retries - 1:
                raise
            print(f"  retry {url}: {e}", file=sys.stderr)
            time.sleep(2.0 * (attempt + 1))
    raise AssertionError("unreachable")


def read_summary(min_entries: int) -> list[tuple[str, str, str, int]]:
    """Return (file, iso, name, count) for broad-phonemic files."""
    text = fetch(SUMMARY_URL).decode("utf-8")
    out: dict[tuple[str, str], tuple[str, str, int]] = {}
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 9 or parts[7] != "Broad":
            continue
        fname, iso, name = parts[0], parts[1], parts[2]
        try:
            count = int(parts[8])
        except ValueError:
            continue
        if count < min_entries:
            continue
        key = (iso, name)
        if key not in out or count > out[key][2]:
            out[key] = (fname, name, count)
    return [(f, iso, name, c) for (iso, name), (f, name2, c) in out.items()]


def normalise(word: str) -> str:
    w = unicodedata.normalize("NFC", word).strip()
    return w.lower() if w.isascii() or w[:1].isupper() else w


def harvest_one(fname: str, iso: str, out_dir: Path) -> tuple[int, Path]:
    raw = fetch(RAW_URL.format(file=fname)).decode("utf-8")
    tsv = out_dir / "wikipron.tsv"
    seen: set[str] = set()
    kept = 0
    with tsv.open("w", encoding="utf-8") as f:
        for line in raw.splitlines():
            word, _, pron = line.partition("\t")
            word = normalise(word)
            pron = unicodedata.normalize("NFC", pron).strip()
            if not word or not pron or word in seen:
                continue
            seen.add(word)
            f.write(f"{word}\t{pron}\n")
            kept += 1
    return kept, tsv


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--min", type=int, default=1000)
    ap.add_argument("--langs", help="comma-separated ISO codes to limit to")
    ap.add_argument("--out", default="staging")
    ap.add_argument("--limit", type=int, default=0, help="stop after N languages")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    want = set(filter(None, args.langs.split(","))) if args.langs else None
    staging = Path(args.out)
    staging.mkdir(parents=True, exist_ok=True)

    rows = read_summary(args.min)
    rows.sort(key=lambda r: -r[3])  # biggest first — value early
    if want:
        rows = [r for r in rows if r[0] in want or r[1] in want]
    if args.limit:
        rows = rows[: args.limit]

    print(f"{len(rows)} languages to harvest (>= {args.min} entries)")
    done = skipped = failed = 0
    for fname, iso, name, count in rows:
        out_dir = staging / iso
        marker = out_dir / ".wikipron.done"
        if marker.exists() and not args.force:
            skipped += 1
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        note = " (gruut-covered: gruut wins conflicts)" if iso in GRUUT_LANGS else ""
        print(f"[{done + 1}/{len(rows)}] {iso} {name} (~{count}){note}")
        try:
            kept, _ = harvest_one(fname, iso, out_dir)
        except Exception as e:  # noqa: BLE001 - keep the loop alive
            print(f"  FAILED: {e}", file=sys.stderr)
            failed += 1
            continue
        (out_dir / "LICENSE.wikipron").write_text(
            "WikiPron data: CC BY-SA 4.0, https://github.com/CUNY-CL/wikipron\n"
            f"Source file: data/scrape/tsv/{fname}\n",
            encoding="utf-8",
        )
        marker.write_text(fname + "\n")
        print(f"  kept {kept} unique words -> {out_dir}/wikipron.tsv")
        done += 1
        time.sleep(0.5)  # be a good citizen

    print(
        f"harvested {done}, skipped {skipped}, failed {failed} "
        f"(staging under {staging}/)"
    )
    return 1 if failed and not done else 0


if __name__ == "__main__":
    raise SystemExit(main())
