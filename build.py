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

FLORAVOX_TAG = os.environ.get("FLORAVOX_TAG", "v0.8.5")

# Language table: code -> (source kind, pypi package or None for core
# gruut, bcp47-ish, license string, source url for provenance).
ROOT = Path(__file__).parent

# License labels carry TWO layers (issue #1): the gruut-lang package
# scaffolding is MIT (Michael Hansen), but the LEXICON DATA inside
# derives from Wiktionary via Kyubyong/pron_dictionaries (which
# extracts from Wiktionary dumps and declares no license of its own).
# The defensible data license is CC BY-SA (Wiktionary's grant).
# Confirmed chain (pron_dictionaries prebuilt): de es fr it pt ru.
# ca cs fa nl sv sw: inspected 2026-11 (issue #3) — the packaged
# lexicons carry Wiktionary-extraction fingerprints (affix lemmas
# '-ák'/'-procentig', "'s-Gravenhage" compounds, conjugation-table
# forms + 'word(2)' homograph keys, loanword entries); no upstream
# statement exists in the sdists themselves. Labelled CC BY-SA with
# the inspection recorded here and in docs/sherpa-coverage.md.
# en: gruut core package; provenance under separate audit.
LANGUAGES: dict[str, dict] = {
    "ca": {"pkg": "gruut-lang-ca", "bcp47": "ca",
           "data_license": "CC-BY-SA-4.0 (Wiktionary-derived, confirmed by inspection 2026-11)",
           "license": "CC-BY-SA-4.0 (data: Wiktionary) + MIT (package)",
           "name": "Catalan"},
    "cs": {"pkg": "gruut-lang-cs", "bcp47": "cs",
           "data_license": "CC-BY-SA-4.0 (Wiktionary-derived, confirmed by inspection 2026-11)",
           "license": "CC-BY-SA-4.0 (data: Wiktionary) + MIT (package)",
           "name": "Czech"},
    "de": {"pkg": "gruut-lang-de", "bcp47": "de-DE",
           "data_license": "CC-BY-SA-4.0 (Wiktionary-derived)",
           "license": "CC-BY-SA-4.0 (data: Wiktionary) + MIT (package)",
           "name": "German"},
    "en": {"pkg": None, "bcp47": "en-US",
           "data_license": "TBD (gruut core en lexicon, provenance under audit)",
           "license": "MIT (package; data provenance under audit)",
           "name": "English (US, gruut)"},
    "es": {"pkg": "gruut-lang-es", "bcp47": "es-ES",
           "data_license": "CC-BY-SA-4.0 (Wiktionary-derived)",
           "license": "CC-BY-SA-4.0 (data: Wiktionary) + MIT (package)",
           "name": "Spanish"},
    "fa": {"pkg": "gruut-lang-fa", "bcp47": "fa",
           "data_license": "CC-BY-SA-4.0 (Wiktionary-derived, confirmed by inspection 2026-11)",
           "license": "CC-BY-SA-4.0 (data: Wiktionary) + MIT (package)",
           "name": "Persian"},
    "fr": {"pkg": "gruut-lang-fr", "bcp47": "fr-FR",
           "data_license": "CC-BY-SA-4.0 (Wiktionary-derived)",
           "license": "CC-BY-SA-4.0 (data: Wiktionary) + MIT (package)",
           "name": "French"},
    "it": {"pkg": "gruut-lang-it", "bcp47": "it-IT",
           "data_license": "CC-BY-SA-4.0 (Wiktionary-derived)",
           "license": "CC-BY-SA-4.0 (data: Wiktionary) + MIT (package)",
           "name": "Italian"},
    "nl": {"pkg": "gruut-lang-nl", "bcp47": "nl-NL",
           "data_license": "CC-BY-SA-4.0 (Wiktionary-derived, confirmed by inspection 2026-11)",
           "license": "CC-BY-SA-4.0 (data: Wiktionary) + MIT (package)",
           "name": "Dutch"},
    "pt": {"pkg": "gruut-lang-pt", "bcp47": "pt-PT",
           "data_license": "CC-BY-SA-4.0 (Wiktionary-derived)",
           "license": "CC-BY-SA-4.0 (data: Wiktionary) + MIT (package)",
           "name": "Portuguese"},
    "ru": {"pkg": "gruut-lang-ru", "bcp47": "ru-RU",
           "data_license": "CC-BY-SA-4.0 (Wiktionary-derived)",
           "license": "CC-BY-SA-4.0 (data: Wiktionary) + MIT (package)",
           "name": "Russian"},
    "sv": {"pkg": "gruut-lang-sv", "bcp47": "sv-SE",
           "data_license": "CC-BY-SA-4.0 (Wiktionary-derived, confirmed by inspection 2026-11)",
           "license": "CC-BY-SA-4.0 (data: Wiktionary) + MIT (package)",
           "name": "Swedish"},
    "sw": {"pkg": "gruut-lang-sw", "bcp47": "sw",
           "data_license": "CC-BY-SA-4.0 (Wiktionary-derived, confirmed by inspection 2026-11)",
           "license": "CC-BY-SA-4.0 (data: Wiktionary) + MIT (package)",
           "name": "Swahili"},
}

