#!/usr/bin/env python3
"""Extract UK/RP and US/GenAm-tagged IPA pairs from the kaikki
(wiktextract) English Wiktionary dump.

Output: word\tUK\tipa\tUS\tipa for words carrying both (28k words).
Feed through floravox-g2p's ipa_seg example before dialect_pairs.py:

  python3 kaikki_dialects.py --dump kaikki-en.jsonl.gz --out ukus.tsv
  awk -F'\\t' '{print $1"\\tUK\\t"$3; print $1"\\tUS\\t"$5}' ukus.tsv \
    | ipa_seg > ukus-seg.tsv
  python3 dialect_pairs.py --pairs ukus-seg.tsv
"""
import argparse
import gzip
import json
import re

UK = {"uk", "british", "received pronunciation", "rp"}
US = {"us", "general american", "american"}


def clean(ipa: str) -> str | None:
    ipa = ipa.strip()
    for a, b in (("/", "/"), ("[", "]")):
        if ipa.startswith(a) and ipa.endswith(b):
            ipa = ipa[1:-1]
    ipa = re.sub(r"\([^)]*\)", "", ipa)
    ipa = re.sub(r"\{\{[^}]*\}\}", "", ipa)
    ipa = ipa.replace(".", "").replace("(", "").replace(")", "").strip()
    if not ipa or len(ipa) < 2 or len(ipa) > 60:
        return None
    if any(c in ipa for c in "<>{}#|_"):
        return None
    return ipa


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    pairs = {}
    with gzip.open(args.dump, "rt", encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            w = e.get("word")
            if not w or not w[0].isalpha() or not e.get("sounds"):
                continue
            wl = w.lower()
            for s in e.get("sounds", []):
                ipa = s.get("ipa")
                if not ipa:
                    continue
                tags = {t.lower().replace("-", " ") for t in s.get("tags", [])}
                cls = "UK" if tags & UK else ("US" if tags & US else None)
                if not cls:
                    continue
                c = clean(ipa)
                if c:
                    pairs.setdefault((wl, cls), c)

    both = sorted({w for (w, _) in pairs
                   if (w, "UK") in pairs and (w, "US") in pairs})
    with open(args.out, "w", encoding="utf-8") as f:
        for w in both:
            f.write(f"{w}\tUK\t{pairs[(w, 'UK')]}\tUS\t{pairs[(w, 'US')]}\n")
    print(f"words with both UK and US IPA: {len(both):,} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
