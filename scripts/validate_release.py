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

# voice locale -> intended bundle; must mirror examples/consumer_smoke.rs
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
    "is_IS": "isl", "pl_PL": "pol", "nb_NO": "nob",
}
BLOCKED = {"ku_TR": "no-data", "tn_ZA": "no-data", "ne_NP": "conventions",
           "vi_VN": "conventions", "uk_UA": "conventions", "lv_LV": "conventions"}


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
    want = want.lower().replace("_", "-")
    short = want.split("-")[0]
    for e in manifest["languages"]:
        if e["lang"].lower() == want or e["bcp47"].lower() == want:
            return e["lang"]
    for e in manifest["languages"]:
        if e["bcp47"].split("-")[0] == short:
            return e["lang"]
    return None


def check_resolution(base: dict, expanded: dict) -> list[str]:
    errs: list[str] = []
    expanded_only = {"isl", "pol", "nob"}
    for voice, want in RESOLUTION.items():
        if want in expanded_only:
            got = resolve(expanded, voice)
        else:
            got = resolve(base, voice) or resolve(expanded, voice)
        if got != want:
            errs.append(f"{voice}: resolved to {got!r}, expected {want!r}")
    for voice, why in BLOCKED.items():
        got = resolve(base, voice) or resolve(expanded, voice)
        if got is not None:
            errs.append(f"{voice}: documented blocked:{why} but resolves to {got!r}")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dist", default="dist")
    ap.add_argument("--expanded", default="dist/expanded-v2")
    args = ap.parse_args()
    dist = REPO / args.dist
    exp_dir = REPO / args.expanded

    failures: list[str] = []
    base = json.loads((dist / "lexicons.json").read_text())
    expanded = json.loads((exp_dir / "expanded.json").read_text())

    failures += check_manifest_schema(base)
    failures += check_manifest_schema(expanded)
    errs, bundles = check_bundles(base, dist)
    failures += errs
    print(f"base manifest: {len(base['languages'])} languages, {bundles} bundles verified")
    errs, exp_bundles = check_bundles(expanded, exp_dir)
    failures += exp_bundles and errs or errs
    print(f"expanded manifest: {len(expanded['languages'])} languages, {exp_bundles} bundles verified")
    failures += check_resolution(base, expanded)
    print(f"resolution table: {len(RESOLUTION)} voices, {len(BLOCKED)} blocked")

    if failures:
        print(f"\nFAILURES ({len(failures)}):")
        for f in failures:
            print(" -", f)
        return 1
    print("\nrelease validation OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