# English alternates / extras (not gruut).
EXTRAS: dict[str, dict] = {
    "en-GB": {
        "kind": "staging",
        # kaikki (Wiktionary) UK/RP IPA primary + gruut en-US fallback
        # rows for words Wiktionary lacks UK tags for (function words,
        # inflections). See staging/en-GB/ and NOTICE inside the bundle.
        "bcp47": "en-GB",
        "license": "CC-BY-SA-3.0 (kaikki primary) + MIT (gruut fallback rows)",
        "name": "English (UK/RP, Wiktionary IPA + gruut fills)",
        "path": "staging/en-GB/lexicon.tsv",
    },
    "en-cmudict": {
        "kind": "cmudict",
        "bcp47": "en-US",
        "license": "BSD-2-Clause-like (CMUDict)",
        "name": "English (CMUDict, ARPABET→IPA)",
        "url": "https://raw.githubusercontent.com/cmusphinx/cmudict/master/cmudict.dict",
        # ARPABET rows: fst-compile converts them, but Phonetisaurus
        # training panics ("empty grapheme table") — ships
        # dictionary-only, as originally intended (see the WFST note
        # below). Without this flag, full rebuilds silently dropped
        # the bundle (that is how v0.4.0 lost it).
        "no_train": True,
    },
    # WikiPron-harvested locales (issue #5): broad-phonemic scrapes of
    # Wiktionary, CC BY-SA 4.0. Bundles keyed to the piper voice locale
    # codes so the fetcher resolves them by bcp47 prefix. Training FSTs
    # and holdout metrics live in staging/<iso3>/ (harvest_and_train).
    "af": {"kind": "staging", "bcp47": "af", "name": "Afrikaans",
           "path": "staging/afr/merged.tsv", "wikipron": True,
           "source": "wikipron:afr_latn_broad_filtered.tsv"},
    "cy": {"kind": "staging", "bcp47": "cy", "name": "Welsh",
           "path": "staging/cym/merged.tsv", "wikipron": True,
           "source": "wikipron:cym_latn_broad.tsv"},
    "et": {"kind": "staging", "bcp47": "et", "name": "Estonian",
           "path": "staging/est/merged.tsv", "wikipron": True,
           "source": "wikipron:est_latn_broad.tsv"},
    "eu": {"kind": "staging", "bcp47": "eu", "name": "Basque",
           "path": "staging/eus/merged.tsv", "wikipron": True,
           "source": "wikipron:eus_latn_broad.tsv"},
    "ga": {"kind": "staging", "bcp47": "ga", "name": "Irish",
           "path": "staging/gle/merged.tsv", "wikipron": True,
           "source": "wikipron:gle_latn_broad.tsv"},
    "gu": {"kind": "staging", "bcp47": "gu", "name": "Gujarati",
           "path": "staging/guj/merged.tsv", "wikipron": True,
           "source": "wikipron:guj_gujr_broad.tsv"},
    "hr": {"kind": "staging", "bcp47": "hr", "name": "Croatian (Latin script)",
           "path": "staging/hbs/lexicon-hr.tsv", "wikipron": True,
           "source": "wikipron:hbs_latn_broad_filtered.tsv"},
    "sr": {"kind": "staging", "bcp47": "sr", "name": "Serbian (Cyrillic script)",
           "path": "staging/hbs/lexicon-sr.tsv", "wikipron": True,
           "source": "wikipron:hbs_cyrl_broad_filtered.tsv"},
    "kk": {"kind": "staging", "bcp47": "kk", "name": "Kazakh",
           "path": "staging/kaz/merged.tsv", "wikipron": True,
           "source": "wikipron:kaz_cyrl_broad.tsv",
           "small": "thin scrape (669 words) — WFST carries most words"},
    "ko": {"kind": "staging", "bcp47": "ko", "name": "Korean",
           "path": "staging/kor/kaikki.folded.tsv", "kaikki": True,
           "source": "kaikki:Korean (English Wiktionary extraction)",
           "note": "folded to the voice's conventions (scripts/fold_korean.py): "
                   "narrow vowels to the espeak set, laryngeal contrasts "
                   "(aspirated/fortis/unreleased) merged to plain — the ko "
                   "voice family's token inventory distinguishes none of "
                   "them. Validated against mimic3-ko_KO-kss tokens.txt "
                   "(0.13% corpus drop)"},
    "lb": {"kind": "staging", "bcp47": "lb", "name": "Luxembourgish",
           "path": "staging/ltz/merged.tsv", "wikipron": True,
           "source": "wikipron:ltz_latn_broad.tsv"},
    "lv": {"kind": "staging", "bcp47": "lv", "name": "Latvian",
           "path": "staging/lav/kaikki.folded.tsv", "kaikki": True,
           "source": "kaikki:Latvian (English Wiktionary extraction)",
           "small": "thin extraction (1,704 words) — WFST carries most words",
           "note": "folded (scripts/fold_latvian.py): pitch-accented/macrone "
                   "vowels to plain long vowels (espeak lv marks no tones); "
                   "0.23% drop vs lv_LV-aivars"},
    "lt": {"kind": "staging", "bcp47": "lt", "name": "Lithuanian",
           "path": "staging/lit/merged.tsv", "wikipron": True,
           "source": "wikipron:lit_latn_broad.tsv",
           "small": "thin scrape (437 words) — WFST carries most words"},
    "ml": {"kind": "staging", "bcp47": "ml", "name": "Malayalam",
           "path": "staging/mal/merged.tsv", "wikipron": True,
           "source": "wikipron:mal_mlym_broad.tsv"},
    "mt": {"kind": "staging", "bcp47": "mt", "name": "Maltese",
           "path": "staging/mlt/merged.tsv", "wikipron": True,
           "source": "wikipron:mlt_latn_broad_filtered.tsv"},
    "no": {"kind": "staging", "bcp47": "no", "name": "Norwegian (Bokmål)",
           "path": "staging/nob/merged.tsv", "wikipron": True,
           "source": "wikipron:nob_latn_broad_filtered.tsv",
           "note": "Bokmål scrape; the expanded-v2 'nob' bundle (bcp47 nb) "
                   "carries the distilled superset"},
    "ka": {"kind": "staging", "bcp47": "ka", "name": "Georgian",
           "path": "staging/kat/kaikki.folded.tsv", "kaikki": True,
           "source": "kaikki:Georgian (English Wiktionary extraction)",
           "note": "folded to the voices' broad conventions "
                   "(scripts/fold_georgian.py): vowels ɑ ɛ ɔ, plain stop "
                   "series (ejectives/labialization merged — the piper ka "
                   "voices' token inventories do not distinguish them)"},
    "hu": {"kind": "staging", "bcp47": "hu", "name": "Hungarian",
           "path": "staging/hun/merged.tsv", "kaikki": True,
           "source": "kaikki:Hungarian (English Wiktionary extraction)"},
    "sq": {"kind": "staging", "bcp47": "sq", "name": "Albanian",
           "path": "staging/sqi/merged.tsv", "wikipron": True,
           "source": "wikipron:sqi_latn_broad.tsv"},
    "ne": {"kind": "staging", "bcp47": "ne", "name": "Nepali",
           "path": "staging/nep/kaikki.folded.tsv", "kaikki": True,
           "source": "kaikki:Nepali (English Wiktionary extraction)",
           "small": "thin extraction (2,135 words) — WFST carries most words",
           "note": "folded (scripts/fold_nepali.py): aspiration as ʰ "
                   "tokens, nasal vowels as vowel+̃ — both verified in the "
                   "ne voices' phoneme inventories; 0.05% drop vs "
                   "ne_NP-google-medium"},
    "uk": {"kind": "staging", "bcp47": "uk", "name": "Ukrainian",
           "path": "staging/ukr/kaikki.folded.tsv", "kaikki": True,
           "source": "kaikki:Ukrainian (English Wiktionary extraction)",
           "note": "folded (scripts/fold_ukrainian.py): glide breves to "
                   "j/w per espeak convention; 0.004% drop vs "
                   "uk_UA-lada — the ukrainian_tts voice is grapheme-based "
                   "(Cyrillic tokens) and needs no lexicon"},
    "vi": {"kind": "staging", "bcp47": "vi", "name": "Vietnamese (Hanoi)",
           "path": "staging/vie/kaikki.folded.tsv", "kaikki": True,
           "source": "kaikki:Vietnamese (English Wiktionary extraction)",
           "note": "Chao tone letters folded to the espeak tone digits "
                   "(scripts/fold_vietnamese.py; ngang=7 huyền=2 sắc=3 "
                   "hỏi=4 ngã=5 nặng=6, verified against espeak-ng's own "
                   "phonemization); 0.014% drop vs vi_VN-vais1000"},
    "yue": {"kind": "staging", "bcp47": "yue", "name": "Cantonese (Han script)",
            "path": "staging/yue/merged.tsv", "wikipron": True,
            "source": "wikipron:yue_hani_standard_broad.tsv",
            "no_train": True,
            "note": "dictionary-only: the Han WFST was 19 MB at 30% exact / "
                    "64% coverage — OOV words fall back char-wise to the "
                    "dictionary (every Han char carries an entry)"},
    "zh": {"kind": "staging", "bcp47": "zh-CN", "name": "Mandarin Chinese (simplified Han)",
           "path": "staging/cmn/wikipron.folded.tsv", "wikipron": True,
           "source": "wikipron:cmn_hani_standard_broad.tsv",
           "no_train": True,
           "note": "Chao tone contours folded to espeak tone digits 1-5 "
                   "(scripts/fold_mandarin.py), validated against "
                   "piper-zh_CN-huayan-medium tokens.txt (0.10% corpus drop). "
                   "No Phonetisaurus: Han-grapheme alignment yields an 82 MB "
                   "model at only 33% exact / 68% coverage — OOV words should "
                   "fall back char-wise to the dictionary (every Han char "
                   "carries an entry), the standard Chinese front-end move"},
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


def build_lang(
    lang: str, work: Path, dist: Path, version: str, train: bool = True,
    train_iters: int | None = None,
) -> dict | None:
    meta = LANGUAGES.get(lang)
    extra = EXTRAS.get(lang) or {}
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
            if not extra:
                print(f"  !! unknown language {lang}")
                return None
            if extra.get("kind") == "staging":
                staging_src = ROOT / extra["path"]
                if not staging_src.is_file():
                    print(f"  !! staging source missing: {staging_src}")
                    return None
                n = sum(
                    1
                    for line in staging_src.read_text(encoding="utf-8").splitlines()
                    if line.strip() and "\t" in line
                )
                shutil.copyfile(staging_src, td / "lex.tsv")
                source = extra.get("source", f"staging:{extra['path']}")
                license_ = extra.get(
                    "license",
                    "CC-BY-SA-4.0 (data: Wiktionary via WikiPron) + MIT (tooling)"
                    if extra.get("wikipron") else
                    "CC-BY-SA-4.0 (data: Wiktionary via kaikki) + MIT (tooling)"
                    if extra.get("kaikki") else None,
                )
            else:
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
        if extra.get("kind") == "cmudict":
            # ARPABET rows must convert to spaced IPA (the crate's own
            # notation table, via examples/arpabet) — raw CMUdict lines
            # are space-separated ARPABET and unusable by sherpa readers
            subprocess.run(
                ["cargo", "build", "--release", "--quiet", "--example", "arpabet"],
                cwd=ROOT, check=True, capture_output=True,
            )
            conv = ROOT / "target/release/examples/arpabet"
            with lexicon_txt.open("wb") as lf:
                with tsv.open("rb") as src:
                    subprocess.run([str(conv)], stdin=src, stdout=lf, check=True)
        else:
            shutil.copyfile(tsv, lexicon_txt)
        bundle_files = [
            stem.with_suffix(".fst"),
            stem.with_suffix(".pho"),
            lexicon_txt,
        ]

        # Per-language Phonetisaurus model trained on this lexicon, so
        # OOV output uses the bundle's own alphabet by construction.
        # Some locales opt out (EXTRAS "no_train") where char-level
        # alignment makes the WFST large and weak — Han-script zh keeps
        # a 7 MB dictionary bundle; OOV words fall back char-wise to
        # the dictionary itself (every Han char carries an entry).
        phonetisaurus_meta = None
        if train and not extra.get("no_train") \
            and shutil.which("floravox-train-phonetisaurus"):
            model_out = td / "phonetisaurus.fst"
            metrics_out = td / "metrics.json"
            cmd = ["floravox-train-phonetisaurus", str(tsv), str(model_out),
                   "--metrics", str(metrics_out)]
            if train_iters:
                cmd += ["--iters", str(train_iters)]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                print(f"  !! training failed: {r.stderr.strip()[-500:]}")
                return None
            bundle_files.append(model_out)
            phonetisaurus_meta = json.loads(metrics_out.read_text())
            print(f"  phonetisaurus: exact {phonetisaurus_meta['exact_match']:.1%}, "
                  f"PER {phonetisaurus_meta['per']:.1%}")
        elif train and not extra.get("no_train"):
            print("  !! floravox-train-phonetisaurus not on PATH; skipping WFST")
        ph_license = None

        # package tar.gz
        tar_path = dist / f"{lang}.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tar:
            for f in bundle_files:
                tar.add(f, arcname=f.name)
            notice = f"voicegarden-lexicons {lang}\nsource: {source}\nlicense: {license_}\n"
            dl = (meta or EXTRAS[lang]).get("data_license", "")
            if extra.get("kaikki"):
                notice += (
                    "data provenance: kaikki.org extraction of the English\n"
                    "  Wiktionary, CC BY-SA 4.0, (c) Wiktionary contributors.\n"
                    "  https://creativecommons.org/licenses/by-sa/4.0/\n"
                    "  Adaptations must carry the same license + attribution.\n"
                )
                if extra.get("small"):
                    notice += f"note: {extra['small']}\n"
                if extra.get("note"):
                    notice += f"note: {extra['note']}\n"
            elif extra.get("wikipron"):
                notice += (
                    "data provenance: WikiPron scrape of Wiktionary\n"
                    "  (https://github.com/CUNY-CL/wikipron), CC BY-SA 4.0,\n"
                    "  (c) Wiktionary contributors.\n"
                    "  https://creativecommons.org/licenses/by-sa/4.0/\n"
                    "  Adaptations must carry the same license + attribution.\n"
                )
                if extra.get("small"):
                    notice += f"note: {extra['small']}\n"
                if extra.get("note"):
                    notice += f"note: {extra['note']}\n"
            elif "CC-BY-SA" in dl:
                notice += (
                    "data provenance: Wiktionary (via Kyubyong/pron_dictionaries\n"
                    "  -> gruut-lang); CC BY-SA 4.0, (c) Wiktionary contributors.\n"
                    "  https://creativecommons.org/licenses/by-sa/4.0/\n"
                    "  Adaptations must carry the same license + attribution.\n"
                )
                if "confirmed by inspection" in dl:
                    notice += (
                        "  (gruut-lang pack has no upstream statement; Wiktionary\n"
                        "  extraction confirmed by inspection 2026-11 — see\n"
                        "  docs/sherpa-coverage.md)\n"
                    )
                elif "inferred" in dl:
                    notice += (
                        "  (provenance inferred -- gruut-lang pack not in the\n"
                        "  pron_dictionaries prebuilt list; per-language\n"
                        "  confirmation pending, see issue #1)\n"
                    )
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
            "phonetisaurus": phonetisaurus_meta,
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
    ap.add_argument("--no-train", action="store_true",
                    help="skip Phonetisaurus training (fast CI mode)")
    ap.add_argument("--train-iters", type=int, default=None,
                    help="override EM iterations (quick smoke runs)")
    args = ap.parse_args()

    dist = Path(args.out)
    dist.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="vgl-build-"))

    langs = args.langs.split(",") if args.langs else list(LANGUAGES) + list(EXTRAS)

    # subset builds merge into the existing manifest instead of clobbering
    prior_path = dist / "lexicons.json"
    prior: dict[str, dict] = {}
    if args.langs and prior_path.exists():
        try:
            for e in json.loads(prior_path.read_text())["languages"]:
                prior[e["lang"]] = e
        except (json.JSONDecodeError, KeyError):
            pass

    entries = []
    failed: list[str] = []
    for lang in langs:
        entry = build_lang(
            lang.strip(), work, dist, args.version,
            train=not args.no_train, train_iters=args.train_iters,
        )
        if entry:
            entries.append(entry)
            prior[entry["lang"]] = entry
        else:
            failed.append(lang.strip())
    if failed:
        # a full build must never silently shrink the manifest (that is
        # how v0.4.0 lost en-cmudict for two releases)
        print(f"\n!! {len(failed)} bundle(s) FAILED to build: {', '.join(failed)}")
        if not args.langs:
            print("!! full build — previously published bundles are MISSING")
        if prior:
            still_ok = [l for l in failed if l not in prior]
            print(f"!! lost-from-prior: {', '.join(still_ok) or 'none'}")

    languages = list(prior.values()) if args.langs else entries
    manifest = {
        "version": args.version,
        "format": "voicegarden-lexicons/1",
        "generator": f"floravox-fst-compile {FLORAVOX_TAG}",
        "languages": sorted(languages, key=lambda e: e["lang"]),
    }
    (dist / "lexicons.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(f"\nwrote {dist / 'lexicons.json'} ({len(entries)} languages)")
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
