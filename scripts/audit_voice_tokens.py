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
    "staging/fin/merged.tsv": ("piper-fi_FI-harri-medium", 0.005, 0.05),
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
