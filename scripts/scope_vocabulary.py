#!/usr/bin/env python3
"""Scope dictionary coverage against living vocabulary (issue #12 follow-up).

Ranks locales by how much a Common Voice + MFA enrichment campaign could
add, BEFORE any audio is downloaded or aligned: the miss-rate of each
published dictionary against a per-locale Wikipedia text sample (the
closest license-clean proxy for runtime TTS input), next to the locale's
guesser quality (manifest phonetisaurus exact-match) and Common Voice
data availability (recorded hours + sentence count, from the public CV
stats API).

What the numbers mean:
- tok_cov  frequency-weighted dictionary coverage — what a TTS pipeline
  experiences on general text; misses fall through to the guesser.
- typ_cov  coverage over unique word types — the ceiling on new rows an
  alignment campaign could harvest from a corpus of similar breadth.
- miss_types x script purity: a miss set dominated by foreign-script
  tokens (loanwords, names) yields fewer usable alignments than raw
  counts suggest.

Not a gate: a scoping table for docs/data-sources.md. Wikipedia text is
CC BY-SA (sample cached under runs-cv-scope/, gitignored); CV stats are
public metadata. Re-run with --refresh to resample.

Usage: scripts/scope_vocabulary.py [--langs ku,kk,...] [--target-tokens N]
                                  [--refresh] [--json-out PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parent.parent
CACHE = REPO / "runs-cv-scope"
CV_STATS = "https://commonvoice.mozilla.org/api/v1/stats/languages"

# bundle lang -> (wikipedia subdomain, CV locale code). Baselines first:
# hu/ka/de are strong locales the method must score high, or it is broken.
# CV codes: Kurmanji lives under kmr (ckb = Sorani, Arabic script — no
# voice), Irish ga-IE, Norwegian Bokmål nb-NO, Nepali ne-NP.
LOCALES = {
    "hu": ("hu", "hu"),
    "ka": ("ka", "ka"),
    "de": ("de", "de"),
    "ku": ("ku", "kmr"),
    "kk": ("kk", "kk"),
    "lv": ("lv", "lv"),
    "ne": ("ne", "ne-NP"),
    "lb": ("lb", "lb"),
    "no": ("no", "nb-NO"),
    "et": ("et", "et"),
    "sq": ("sq", "sq"),
    "af": ("af", "af"),
    "ga": ("ga", "ga-IE"),
    "tn": ("tn", "tn"),
}

APOSTROPHES = "'`’"
MARK = "M"  # unicodedata category prefix for combining marks


def _word_char(c: str) -> bool:
    r"""Letters, digits, combining marks, underscores and apostrophes.
    `\w` alone would split every word in a script that builds words from
    base + combining marks (Devanagari viramas and vowel signs, Thai,
    Arabic diacritics) into fragments — which is exactly what happened
    to the first Nepali scoping run."""
    return (c.isalnum() or c == "_" or c in APOSTROPHES
            or unicodedata.category(c).startswith(MARK))


def tokenize(text: str) -> Counter:
    """NFC + casefold word types with frequency. Leading/trailing
    apostrophes are stripped; tokens with digits and 1-char tokens are
    dropped (digits are normalised elsewhere; single letters are mostly
    list markers)."""
    text = unicodedata.normalize("NFC", text).casefold()
    counts: Counter = Counter()
    buf: list[str] = []

    def flush() -> None:
        tok = "".join(buf).strip(APOSTROPHES)
        if len(tok) >= 2 and not any(c.isdigit() for c in tok):
            counts[tok] += 1
        buf.clear()

    for c in text:
        if _word_char(c):
            buf.append(c)
        else:
            flush()
    flush()
    return counts




def fetch_json(url: str) -> object:
    req = Request(url, headers={"User-Agent": "voicegarden-lexicons scoping/1.0"})
    with urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def wiki_sample(code: str, target_tokens: int, refresh: bool) -> str:
    """Random-article plaintext extracts until ~target_tokens words."""
    CACHE.mkdir(exist_ok=True)
    cached = CACHE / f"{code}.txt"
    if cached.exists() and not refresh:
        return cached.read_text(encoding="utf-8")
    api = f"https://{code}.wikipedia.org/w/api.php"
    parts: list[str] = []
    n_tokens = 0
    for _ in range(40):  # hard request cap
        url = (f"{api}?action=query&prop=extracts&explaintext&exlimit=max"
               f"&exintro=1&generator=random&grnnamespace=0&grnlimit=12"
               f"&format=json&formatversion=2")
        try:
            data = fetch_json(url)
        except Exception as e:  # noqa: BLE001 - network ops
            print(f"  {code}: wikipedia fetch retry ({e})", file=sys.stderr)
            time.sleep(2.0)
            continue
        for page in data.get("query", {}).get("pages", []):
            parts.append(page.get("extract", ""))
        n_tokens = sum(len(p.split()) for p in parts)
        if n_tokens >= target_tokens:
            break
        time.sleep(0.2)
    text = "\n\n".join(parts)
    cached.write_text(text, encoding="utf-8")
    return text


def dominant_script(tok: str) -> str:
    for ch in tok:
        name = unicodedata.name(ch, "")
        for s in ("LATIN", "CYRILLIC", "DEVANAGARI", "GEORGIAN",
                  "HANGUL", "ARABIC", "GREEK", "HAN"):
            if name.startswith(s):
                return s
    return "?"


def load_dictionary(lang: str) -> set[str]:
    import tarfile

    manifest = json.loads((REPO / "dist/lexicons.json").read_text())
    entry = next((e for e in manifest["languages"] if e["lang"] == lang), None)
    if entry is None:
        return set()  # no bundle yet (tn): every type is a campaign target
    path = REPO / "dist" / entry["file"]
    if not path.exists():
        return set()
    words: set[str] = set()
    with tarfile.open(path) as tar:
        f = tar.extractfile("lexicon.txt")
        for line in f or []:  # type: ignore[union-attr]
            # casefold defensively: the sample is casefolded, and a
            # future cased source bundle must still match
            words.add(line.decode("utf-8").split("\t", 1)[0]
                      .strip().casefold())
    return words


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--langs", help="comma-separated bundle langs to scope")
    ap.add_argument("--target-tokens", type=int, default=30_000)
    ap.add_argument("--refresh", action="store_true",
                    help="refetch the cached wikipedia samples")
    ap.add_argument("--json-out", default="audit/vocabulary-scoping.json")
    args = ap.parse_args()
    selected = args.langs.split(",") if args.langs else list(LOCALES)

    cv_stats: dict[str, dict] = {}
    try:
        for row in fetch_json(CV_STATS):  # type: ignore[assignment]
            cv_stats[row["locale"]] = row
    except Exception as e:  # noqa: BLE001 - metadata, optional
        print(f"warning: CV stats unavailable ({e})", file=sys.stderr)

    manifest = json.loads((REPO / "dist/lexicons.json").read_text())
    per_lang = {e["lang"]: e for e in manifest["languages"]}

    results = []
    for lang in selected:
        wiki_code, cv_code = LOCALES[lang]
        sample = wiki_sample(wiki_code, args.target_tokens, args.refresh)
        counts = tokenize(sample)
        dictionary = load_dictionary(lang)
        if not counts:
            print(f"{lang}: empty sample, skipped", file=sys.stderr)
            continue
        hits = {t: n for t, n in counts.items() if t in dictionary}
        miss = {t: n for t, n in counts.items() if t not in dictionary}
        tok_cov = sum(hits.values()) / max(sum(counts.values()), 1)
        typ_cov = len(hits) / max(len(counts), 1)
        # effective coverage: dictionary hits + the share of misses the
        # per-bundle guesser pronounces exactly right on holdout. An
        # ESTIMATE — holdout words are dictionary-like, runtime misses
        # (names, inflections) are harder — but it ranks the real
        # exposure: a weak guesser under a low tok_cov is the crisis.
        eff = None
        if ph_est := (per_lang.get(lang, {}).get("phonetisaurus") or {}).get(
                "exact_match"):
            eff = tok_cov + (1 - tok_cov) * ph_est
        dom = Counter(dominant_script(t) for t in counts)
        dom_script, dom_n = dom.most_common(1)[0]
        miss_native = sum(1 for t in miss if dominant_script(t) == dom_script)
        cv = cv_stats.get(cv_code, {})
        ph = (per_lang.get(lang, {}).get("phonetisaurus") or {})
        results.append({
            "lang": lang,
            "sample_tokens": sum(counts.values()),
            "wiki_types": len(counts),
            "tok_cov": round(tok_cov, 4),
            "typ_cov": round(typ_cov, 4),
            "est_eff_cov": None if eff is None else round(eff, 4),
            "miss_types": len(miss),
            "miss_native": miss_native,
            "dom_script": dom_script,
            "script_purity": round(dom_n / len(counts), 3),
            "top_miss": [t for t, _ in Counter(miss).most_common(8)],
            "dict_entries": per_lang.get(lang, {}).get("entries"),
            "g2p_exact": ph.get("exact_match"),
            "cv_recorded_hours": cv.get("recordedHours"),
            "cv_validated_hours": cv.get("validatedHours"),
            "cv_sentences": (cv.get("sentencesCount") or {}).get("currentCount"),
        })

    results.sort(key=lambda r: (r["est_eff_cov"] is not None,
                                r["est_eff_cov"] or 0, r["lang"]))
    hdr = (f"{'lang':<5} {'tok_cov':>7} {'est_eff':>7} {'typ_cov':>7} "
           f"{'miss_typ':>8} {'native':>6} {'dict':>8} {'g2p':>5} "
           f"{'cv_val_h':>8} {'cv_sent':>7}")
    print(hdr)
    print("-" * len(hdr))
    for r in results:
        eff_s = f"{r['est_eff_cov']:.0%}" if r["est_eff_cov"] is not None else "—"
        g2p = f"{r['g2p_exact']:.0%}" if r["g2p_exact"] is not None else "—"
        cvh = str(r["cv_validated_hours"] or "—")
        cvs = str(r["cv_sentences"] or "—")
        entries = f"{r['dict_entries']:,}" if r["dict_entries"] else "—"
        print(f"{r['lang']:<5} {r['tok_cov']:>7.1%} {eff_s:>7} "
              f"{r['typ_cov']:>7.1%} "
              f"{r['miss_types']:>8} {r['miss_native']:>6} "
              f"{entries:>8} {g2p:>5} {cvh:>8} {cvs:>7}")
    for r in results:
        print(f"  {r['lang']}: top misses: {' '.join(r['top_miss'])}")

    out = REPO / args.json_out
    out.write_text(json.dumps(results, indent=1, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"\n{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
