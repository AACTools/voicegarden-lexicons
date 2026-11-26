#!/usr/bin/env python3
"""Distill the most frequent missing words with the 2-vote ByT5 rule.

Wiktionary carries no IPA for many function words (verified in the raw
kaikki dump: Norwegian `men`, `da`, `også` have empty `sounds`, `eller`
has audio only) — so the top-frequency tokens of running text fall
through the dictionary to the guesser on every use. This closes that
gap with the archive's established distillation rule (the expanded
tier's): ask the ByT5 G2P small and tiny models (v2) to pronounce each
missing word and keep it only when both produce the same pronunciation
AND every phone is in the target voice's inventory.

The vocabulary comes from a running-text sample (the scoping audit's
cached Wikipedia text, runs-cv-scope/<wiki>.txt): the N most frequent
tokens absent from the bundle's dictionary. Rows are written as a
separate staging file with a provenance sidecar — they are
model-generated, not transcriptions, and are labelled as such.

The language tag must exist in the models' training (v2): languages
added after August 2026 (kur, tsn) cannot be distilled this way.

Usage: scripts/distill_missing.py --iso afr --lang afr --wiki runs-cv-scope/af.txt \
          --dict staging/afr/merged.tsv --voice mimic3-af_ZA-google-nwu_low \
          --top 200 --out staging/afr/function-words.tsv
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import p2g_roundtrip as rt  # noqa: E402
from audit_voice_tokens import covered, load_vocab  # noqa: E402
from scope_vocabulary import dominant_script, tokenize  # noqa: E402

MIN_LEN = 2
# English closed-class tokens that leak into Wikipedia running text
# through templates and citations — never words of the target language.
# Deliberately per language: cognates are real words ("in", "is", "by"
# and "was" are Afrikaans; "to", "is", "at", "by" and "for" are
# Norwegian Bokmål) and must not be filtered.
FOREIGN = {
    "afr": {"the", "of", "and", "with", "from", "this", "that", "on", "at", "as"},
    "nob": {"the", "of", "and", "in", "with", "from", "this", "that", "was", "on"},
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--iso", required=True, help="staging dir (afr, nob, ...)")
    ap.add_argument("--lang", required=True, help="model language tag (afr, nob, ...)")
    ap.add_argument("--wiki", required=True, type=Path, help="running-text sample")
    ap.add_argument("--dict", required=True, type=Path, help="bundle dictionary TSV")
    ap.add_argument("--voice", required=True, help="vendored inventory name")
    ap.add_argument("--top", type=int, default=200)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--models", type=Path, default=REPO / "onnx-models")
    ap.add_argument("--provider", default="cpu", choices=("cpu", "cuda"))
    ap.add_argument("--threads", type=int, default=0)
    args = ap.parse_args()

    dictionary: set[str] = set()
    for line in args.dict.read_text(encoding="utf-8").splitlines():
        w, _, phones = line.partition("\t")
        if phones.strip():
            dictionary.add(unicodedata.normalize("NFC", w.strip()).casefold())

    counts = tokenize(args.wiki.read_text(encoding="utf-8"))
    script = Counter(dominant_script(t) for t in counts).most_common(1)[0][0]
    missing = [t for t, _n in counts.most_common()
               if t not in dictionary and len(t) >= MIN_LEN
               and dominant_script(t) == script
               and t not in FOREIGN.get(args.lang, set())][: args.top]
    if not missing:
        print("nothing missing")
        return 0
    share = sum(counts[t] for t in missing) / sum(counts.values())
    print(f"{args.iso}: top {len(missing)} missing types cover {share:.1%} "
          f"of running-text tokens in the sample")

    small = rt.Byt5(rt.model_dir(args.models, "g2p", "small"), args.threads, args.provider)
    tiny = rt.Byt5(rt.model_dir(args.models, "g2p", "tiny"), args.threads, args.provider)
    vocab = load_vocab(args.voice)

    def ask(model: rt.Byt5) -> list[str]:
        return [o.strip() for o in model.generate([f"<{args.lang}>: {w}" for w in missing])]

    a, b = ask(small), ask(tiny)
    kept, disagree, uncovered = [], [], []
    for w, x, y in zip(missing, a, b):
        if x != y or not x:
            disagree.append((w, x, y))
            continue
        if not all(covered(p, vocab) for p in x.split()):
            uncovered.append((w, x))
            continue
        kept.append((w, x))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(f"{w}\t{p}\n" for w, p in kept), encoding="utf-8")
    kept_share = sum(counts[w] for w, _p in kept) / sum(counts.values())
    summary = {
        "iso": args.iso, "lang": args.lang, "voice": args.voice,
        "missing_types": len(missing), "missing_token_share": round(share, 4),
        "kept": len(kept), "kept_token_share": round(kept_share, 4),
        "disagreed": len(disagree), "not_in_voice_inventory": len(uncovered),
        "rule": "willwade/byt5-g2p-multilingual v2 small+tiny agreement "
                "+ every phone in the target voice inventory",
        "disagreements": [{"word": w, "small": x, "tiny": y} for w, x, y in disagree],
        "uncovered": [{"word": w, "phones": p} for w, p in uncovered],
    }
    sidecar = args.out.with_suffix(".provenance.json")
    sidecar.write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    print(f"kept {len(kept)} (they cover {kept_share:.1%} of tokens); "
          f"{len(disagree)} disagreed, {len(uncovered)} not in the voice inventory")
    for w, p in kept[:25]:
        print(f"  {counts[w]:>6}  {w:<14} {p}")
    print(f"wrote {args.out} + {sidecar.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
