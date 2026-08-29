#!/usr/bin/env python3
"""Independent coverage validation: Wikipedia random articles.

Distill candidates came from wordfreq, so top-N coverage is partly by
construction. This measures coverage on text from a different world:
random Wikipedia articles per language (proper nouns, loans, and
infrequent forms included). Per language:

  - fetch ~40 random article extracts
  - tokenize to alphabetic words
  - report the share found in the base lexicon, the share the
    expanded lexicon adds, and the remainder (goes to the WFST tier)

Usage: python3 validate_coverage.py [--n 40]
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.request
from pathlib import Path

REPO = Path("/home/willwade/GitHub/AACTools/voicegarden-lexicons")

# tag -> (staging dir exists check uses tag; wikipedia subdomain, bcp47 for UA string)
WIKI = {"spa-ES": "es", "spa-LatAm": "es", "por-PT": "pt", "deu": "de",
        "pol": "pl", "ita": "it", "fra": "fr", "tur": "tr",
        "ell": "el", "swe": "sv", "eng-US": "en"}
UA = {"User-Agent": "voicegarden-lexicons-coverage/1 (TTS research)"}


def lexicon(tag: str) -> set[str]:
    words = set()
    p = REPO / f"staging/{tag}/merged.tsv"
    for line in p.open(encoding="utf-8"):
        words.add(line.split("\t")[0].strip().lower())
    return words


def distill_words(tag: str) -> set[str]:
    suffix = ".3vote.tsv" if tag in ("eng-US", "ell", "swe") else ".tsv"
    words = set()
    for line in (REPO / f"distill/{tag}{suffix}").open(encoding="utf-8"):
        words.add(line.split("\t")[0].strip().lower())
    return words


def article_batch(lang: str, limit: int = 20) -> list[str]:
    """One MediaWiki API call: up to `limit` random article intros
    (full-article extracts are capped at exlimit=1 by the API)."""
    url = (f"https://{lang}.wikipedia.org/w/api.php?action=query"
           f"&generator=random&grnnamespace=0&grnlimit={limit}"
           f"&prop=extracts&exintro=1&explaintext=1&exlimit={limit}"
           f"&format=json")
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode("utf-8"))
            pages = data.get("query", {}).get("pages", {})
            return [p.get("extract", "") for p in pages.values()
                    if p.get("extract")]
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(10 * (attempt + 1))
            else:
                return []
        except Exception:  # noqa: BLE001
            return []
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40, help="articles per language")
    args = ap.parse_args()

    print(f"{'tag':10} {'articles':>8} {'words':>7} {'base':>7} {'+distill':>9} {'neither':>8}")
    results = {}
    for tag, lang in WIKI.items():
        base = lexicon(tag)
        dist = distill_words(tag)
        text: list[str] = []
        for _ in range(args.n):
            text.extend(article_batch(lang))
            time.sleep(0.5)
        words: set[str] = set()
        for t in text:
            for w in re.findall(r"[^\W\d_]+", t, re.UNICODE):
                if len(w) >= 2:
                    words.add(w.lower())
        if not words:
            print(f"{tag:10} (no articles fetched)")
            continue
        in_base = sum(w in base for w in words)
        in_dist = sum(w in dist and w not in base for w in words)
        neither = len(words) - in_base - in_dist
        n = len(words)
        results[tag] = {"articles": len(text), "words": n,
                        "base": in_base / n, "distill": in_dist / n,
                        "neither": neither / n}
        print(f"{tag:10} {len(text):8d} {n:7d} {in_base/n:7.1%} "
              f"{in_dist/n:9.1%} {neither/n:8.1%}")

    out = REPO / "audit/coverage-wikipedia.json"
    json.dump(results, out.open("w"), indent=1)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
