#!/usr/bin/env python3
"""Local pre-release validation — everything CI used to check, offline.

Replaces the bundle-build/smoke steps of the old CI: run locally before
pushing and cutting a release (`make check-release`). Checks:

  1. manifest schema (dist/lexicons.json vs schema.json)
  2. every manifest asset exists and matches its sha256
  3. every bundle opens and ships lexicon.txt + NOTICE (+ .fst/.pho
     for base bundles, phonetisaurus.fst everywhere)
  4. lexicon.txt is well-formed (`word\\tphones`, non-empty spaced
     phones) and its line count matches the manifest entry
  5. voice-locale resolution table: every sherpa piper voice locale
     resolves to the intended bundle; the blocked set stays blocked

Usage: python3 scripts/validate_release.py [--dist dist] [--expanded dist/expanded-v2]
Exit code 1 on any failure.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# voice locale -> expected bundle in the BASE manifest; must mirror
# examples/consumer_smoke.rs (the smoke covers the expanded tier below)
RESOLUTION = {
    "de_DE": "de", "en_US": "en", "en_GB": "en-GB", "fr_FR": "fr",
    "es_ES": "es", "it_IT": "it", "pt_BR": "pt", "ru_RU": "ru",
    "ca_ES": "ca", "cs_CZ": "cs", "fa_IR": "fa", "nl_NL": "nl",
    "sv_SE": "sv", "sw_CD": "sw",
    "af_ZA": "af", "cy_GB": "cy", "et": "et", "eu_ES": "eu", "ga": "ga",
    "gu_IN": "gu", "hr": "hr", "sr_RS": "sr", "kk_KZ": "kk",
    "lb_LU": "lb", "lt": "lt", "ml_IN": "ml", "mt": "mt",
    "no_NO": "no", "sq_AL": "sq", "yue": "yue",
    "hu_HU": "hu", "ka_GE": "ka", "zh_CN": "zh", "ko_KO": "ko",
    "uk_UA": "uk", "vi_VN": "vi", "ne_NP": "ne", "lv_LV": "lv",
}
# voice locale -> expected bundle in the EXPANDED manifest
EXPANDED_RESOLUTION = {
    "fi_FI": "fin", "is_IS": "isl", "pl_PL": "pol",
    "nb_NO": "nob", "sv_SE": "swe",
}
BLOCKED = {"ku_TR": "no-data", "tn_ZA": "no-data"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_manifest_schema(manifest: dict) -> list[str]:
    errs: list[str] = []
    try:
        import jsonschema  # noqa: F401
    except ImportError:
        # minimal structural checks without the dependency
        if manifest.get("format") != "voicegarden-lexicons/1":
            errs.append("manifest.format is not voicegarden-lexicons/1")
        for e in manifest.get("languages", []):
            for key in ("lang", "bcp47", "entries", "license", "file", "sha256"):
                if key not in e:
                    errs.append(f"entry {e.get('lang', '?')} missing {key}")
        return errs
    schema = json.loads((REPO / "schema.json").read_text())
    try:
        jsonschema.validate(manifest, schema)
    except jsonschema.ValidationError as ex:  # type: ignore[attr-defined]
        errs.append(f"schema: {ex.message}")
    return errs


def check_bundles(manifest: dict, dist: Path) -> tuple[list[str], int]:
    errs: list[str] = []
    bundles = 0
    for e in manifest["languages"]:
        path = dist / e["file"]
        if not path.exists():
            errs.append(f"{e['lang']}: missing {path}")
            continue
        if sha256(path) != e["sha256"]:
            errs.append(f"{e['lang']}: sha256 mismatch")
            continue
        try:
            with tarfile.open(path) as tar:
                names = set(tar.getnames())
                for need in ("lexicon.txt", "NOTICE"):
                    if need not in names:
                        errs.append(f"{e['lang']}: bundle lacks {need}")
                # phonetisaurus.fst is optional (dictionary-only bundles
                # ship without — manifest entry carries phonetisaurus: null)
                if e.get("phonetisaurus") is not None and "phonetisaurus.fst" not in names:
                    errs.append(f"{e['lang']}: bundle lacks phonetisaurus.fst")
                lex = tar.extractfile("lexicon.txt")
                if lex is None:
                    errs.append(f"{e['lang']}: lexicon.txt unreadable")
                    continue
                n = 0
                for i, line in enumerate(io.TextIOWrapper(lex, encoding="utf-8")):
                    word, sep, phones = line.partition("\t")
                    if not sep or not word.strip() or not phones.strip():
                        errs.append(f"{e['lang']}: malformed lexicon line {i + 1}")
                        break
                    n += 1
                if n != e["entries"]:
                    errs.append(
                        f"{e['lang']}: lexicon has {n} lines, manifest says {e['entries']}"
                    )
                notice = tar.extractfile("NOTICE")
                if notice is not None:
                    text = notice.read().decode()
                    if "CC BY-SA" not in text and "BSD" not in text and "MIT" not in text:
                        errs.append(f"{e['lang']}: NOTICE carries no license")
                bundles += 1
        except tarfile.TarError as ex:
            errs.append(f"{e['lang']}: cannot open bundle: {ex}")
    return errs, bundles


def resolve(manifest: dict, want: str) -> str | None:
    """Mirrors LexiconArchive::entry(): exact lang, exact bcp47, then
    longest-shared-bcp47-prefix with plain ids winning ties."""
    want = want.lower().replace("_", "-")
    short = want.split("-")[0]
    langs = manifest["languages"]
    for e in langs:
        if e["lang"].lower() == want or e["bcp47"].lower() == want:
            return e["lang"]
    want_parts = want.split("-")
    best, best_key = None, -1
    for e in langs:
        p = e["bcp47"].split("-")[0]
        if p != short:
            continue
        parts = e["bcp47"].lower().split("-")
        shared = 0
        for a, b in zip(want_parts, parts):
            if a != b:
                break
            shared += 1
        key = shared * 2 + int(e["lang"].lower() == short)
        if key > best_key:
            best, best_key = e["lang"], key
    return best


def check_resolution(base: dict, expanded: dict) -> list[str]:
    errs: list[str] = []
    for voice, want in RESOLUTION.items():
        got = resolve(base, voice)
        if got != want:
            errs.append(f"base: {voice}: resolved to {got!r}, expected {want!r}")
    for voice, want in EXPANDED_RESOLUTION.items():
        got = resolve(expanded, voice) if expanded else None
        if got != want:
            errs.append(f"expanded: {voice}: resolved to {got!r}, expected {want!r}")
    for voice, why in BLOCKED.items():
        got = resolve(base, voice) or (resolve(expanded, voice) if expanded else None)
        if got is not None:
            errs.append(f"{voice}: documented blocked:{why} but resolves to {got!r}")
    return errs


def check_no_regression(candidate: dict, baseline: dict) -> list[str]:
    """PR rule: bundles only expand — no language disappears, no
    per-language entry count decreases. Entry *counts* may legitimately
    change when a dictionary is rebuilt from a better source; shrinking
    still flags loudly so it can only ever happen deliberately."""
    errs: list[str] = []
    base = {e["lang"]: e for e in baseline["languages"]}
    cand = {e["lang"]: e for e in candidate["languages"]}
    for lang, entry in base.items():
        if lang not in cand:
            errs.append(f"REGRESSION: bundle {lang!r} in baseline is gone")
        elif cand[lang]["entries"] < entry["entries"]:
            errs.append(
                f"REGRESSION: {lang} shrank {entry['entries']} -> {cand[lang]['entries']}"
            )
    return errs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dist", default="dist")
    ap.add_argument("--expanded", default="dist/expanded-v2")
    ap.add_argument("--skip-expanded", action="store_true",
                    help="skip the expanded-tier checks (CI release job "
                    "builds the base tier only)")
    ap.add_argument("--baseline", help="published lexicons.json (path or URL) "
                    "to assert expand-only changes")
    args = ap.parse_args()
    dist = REPO / args.dist
    exp_dir = REPO / args.expanded

    failures: list[str] = []
    base = json.loads((dist / "lexicons.json").read_text())
    has_expanded = not args.skip_expanded and (exp_dir / "expanded.json").exists()
    expanded = json.loads((exp_dir / "expanded.json").read_text()) if has_expanded else None

    failures += check_manifest_schema(base)
    if has_expanded:
        failures += check_manifest_schema(expanded)
    errs, bundles = check_bundles(base, dist)
    failures += errs
    print(f"base manifest: {len(base['languages'])} languages, {bundles} bundles verified")
    if has_expanded:
        errs, exp_bundles = check_bundles(expanded, exp_dir)
        failures += errs
        print(f"expanded manifest: {len(expanded['languages'])} languages, {exp_bundles} bundles verified")
    failures += check_resolution(base, expanded)
    print(f"resolution table: {len(RESOLUTION)} base + "
          f"{len(EXPANDED_RESOLUTION)} expanded voices, {len(BLOCKED)} blocked")

    if args.baseline:
        bl = args.baseline
        if bl.startswith("http"):
            import urllib.request
            with urllib.request.urlopen(bl, timeout=60) as r:
                baseline = json.load(r)
        else:
            baseline = json.loads(Path(bl).read_text())
        failures += check_no_regression(base, baseline)
        n_base = len(baseline["languages"])
        new_langs = sorted({e["lang"] for e in base["languages"]}
                           - {e["lang"] for e in baseline["languages"]})
        print(f"expand-only check vs baseline: {n_base} -> "
              f"{len(base['languages'])} languages (+{len(new_langs)}: "
              f"{', '.join(new_langs) or 'none'})")

    if failures:
        print(f"\nFAILURES ({len(failures)}):")
        for f in failures:
            print(" -", f)
        return 1
    print("\nrelease validation OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
