#!/usr/bin/env python3
"""Harvest kaikki.org (Wiktionary extraction) dumps into voicegarden staging TSVs.

kaikki.org publishes full JSONL extractions of the English Wiktionary
(CC BY-SA 4.0 via Wiktionary, same licensing chain as WikiPron). Unlike
WikiPron's filtered broad scrape, kaikki retains inflected forms —
exactly the paradigm coverage the P2G direction lacks on heavily
inflected languages (isl p2g exact 7.8%, swe 6.7%, fin 15.9%).

This script reads a downloaded `*.jsonl` dump, extracts word -> IPA
pairs (first IPA per word, first wins on repeats), normalises to the
staging corpus conventions (NFC, phonemic brackets and stress/syllable
marks stripped — matching the WikiPron-broad harvest), and writes
staging/<lang>/kaikki.tsv.

kaikki is used as a FILL source: words the wikipron.tsv already covers
keep their WikiPron transcription (single convention per language);
merge_sources.py unions kaikki in behind wikipron.

Usage:
  scripts/harvest_kaikki.py --lang Icelandic --iso isl [--dump path]

Dumps: https://kaikki.org/dictionary/<Language>/kaikki.org-dictionary-<Language>.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

# bracket + stress + syllable-boundary marks to strip (keeps length ː,
# tie bars, and every segmental diacritic — the corpus conventions)
STRIP = re.compile(r"[/\[\]ˈˌ.\| ‖]")
PARENS = re.compile(r"[()]")
ATTACH_LM = set("ːˑʰʲʷˠˀˁⁿ")
TIE = "͡"


def segment(ipa: str) -> str:
    """Unsegmented IPA -> space-separated phone units (base char +
    combining marks + attached modifier letters; tie bars join the
    next base char so affricates stay whole)."""
    units: list[str] = []
    tie_pending = False
    for ch in ipa:
        if ch == " ":
            tie_pending = False
            continue
        cat = unicodedata.category(ch)
        attached = bool(units) and (cat in ("Mn", "Mc", "Me") or ch in ATTACH_LM)
        if tie_pending and units and not attached:
            units[-1] += ch
            tie_pending = False
            continue
        if ch == TIE:
            if units:
                units[-1] += ch
            tie_pending = True
            continue
        if attached:
            units[-1] += ch
        else:
            units.append(ch)
    return " ".join(units)

LICENCE = (
    "kaikki.org extraction of the English Wiktionary\n"
    "https://kaikki.org/dictionary/ — CC BY-SA 4.0,\n"
    "(c) Wiktionary contributors. Same grant as the WikiPron scrape\n"
    "(WikiPron is a filtered scrape of the same source).\n"
)


def normalise_ipa(raw: str) -> str:
    ipa = PARENS.sub("", STRIP.sub(" ", raw)).split()
    return " ".join(segment(tok) for tok in ipa)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lang", required=True, help="kaikki language page name (e.g. Icelandic)")
    ap.add_argument("--iso", required=True, help="staging dir / ISO 639-3 (e.g. isl)")
    ap.add_argument("--dump", help="path to the .jsonl (default /tmp/opencode/kaikki/<lang>.jsonl)")
    ap.add_argument("--staging", default="staging")
    ap.add_argument("--limit-words", type=int, default=0)
    args = ap.parse_args()

    dump = Path(args.dump) if args.dump else Path(f"/tmp/opencode/kaikki/{args.lang}.jsonl")
    if not dump.is_file():
        raise SystemExit(f"dump not found: {dump}")

    out_dir = Path(args.staging) / args.iso
    out_dir.mkdir(parents=True, exist_ok=True)
    tsv = out_dir / "kaikki.tsv"

    seen: set[str] = set()
    n_lines = n_words = 0
    with tsv.open("w", encoding="utf-8") as out:
        with dump.open(encoding="utf-8") as f:
            for line in f:
                n_lines += 1
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                word = entry.get("word")
                if not word:
                    continue
                word = unicodedata.normalize("NFC", word.strip())
                if not word or word in seen:
                    continue
                sounds = entry.get("sounds") or []
                ipa = next((s.get("ipa") for s in sounds if s.get("ipa")), None)
                if not ipa:
                    continue
                pron = normalise_ipa(ipa)
                if not pron:
                    continue
                seen.add(word)
                out.write(f"{word}\t{pron}\n")
                n_words += 1
                if args.limit_words and n_words >= args.limit_words:
                    break

    (out_dir / "LICENSE.kaikki").write_text(LICENCE, encoding="utf-8")
    print(f"{args.lang}: {n_words} words with IPA from {n_lines} entries -> {tsv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
