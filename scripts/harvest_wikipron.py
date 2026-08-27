#!/usr/bin/env python3
"""Harvest WikiPron scraped lexicons into voicegarden staging TSVs.

WikiPron (CUNY-CL/wikipron, CC BY-SA 4.0) publishes per-language TSVs at
data/scrape/tsv/{lang}_{script}_{broad|narrow}.tsv — "word\tIPA". This
script reads the repo summary, selects languages meeting a minimum entry
count, downloads each file, normalises to our lexicon.txt format
(NFC, lowercased word where the language is cased, single pronunciation
per word — first wins), and writes staging/<lang>/wikipron.tsv.

--variants keeps regional/dialectal splits apart: languages with
multiple dialect files (eng-US/eng-UK, por-BR/por-PT, spa-ES/spa-LatAm,
cym-North/cym-South, ...) harvest into variety-keyed dirs instead of
one mixed dir. Variety codes are short readable slugs derived from the
WikiPron dialect field (US, UK, BR, PT, ES, LatAm, ...).

Idempotent + resumable: a language with an existing .done marker is
skipped; --force redoes everything.

Usage:
  scripts/harvest_wikipron.py [--min 1000] [--variants]
                              [--langs a,b,c] [--out staging] [--limit N]
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


# WikiPron dialect field -> short variety slug used in staging dirs and
# corpus tags (kept conservative; unmapped dialects fall back to the
# bare ISO code).
VARIANT_SLUGS = {
    "US, General American": "US",
    "UK, Received Pronunciation": "UK",
    "Brazil": "BR",
    "Portugal": "PT",
    "Castilian, Spain": "ES",
    "Latin America": "LatAm",
    "South Wales": "South",
    "North Wales": "North",
    "Eastern Armenian": "East",
    "Western Armenian": "West",
    "Hokkien": "Hokkien",
    "Teochew": "Teochew",
    "Shanghai": "Shanghai",
    "Rarh, Standard Bengali": "Rarh",
    "Dhaka": "Dhaka",
    "Meixian": "Meixian",
    "Changsha": "Changsha",
    "Taiyuan": "Taiyuan",
    "Jian'ou": "Jianou",
    "Nanchang": "Nanchang",
    "Fuzhou": "Fuzhou",
    "Putian": "Putian",
    "Nanning": "Nanning",
    "Leizhou": "Leizhou",
    "Standard": "",
    "Zhengzhang": "Zhengzhang",
}


def read_summary(min_entries: int, variants: bool):
    """Return (file, dirkey, display, count) for broad-phonemic files.

    dirkey is the staging-dir/corpus tag: bare ISO, or ISO-Slug when
    --variants and the language has multiple dialect files above the
    entry threshold.
    """
    text = fetch(SUMMARY_URL).decode("utf-8")
    per_iso: dict[str, list[tuple[str, str, str, int]]] = {}
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 9 or parts[7] != "Broad":
            continue
        fname, iso, name, dialect = parts[0], parts[1], parts[2], parts[5]
        try:
            count = int(parts[8])
        except ValueError:
            continue
        if count < min_entries:
            continue
        per_iso.setdefault(iso, []).append((fname, name, dialect, count))

    out = []
    for iso, files in per_iso.items():
        if len(files) == 1 or not variants:
            # single variety (or flat mode): keep the largest file only
            fname, name, _d, count = max(files, key=lambda f: f[3])
            out.append((fname, iso, name, count))
            continue
        # Group by dialect: WikiPron ships both raw and _filtered files
        # for big dialects — keep the filtered one (deduped pronunciations).
        by_dialect: dict[str, tuple[str, str, int, bool]] = {}
        for fname, name, dialect, count in files:
            filtered = fname.endswith("_filtered.tsv")
            prev = by_dialect.get(dialect)
            if prev is None or (filtered and not prev[3]):
                by_dialect[dialect] = (fname, name, count, filtered)
        slugs = {}
        for dialect, (fname, name, count, _f) in by_dialect.items():
            slug = VARIANT_SLUGS.get(dialect, "")
            if slug in slugs.values():
                slug = dialect.replace(" ", "-").replace(",", "")[:12]
            slugs[dialect] = slug
            key = iso if not slug else f"{iso}-{slug}"
            out.append((fname, key, f"{name} ({dialect})", count))
    return out


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
    ap.add_argument("--variants", action="store_true",
                    help="keep dialect/region splits as separate dirs+tags")
    ap.add_argument("--langs", help="comma-separated ISO codes to limit to")
    ap.add_argument("--out", default="staging")
    ap.add_argument("--limit", type=int, default=0, help="stop after N languages")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    want = set(filter(None, args.langs.split(","))) if args.langs else None
    staging = Path(args.out)
    staging.mkdir(parents=True, exist_ok=True)

    rows = read_summary(args.min, args.variants)
    rows.sort(key=lambda r: -r[3])  # biggest first — value early
    if want:
        rows = [r for r in rows if r[1] in want or r[1].split("-")[0] in want or r[0] in want]
    if args.limit:
        rows = rows[: args.limit]

    print(f"{len(rows)} languages to harvest (>= {args.min} entries)")
    done = skipped = failed = 0
    for fname, key, name, count in rows:
        out_dir = staging / key
        marker = out_dir / ".wikipron.done"
        if marker.exists() and not args.force:
            skipped += 1
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        bare = key.split("-")[0]
        note = " (gruut-covered: gruut wins conflicts)" if bare in GRUUT_LANGS else ""
        print(f"[{done + 1}/{len(rows)}] {key} {name} (~{count}){note}")
        try:
            kept, _ = harvest_one(fname, key, out_dir)
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
