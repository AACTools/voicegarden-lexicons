#!/usr/bin/env python3
"""Phone-compatibility audit: staged lexicons vs real voice inventories.

Recomputes the corpus-drop numbers quoted in docs/sherpa-coverage.md
from the committed staging files against the vendored `tokens.txt`
inventories in audit/voice-tokens/ — so every "0.00X% drop vs <voice>"
claim is reproducible from the repo, and a fold regression fails the
gate instead of silently shipping phones the voice cannot consume.

Method = the wrapper's runtime ladder (rust-tts-wrapper SHERPA_CATALOG_AUDIT):
  1. exact token in the voice inventory
  2. cluster split — base char + trailing combining marks (Mn/Mc/Me),
     tie bars (U+0361) dropped so affricates char-split
  3. per-character (some inventories ship standalone combining marks)

Usage: python3 scripts/audit_voice_tokens.py [--json out.json]
Exit 1 if any bundle exceeds its expected drop threshold (THRESHOLDS).
"""

from __future__ import annotations

import argparse
import json
import unicodedata
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOKENS = REPO / "audit/voice-tokens"

# staged file -> (voice inventory, documented drop %, per-word threshold %)
# third element None => report-only. GRAPHEME_* entries: the only voice for
# the locale is a grapheme/transliteration model (coqui character tokens,
# mimic3 ASCII transliteration) — no lexicon can serve it; recorded so the
# wrapper never provisions a bundle for those voices expecting TTS gain.
AUDITS = {
    "staging/hun/merged.tsv": ("piper-hu_HU-anna-medium", 0.000, 0.01),
    "staging/kat/kaikki.folded.tsv": ("piper-ka_GE-natia-medium", 0.004, 0.05),
    "staging/kor/kaikki.folded.tsv": ("mimic3-ko_KO-kss_low", 0.13, 0.5),
    "staging/cmn/wikipron.folded.tsv": ("piper-zh_CN-huayan-medium", 0.005, 0.05),
    "staging/vie/kaikki.folded.tsv": ("piper-vi_VN-vais1000-medium", 0.010, 0.1),
    "staging/nep/kaikki.folded.tsv": ("piper-ne_NP-google-medium", 0.05, 0.3),
    "staging/ukr/kaikki.folded.tsv": ("piper-uk_UA-lada-x_low", 0.004, 0.05),
    "staging/lav/kaikki.folded.tsv": ("piper-lv_LV-aivars-medium", 0.235, 1.0),
    "staging/hbs/lexicon-sr.tsv": ("piper-sr_RS-serbski_institut-medium", 0.000, 0.05),
    # coqui-hr-cv is a character-token model (Latin + Cyrillic letters +
    # punctuation, zero IPA symbols — vendored 2026-11 for issue #12):
    # like et/ga/lt/mt/gu, no lexicon can serve it. The hr bundle stays
    # a valid G2P/P2G dictionary product; TTS-wise it is report-only.
    "staging/hbs/lexicon-hr.tsv": ("coqui-hr-cv", 79.496, None),  # grapheme voice
    "staging/fin/merged.tsv": ("piper-fi_FI-harri-medium", 0.005, 0.05),
    # wave-1 WikiPron bundles, first audited 2026-11 (round 2)
    "staging/afr/merged.tsv": ("mimic3-af_ZA-google-nwu_low", 0.386, 2.0),
    "staging/cym/merged.tsv": ("piper-cy_GB-bu_tts-medium", 0.014, 0.5),
    "staging/est/merged.tsv": ("coqui-et-cv", 92.137, None),  # grapheme voice
    "staging/eus/merged.tsv": ("piper-eu_ES-antton-medium", 0.017, 0.5),
    "staging/gle/merged.tsv": ("coqui-ga-cv", 99.497, None),  # grapheme voice
    "staging/guj/merged.tsv": ("mimic3-gu_IN-cmu-indic_low", 75.795, None),  # transliteration
    "staging/kaz/merged.tsv": ("piper-kk_KZ-iseke-x_low", 1.018, 4.0),
    "staging/ltz/merged.tsv": ("piper-lb_LU-marylux-medium", 0.369, 1.0),
    "staging/lit/merged.tsv": ("coqui-lt-cv", 99.977, None),  # grapheme voice
    "staging/mal/merged.tsv": ("piper-ml_IN-arjun-medium", 0.021, 0.5),
    "staging/mlt/merged.tsv": ("coqui-mt-cv", 91.488, None),  # grapheme voice
    "staging/nob/merged.tsv": ("piper-no_NO-talesyntese-medium", 0.000, 0.05),
    "staging/sqi/merged.tsv": ("piper-sq_AL-edon-medium", 0.452, 1.0),
    "staging/swe/merged.tsv": ("piper-sv_SE-alma-medium", 0.114, 0.5),
    "staging/en-GB/lexicon.tsv": ("piper-en_GB-alan-medium", None, 2.0),
    "staging/ita/merged.tsv": ("piper-it_IT-dii-high", None, 1.0),
    "staging/nld/merged.tsv": ("piper-nl_NL-alex-medium", None, 1.0),
}

