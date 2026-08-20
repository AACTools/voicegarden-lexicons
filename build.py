#!/usr/bin/env python3
"""Build voicegarden-lexicons bundles + manifest.

Per language: download the source lexicon, convert to floravox TSV,
compile with floravox-fst-compile, package a tar.gz with metadata, and
emit the lexicons.json manifest entry (with SHA-256).

Usage:
  python build.py [--langs de,fr] [--out dist] [--version v1]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

FLORAVOX_TAG = os.environ.get("FLORAVOX_TAG", "v0.5.0")

# Language table: code -> (source kind, pypi package or None for core
# gruut, bcp47-ish, license string, source url for provenance).
LANGUAGES: dict[str, dict] = {
    "ca": {"pkg": "gruut-lang-ca", "bcp47": "ca", "license": "MIT",
           "name": "Catalan"},
    "cs": {"pkg": "gruut-lang-cs", "bcp47": "cs", "license": "MIT",
           "name": "Czech"},
    "de": {"pkg": "gruut-lang-de", "bcp47": "de-DE", "license": "MIT",
           "name": "German"},
    "en": {"pkg": None, "bcp47": "en-US", "license": "MIT",
           "name": "English (US, gruut)"},
    "es": {"pkg": "gruut-lang-es", "bcp47": "es-ES", "license": "MIT",
           "name": "Spanish"},
    "fa": {"pkg": "gruut-lang-fa", "bcp47": "fa", "license": "MIT",
           "name": "Persian"},
    "fr": {"pkg": "gruut-lang-fr", "bcp47": "fr-FR", "license": "MIT",
           "name": "French"},
    "it": {"pkg": "gruut-lang-it", "bcp47": "it-IT", "license": "MIT",
           "name": "Italian"},
    "nl": {"pkg": "gruut-lang-nl", "bcp47": "nl-NL", "license": "MIT",
           "name": "Dutch"},
    "pt": {"pkg": "gruut-lang-pt", "bcp47": "pt-PT", "license": "MIT",
           "name": "Portuguese"},
    "ru": {"pkg": "gruut-lang-ru", "bcp47": "ru-RU", "license": "MIT",
           "name": "Russian"},
    "sv": {"pkg": "gruut-lang-sv", "bcp47": "sv-SE", "license": "MIT",
           "name": "Swedish"},
    "sw": {"pkg": "gruut-lang-sw", "bcp47": "sw", "license": "MIT",
           "name": "Swahili"},
}

# English alternates / extras (not gruut).
EXTRAS: dict[str, dict] = {
    "en-cmudict": {
        "kind": "cmudict",
        "bcp47": "en-US",
        "license": "BSD-2-Clause-like (CMUDict)",
        "name": "English (CMUDict, ARPABET→IPA)",
        "url": "https://raw.githubusercontent.com/cmusphinx/cmudict/master/cmudict.dict",
    },
}

# NOTE: per-language Phonetisaurus WFSTs are a planned addition, to be
# TRAINED on these IPA lexicons so OOV output matches the bundle's
# alphabet. The published cmudict WFST emits ARPABET, which mismatches
# the IPA lexicons here (OOV words would produce unresolvable symbols),
# so no WFST ships in v1 bundles.


def pypi_sdist(pkg: str, pin: str | None = None) -> str:
    spec = f"{pkg}/{pin}" if pin else pkg
    with urllib.request.urlopen(f"https://pypi.org/pypi/{spec}/json") as r:
        info = json.load(r)
    for u in info["urls"]:
        if u["packagetype"] == "sdist":
            return u["url"]
    raise SystemExit(f"no sdist for {pkg}")


def download(url: str, dest: Path) -> None:
    print(f"  download {url}")
    with urllib.request.urlopen(url) as r, dest.open("wb") as f:
        shutil.copyfileobj(r, f)


def gruut_db_to_tsv(db_path: Path, tsv_path: Path) -> int:
    db = sqlite3.connect(str(db_path))
    rows = db.execute(
        "SELECT word, phonemes FROM word_phonemes WHERE pron_order = 0 "
        "ORDER BY word COLLATE NOCASE"
    )
    n = 0
    with tsv_path.open("w", encoding="utf-8") as f:
        for word, pron in rows:
            pron = " ".join(pron.split())
            if word and pron:
                f.write(f"{word}\t{pron}\n")
                n += 1
    return n


def cmudict_to_tsv(src: Path, tsv_path: Path) -> int:
    """Marker-only conversion: pass through, the fst-compile --format
    cmudict path handles ARPABET→IPA. We emit a `# format: cmudict`
    hint by relying on auto-detection."""
    n = 0
    with tsv_path.open("w", encoding="utf-8") as out, src.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            if line and not line.startswith(";"):
                out.write(line + "\n")
                n += 1
    return n


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_lang(lang: str, work: Path, dist: Path, version: str) -> dict | None:
    meta = LANGUAGES.get(lang)
    print(f"== {lang}")
    with tempfile.TemporaryDirectory(dir=work) as td:
        td = Path(td)
        if meta:
            pkg = meta["pkg"]
            if pkg:
                sdist = td / "s.tar.gz"
                download(pypi_sdist(pkg), sdist)
                subprocess.run(["tar", "xzf", str(sdist), "-C", str(td)], check=True)
                # gruut_lang_de-2.0.1/gruut_lang_de/lexicon.db
                dbs = list(td.rglob("lexicon.db"))
                dbs = [d for d in dbs if "espeak" not in str(d)]
                if not dbs:
                    print(f"  !! no lexicon.db in {pkg}")
                    return None
                n = gruut_db_to_tsv(dbs[0], td / "lex.tsv")
                source = f"PyPI:{pkg}"
                license_ = meta["license"]
            else:
                # core gruut 2.0.0 sdist ships data/en-us/lexicon.db
                # (2.4.0 dropped the bundled data)
                sdist = td / "g.tar.gz"
                download(pypi_sdist("gruut", pin="2.0.0"), sdist)
                subprocess.run(["tar", "xzf", str(sdist), "-C", str(td),
                                "--wildcards", "*/gruut/data/en-us/lexicon.db"],
                               check=True)
                dbs = list(td.rglob("lexicon.db"))
                if not dbs:
                    print("  !! core gruut has no en-us lexicon.db")
                    return None
                n = gruut_db_to_tsv(dbs[0], td / "lex.tsv")
                source = "PyPI:gruut"
                license_ = meta["license"]
        else:
            extra = EXTRAS.get(lang)
            if not extra:
                print(f"  !! unknown language {lang}")
                return None
            src = td / "cmudict.dict"
            download(extra["url"], src)
            n = cmudict_to_tsv(src, td / "lex.tsv")
            source = "github:cmusphinx/cmudict"
            license_ = extra["license"]

        # compile with floravox-fst-compile
        tsv = td / "lex.tsv"
        stem = td / lang
        r = subprocess.run(
            ["floravox-fst-compile", str(tsv), str(stem)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(f"  !! fst-compile failed: {r.stderr.strip()}")
            return None
        print(f"  entries: {n}")

        # sherpa-onnx 2.0 lexicon.txt format: `word\tp1 p2 p3`
        # (their Alternative 1 for the espeak-ng removal,
        # k2-fsa/sherpa-onnx#3731) — same data, consumable by every
        # sherpa-onnx binding with zero code.
        lexicon_txt = td / "lexicon.txt"
        shutil.copyfile(tsv, lexicon_txt)
        bundle_files = [
            stem.with_suffix(".fst"),
            stem.with_suffix(".pho"),
            lexicon_txt,
        ]
        ph_license = None

        # package tar.gz
        tar_path = dist / f"{lang}.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tar:
            for f in bundle_files:
                tar.add(f, arcname=f.name)
            notice = f"voicegarden-lexicons {lang}\nsource: {source}\nlicense: {license_}\n"
            if ph_license:
                notice += f"phonetisaurus.fst: {PHONETISAURUS_EN['url']} ({ph_license})\n"
            info = tarfile.TarInfo("NOTICE")
            info.size = len(notice.encode())
            tar.addfile(info, io.BytesIO(notice.encode()))

        return {
            "lang": lang,
            "name": (meta or EXTRAS[lang])["name"],
            "bcp47": (meta or EXTRAS[lang])["bcp47"],
            "entries": n,
            "license": license_,
            "source": source,
            "phonetisaurus": ph_license,
            "file": f"{lang}.tar.gz",
            "sha256": sha256(tar_path),
            "size_bytes": tar_path.stat().st_size,
            "format": "floravox-fst-lexicon/1",
            "floravox_tag": FLORAVOX_TAG,
            "version": version,
        }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--langs", help="comma-separated subset")
    ap.add_argument("--out", default="dist")
    ap.add_argument("--version", default="dev")
    args = ap.parse_args()

    dist = Path(args.out)
    dist.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="vgl-build-"))

    langs = args.langs.split(",") if args.langs else list(LANGUAGES) + list(EXTRAS)
    entries = []
    for lang in langs:
        entry = build_lang(lang.strip(), work, dist, args.version)
        if entry:
            entries.append(entry)

    manifest = {
        "version": args.version,
        "format": "voicegarden-lexicons/1",
        "generator": f"floravox-fst-compile {FLORAVOX_TAG}",
        "languages": entries,
    }
    (dist / "lexicons.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(f"\nwrote {dist / 'lexicons.json'} ({len(entries)} languages)")
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
