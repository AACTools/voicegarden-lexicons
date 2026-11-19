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
    "it": None,  # moved to EXTRAS: built from the staging union (gruut +
                # WikiPron fills) — audits 0.004% vs it_IT-dii-high
    "nl": None,  # moved to EXTRAS: built from the staging union — audits
                # 0.000% vs nl_NL-alex-medium
    "pt": {"pkg": "gruut-lang-pt", "bcp47": "pt-PT",
           "data_license": "CC-BY-SA-4.0 (Wiktionary-derived)",
           "license": "CC-BY-SA-4.0 (data: Wiktionary) + MIT (package)",
           "name": "Portuguese"},
    "ru": {"pkg": "gruut-lang-ru", "bcp47": "ru-RU",
           "data_license": "CC-BY-SA-4.0 (Wiktionary-derived)",
           "license": "CC-BY-SA-4.0 (data: Wiktionary) + MIT (package)",
           "name": "Russian"},
    "sv": None,  # moved to EXTRAS: gruut-lang-sv carries Swedish tone
                 # marks the voices cannot consume — built from the folded
                 # staging union instead (see EXTRAS["sv"])
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
        # the lexicon converts ARPABET→IPA (examples/arpabet) before
        # training, so the WFST now emits the bundle's own IPA — the
        # original reason for shipping without one (ARPABET mismatch)
        # is gone. Trained on the converted rows.
    },
    # WikiPron-harvested locales (issue #5): broad-phonemic scrapes of
    # Wiktionary, CC BY-SA 4.0. Bundles keyed to the piper voice locale
    # codes so the fetcher resolves them by bcp47 prefix. Training FSTs
    # and holdout metrics live in staging/<iso3>/ (harvest_and_train).
    "af": {"kind": "staging", "bcp47": "af", "name": "Afrikaans",
           "path": "staging/afr/merged.tsv", "wikipron": True,
           "source": "wikipron:afr_latn_broad_filtered.tsv",
           "note": "folded (scripts/fold_afrikaans.py): chi->x, ɦ->h, "
                   "ʋ->v, glide breves; 0.386% drop vs the mimic3-af voice"},
    "cy": {"kind": "staging", "bcp47": "cy", "name": "Welsh",
           "path": "staging/cym/merged.tsv", "wikipron": True,
           "source": "wikipron:cym_latn_broad.tsv",
           "note": "folded (scripts/fold_welsh.py): voiceless sonorants "
                   "-> plain; 0.014% drop vs cy_GB-bu_tts"},
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
           "source": "wikipron:hbs_latn_broad_filtered.tsv",
           "note": "Serbo-Croatian pitch accents folded to plain vowels "
                   "(scripts/fold_serbian.py) — 0.000% drop vs the sr voice "
                   "inventory; audit via scripts/audit_voice_tokens.py"},
    "sr": {"kind": "staging", "bcp47": "sr", "name": "Serbian (Cyrillic script)",
           "path": "staging/hbs/lexicon-sr.tsv", "wikipron": True,
           "source": "wikipron:hbs_cyrl_broad_filtered.tsv",
           "note": "pitch accents folded (scripts/fold_serbian.py); "
                   "0.000% drop vs piper-sr_RS-serbski_institut-medium"},
    "ku": {"kind": "staging", "bcp47": "ku", "name": "Kurdish (Kurmanji, Latin script)",
           "path": "staging/kur/merged.tsv", "wikipron": True,
           "source": "wikipron:kmr_latn_broad.tsv",
           "small": "thin extraction (2,132 words) — WFST carries most words",
           "note": "raw scrape needed no convention fold — 0.000% drop vs "
                   "piper-ku_TR-berfin_renas-medium (one pron-side fix: a "
                   "stray í phone in one word, see merge-strategy.txt)"},
    "kk": {"kind": "staging", "bcp47": "kk", "name": "Kazakh",
           "path": "staging/kaz/merged.tsv", "wikipron": True,
           "source": "wikipron:kaz_cyrl_broad.tsv + kaikki fill",
           "note": "kaikki fill grew the scrape 669 -> 2,259 words; "
                   "conventions folded (scripts/fold_kazakh.py): glide "
                   "breves, tongue-position marks, aspiration stripped — "
                   "the kk voices' inventories carry none"},
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
                   "0.235% per-word drop vs lv_LV-aivars"},
    "lt": {"kind": "staging", "bcp47": "lt", "name": "Lithuanian",
           "path": "staging/lit/merged.tsv", "wikipron": True,
           "source": "wikipron:lit_latn_broad.tsv + kaikki fill",
           "note": "kaikki fill grew the scrape 437 -> 25,748 words "
                   "(scripts/fold_lithuanian.py aligns conventions); the "
                   "only lt voice is a coqui grapheme model — bundle "
                   "serves G2P/P2G lookup, not TTS provisioning"},
    "ml": {"kind": "staging", "bcp47": "ml", "name": "Malayalam",
           "path": "staging/mal/merged.tsv", "wikipron": True,
           "source": "wikipron:mal_mlym_broad.tsv",
           "note": "folded (scripts/fold_malayalam.py): ä->aː, ʱ->ʰ, "
                   "dentals; 0.021% drop vs ml_IN-arjun"},
    "mt": {"kind": "staging", "bcp47": "mt", "name": "Maltese",
           "path": "staging/mlt/merged.tsv", "wikipron": True,
           "source": "wikipron:mlt_latn_broad_filtered.tsv"},
    "no": {"kind": "staging", "bcp47": "no", "name": "Norwegian (Bokmål)",
           "path": "staging/nob/merged.tsv", "wikipron": True,
           "source": "wikipron:nob_latn_broad_filtered.tsv",
           "note": "tonal accents folded (scripts/fold_norwegian.py); "
                   "0.000% drop vs no_NO-talesyntese; the expanded 'nob' "
                   "bundle (bcp47 nb) carries the distilled superset"},
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
                   "(scripts/fold_vietnamese.py; ngang=1 huyền=2 sắc=3 "
                   "hỏi=4 ngã=5 nặng=6, per espeak's ph_vietnam phoneme "
                   "definitions — tone 7 is the clause-final ngang "
                   "variant, not lexical); 0.010% drop vs vi_VN-vais1000"},
    "it": {"kind": "staging", "bcp47": "it-IT",
           "name": "Italian",
           "path": "staging/ita/merged.tsv",
           "source": "gruut-lang-it 2.0.1 (PyPI) + WikiPron fills via staging",
           "data_license": "CC-BY-SA-4.0 (Wiktionary-derived)",
           "license": "CC-BY-SA-4.0 (data: Wiktionary) + MIT (package)",
           "note": "staging union (91,133 rows: WikiPron primary, gruut "
                   "fills) — 0.004% drop vs it_IT-dii-high; the gruut-only "
                   "build measured 52.3% WFST exact, the union trains "
                   "stronger"},
    "nl": {"kind": "staging", "bcp47": "nl-NL",
           "name": "Dutch",
           "path": "staging/nld/merged.tsv",
           "source": "gruut-lang-nl 2.0.2 (PyPI) + WikiPron fills via staging",
           "data_license": "CC-BY-SA-4.0 (Wiktionary-derived, confirmed by inspection 2026-11)",
           "license": "CC-BY-SA-4.0 (data: Wiktionary) + MIT (package)",
           "note": "staging union (70,493 rows) — 0.000% drop vs "
                   "nl_NL-alex-medium"},
    "yue": {"kind": "staging", "bcp47": "yue", "name": "Cantonese (Han script)",
            "path": "staging/yue/merged.tsv", "wikipron": True,
            "source": "wikipron:yue_hani_standard_broad.tsv",
            "train_params": {"order": 3, "iters": 6, "gmax": 2, "pmax": 2},
            "note": "Han WFST needs low n-gram order: order-7 hit 30% "
                    "exact / 64% coverage at 19 MB; order-3 reaches "
                    "38.5% exact / 88.4% trainer-coverage at 11 MB. "
                    "RUNTIME caveat: floravox-g2p caps its search at "
                    "65,536 pops — measured through the shipped runtime, "
                    "yue decodes 68% of OOV words, and char-wise "
                    "dictionary fallback completes the ladder (covers "
                    "most, not all, chars: e.g. 设 has no standalone "
                    "entry). Unihan kCantonese is the principled char "
                    "tier (roadmap)"},
    "sv": {"kind": "staging", "bcp47": "sv-SE",
           "name": "Swedish",
           "path": "staging/swe/merged.tsv",
           "source": "gruut-lang-sv 2.0.1 (PyPI) + WikiPron fills via staging",
           "data_license": "CC-BY-SA-4.0 (Wiktionary-derived, confirmed by inspection 2026-11)",
           "license": "CC-BY-SA-4.0 (data: Wiktionary) + MIT (package)",
           "note": "built from the folded staging union, NOT the raw gruut "
                   "pack: gruut-lang-sv marks Swedish pitch accents with "
                   "tone digits the sv voices cannot consume (12,063 rows, "
                   "58.9% word-drop). scripts/fold_swedish.py + the "
                   "variants merge; audited vs sv_SE-alma"},
    "zh": {"kind": "staging", "bcp47": "zh-CN", "name": "Mandarin Chinese (simplified Han)",
           "path": "staging/cmn/wikipron.folded.tsv", "wikipron": True,
           "source": "wikipron:cmn_hani_standard_broad.tsv",
           "train_params": {"order": 3, "iters": 6, "gmax": 2, "pmax": 2},
           "note": "Chao tone contours + sandhi folded to espeak tone digits (scripts/fold_mandarin.py); 0.005% drop vs "
           "piper-zh_CN-huayan-medium (digit words excluded). Han "
           "WFST needs low order: order-3 reaches 53.8% exact at "
           "13 MB. RUNTIME caveat: floravox-g2p caps its search "
           "at 65,536 pops — zh decodes 95% of OOV words through "
           "the shipped runtime; char-wise dictionary fallback "
           "completes the ladder (a few common chars lack "
           "standalone entries — Unihan kMandarin is the "
           "principled char tier, roadmap)"},
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
    hint by relying on auto-detection. Lines may carry trailing `#`
    etymology annotations ("aalborg AO1 L B AO0 R G # place, danish") —
    strip them: ARPABET is A-Z + stress digits only, so `#` can never
    be a phone."""
    n = 0
    with tsv_path.open("w", encoding="utf-8") as out, src.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            if line and not line.startswith(";"):
                if " #" in line:
                    line = line.split(" #", 1)[0].rstrip()
                if line:
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
            # are space-separated ARPABET and unusable by sherpa readers.
            # -j2: compiling the full dep tree on a small CI runner
            # alongside the bundle build has OOMed (rustc exit 101).
            r = subprocess.run(
                ["cargo", "build", "--release", "--quiet", "--jobs", "2",
                 "--example", "arpabet"],
                cwd=ROOT, check=False, capture_output=True, text=True,
            )
            if r.returncode != 0:
                raise SystemExit(
                    "arpabet example failed to build:\n"
                    f"{r.stdout}\n{r.stderr}"
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
            # cmudict trains on the CONVERTED IPA rows, not the raw
            # ARPABET (training on ARPABET panics: empty grapheme table)
            train_src = lexicon_txt if extra.get("kind") == "cmudict" else tsv
            cmd = ["floravox-train-phonetisaurus", str(train_src), str(model_out),
                   "--metrics", str(metrics_out)]
            # per-locale overrides (e.g. Han scripts need lower n-gram
            # order: order-7 WFSTs hit 65% coverage at 82 MB, order-3
            # reaches 88% at 13 MB)
            for flag, key in (("--order", "order"), ("--iters", "iters"),
                              ("--gmax", "gmax"), ("--pmax", "pmax")):
                if key in extra.get("train_params", {}):
                    cmd += [flag, str(extra["train_params"][key])]
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
                if extra.get("small"):
                    notice += f"note: {extra['small']}\n"
                if extra.get("note"):
                    notice += f"note: {extra['note']}\n"
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

    # dedupe: gruut locales moved to EXTRAS keep a None placeholder in
    # LANGUAGES for documentation — without deduping they'd build twice
    # and emit duplicated manifest entries (gzip timestamps make the
    # second build's sha differ from the first)
    langs = args.langs.split(",") if args.langs else \
        list(dict.fromkeys(list(LANGUAGES) + list(EXTRAS)))

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
            print("!! full build — refusing to write a manifest that "
                  "silently drops published bundles")
            for lang in failed:
                print(f"!! missing from this build: {lang}")
            return 1
        # subset builds continue (incremental workflow), but CI and
        # humans get a hard-to-miss warning
        print("::warning::subset build dropped bundles: " + ", ".join(failed))

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