# expanded-tier artifacts (the tarball lexicons consumers actually
# fetch — merged + distilled rows): guard the shipped file, not just
# staging, so a contaminated distill can never publish again
EXPANDED_AUDITS = {
    "dist/expanded-v2/fin.tar.gz": ("piper-fi_FI-harri-medium", 0.05),
    "dist/expanded-v2/swe.tar.gz": ("piper-sv_SE-alma-medium", 1.0),
    "dist/expanded-v2/nob.tar.gz": ("piper-no_NO-talesyntese-medium", 1.0),
    "dist/sv.tar.gz": ("piper-sv_SE-alma-medium", 0.5),
}
TIE = "\u0361"


def load_vocab(name: str) -> set[str]:
    vocab: set[str] = set()
    for line in (TOKENS / f"{name}.txt").open(encoding="utf-8"):
        parts = line.split()
        if parts:
            vocab.add(parts[0])
    return vocab


def units(phone: str) -> list[str]:
    out: list[str] = []
    for ch in phone:
        if ch == TIE:
            continue
        if out and unicodedata.category(ch) in ("Mn", "Mc", "Me"):
            out[-1] += ch
        else:
            out.append(ch)
    return out


def covered(phone: str, vocab: set[str]) -> bool:
    if phone in vocab:
        return True
    if all(u in vocab for u in units(phone)):
        return True
    return all(c in vocab for c in phone if c != TIE)


def audit(tsv: Path, vocab: set[str]) -> tuple[float, Counter, int]:
    dropped = total = 0
    unmapped: Counter = Counter()
    for line in tsv.open(encoding="utf-8"):
        word, _, pron = line.partition("\t")
        if any(c.isdigit() for c in word):
            continue  # digit words normalized elsewhere (wrapper-side)
        total += 1
        bad = [ph for ph in pron.split() if not covered(ph, vocab)]
        if bad:
            dropped += 1
            unmapped.update(bad)
    return (dropped / total * 100 if total else 0.0), unmapped, total


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", help="write results to this path as JSON")
    args = ap.parse_args()

    results = {}
    failures = []
    for tsv, (voice, documented, threshold) in sorted(AUDITS.items()):
        path = REPO / tsv
        if not path.exists():
            failures.append(f"{tsv}: staged file missing")
            continue
        inv = TOKENS / f"{voice}.txt"
        if not inv.exists():
            failures.append(f"{voice}: vendored inventory missing")
            continue
        drop, unmapped, total = audit(path, load_vocab(voice))
        results[tsv] = {
            "voice": voice,
            "words": total,
            "drop_pct": round(drop, 4),
            "documented_drop_pct": documented,
            "top_unmapped": unmapped.most_common(6),
        }
        line = (f"{tsv.split('/')[1]:<5} vs {voice:<38} "
                f"{drop:7.3f}% drop ({total} words)")
        if documented is not None and abs(drop - documented) > 0.05:
            line += f"  !! documented {documented}%"
            failures.append(
                f"{tsv}: drop {drop:.3f}% != documented {documented}%"
            )
        if threshold is not None and drop > threshold:
            line += f"  !! exceeds threshold {threshold}%"
            failures.append(f"{tsv}: drop {drop:.3f}% > {threshold}%")
        print(line)

    # shipped expanded artifacts (tarball lexicons) against their voices
    import io
    import tarfile
    for tgz, (voice, threshold) in sorted(EXPANDED_AUDITS.items()):
        path = REPO / tgz
        if not path.exists():
            # never pass vacuously: a listed artifact that is missing
            # (typo, unbuilt tier) is a gate failure, not a skip
            failures.append(f"{tgz}: artifact missing — build it or fix the audit table")
            continue
        with tarfile.open(path) as tar:
            lex = tar.extractfile("lexicon.txt")
            if lex is None:
                failures.append(f"{tgz}: no lexicon.txt")
                continue
            text = io.TextIOWrapper(lex, encoding="utf-8").read()
        vocab = load_vocab(voice)
        dropped = total = 0
        for line in text.splitlines():
            word, _, pron = line.partition("\t")
            if any(c.isdigit() for c in word):
                continue
            total += 1
            if any(not covered(ph, vocab) for ph in pron.split()):
                dropped += 1
        drop = dropped / total * 100 if total else 0.0
        results[tgz] = {"voice": voice, "words": total,
                        "drop_pct": round(drop, 4)}
        flag = ""
        if drop > threshold:
            flag = f"  !! exceeds {threshold}%"
            failures.append(f"{tgz}: shipped lexicon drop {drop:.3f}% > {threshold}%")
        print(f"{tgz.split('/')[-1]:<12} shipped vs {voice:<38} "
              f"{drop:7.3f}% drop ({total} words){flag}")

    if args.json:
        Path(args.json).write_text(
            json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8"
        )
    if failures:
        print(f"\nFAILURES ({len(failures)}):")
        for f in failures:
            print(" -", f)
        return 1
    print("\nvoice-token audit OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
