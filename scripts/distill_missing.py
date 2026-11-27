#!/usr/bin/env python3
"""Distill the most frequent missing words — only when independent systems agree.

Wiktionary carries no IPA for many function words (verified in the raw
kaikki dump: Norwegian `men`, `da`, `også` have empty `sounds`, `eller`
has audio only), so the top-frequency tokens of running text fall
through the dictionary to the guesser on every use. This closes that
gap with a conservative, multi-system rule:

  1. the ByT5 G2P small and tiny models (v2) produce the same pronunciation;
  2. every phone is in the target voice's inventory;
  3. every phone token is one the seed dictionary itself uses (convention);
  4. where espeak-ng has the language: its pronunciation of the word,
     reduced to a segment skeleton and with its notation mapped onto the
     seed's (the map is LEARNED from the seed, never hand-tuned), equals
     the distilled row's skeleton. The voices were trained on espeak-ng's
     phonemes, so this is an independent, rule-based third voter.

Rule 1 alone is NOT enough: on held-out rows the agreed outputs are
correct 33-73% of the time (run --validate to measure it per language),
which is at or below the WFST guesser those words would otherwise
reach. `--validate LANG=TSV` reports how often agreed rows match a known
reference, with and without rule 4, so shipping decisions rest on a
measurement rather than on inspection.

The vocabulary comes from a running-text sample (the scoping audit's
cached Wikipedia text). Rows are written as a separate staging file with
a provenance sidecar — they are model-generated, not transcriptions.

The language tag must exist in the models' training (v2): languages
added after August 2026 (kur, tsn) cannot be distilled this way.

Usage: scripts/distill_missing.py --iso afr --lang afr --wiki runs-cv-scope/af.txt \
          --dict staging/afr/merged.tsv --voice mimic3-af_ZA-google-nwu_low \
          --top 200 --out staging/afr/function-words.tsv \
          --validate afr=runs-cv-scope/afr-val.tsv
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import p2g_roundtrip as rt  # noqa: E402
from audit_voice_tokens import covered, load_vocab  # noqa: E402
from scope_vocabulary import dominant_script, tokenize  # noqa: E402

MIN_LEN = 2
# espeak-ng voice per language tag (espeak-ng 1.52 has no Kazakh/Nepali)
ESPEAK = {"afr": "af", "nob": "nb", "sqi": "sq", "ltz": "lb"}
# a notation map entry needs this many aligned occurrences and this share
MAP_SUPPORT, MAP_DOMINANCE = 10, 0.8
STRIP = set(" ˈˌ.ːˑ|‖-")
VOWELS = set("aeiouyæøœɑɒʌɔɤɪʏʊɘɵəɚɝɨ")


def skeleton(phones: str) -> list[str]:
    """Base segments only: stress, length, syllable and tie marks, all
    combining marks and doubled consonants are dropped, so the comparison
    is about segments, not notation."""
    s = unicodedata.normalize("NFC", phones).replace("\u200d", "")
    out: list[str] = []
    for ch in s:
        if ch in STRIP or ch == "\u0361" or unicodedata.category(ch).startswith("M"):
            continue
        out.append(ch)
    return collapse(out)


def collapse(segs: list[str]) -> list[str]:
    out: list[str] = []
    for c in segs:
        # doubled consonants are one segment (geminates are notation here)
        if out and c == out[-1] and c not in VOWELS:
            continue
        out.append(c)
    return out


def espeak_ipa(voice: str, word: str) -> str:
    r = subprocess.run(["espeak-ng", "-v", voice, "-q", "--ipa=3", word],
                       capture_output=True, text=True)
    return r.stdout.strip()


def learn_notation(voice: str, seed_rows: list[tuple[str, str]],
                   sample: int = 600) -> dict[str, str]:
    """espeak symbol -> seed symbol, from seed rows whose skeletons align
    positionally. Only dominant, well-supported pairs are kept."""
    pairs: dict[str, Counter] = defaultdict(Counter)
    for w, p in random.Random(3).sample(seed_rows, min(sample, len(seed_rows))):
        e, s = skeleton(espeak_ipa(voice, w)), skeleton(p)
        if len(e) == len(s):
            for a, b in zip(e, s):
                pairs[a][b] += 1
    out = {}
    for a, c in pairs.items():
        sym, n = c.most_common(1)[0]
        if sum(c.values()) >= MAP_SUPPORT and n / sum(c.values()) >= MAP_DOMINANCE:
            out[a] = sym
    return out


# English closed-class tokens that leak into Wikipedia running text
# through templates and citations — never words of the target language.
# Deliberately per language: cognates are real words ("in", "is", "by"
# and "was" are Afrikaans; "to", "is", "at", "by" and "for" are
# Norwegian Bokmål) and must not be filtered.
FOREIGN = {
    "afr": {"the", "of", "and", "with", "from", "this", "that", "on", "at", "as"},
    "nob": {"the", "of", "and", "in", "with", "from", "this", "that", "was", "on"},
    "ltz": {"the", "of", "and", "to", "is", "on", "at", "by", "from",
            "this", "that", "with", "was"},
    "sqi": {"the", "of", "and", "in", "to", "is", "on", "at", "by", "from",
            "this", "that", "with", "was"},
    # kaz / nep are non-Latin scripts: the dominant-script filter already
    # drops English intrusions
}


def wilson(k: int, n: int) -> tuple[float, float]:
    z = 1.96
    if not n:
        return 0.0, 1.0
    centre = (k + z * z / 2) / (n + z * z)
    half = z * ((k * (n - k) / n + z * z / 4) ** 0.5 / n)
    return max(centre - half, 0.0), min(centre + half, 1.0)


def norm(word: str) -> str:
    return unicodedata.normalize("NFC", word.strip()).casefold()


def read_rows(path: Path) -> list[tuple[str, str]]:
    rows: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        w, _, phones = line.partition("\t")
        if w.strip() and phones.strip() and " " not in w.strip() \
                and not w.strip().startswith("-") and not w.strip().endswith("-"):
            rows.setdefault(norm(w), phones.strip())
    return sorted(rows.items())


def validate(vlang: str, path: Path, note: dict[str, str], voice: str | None,
             run) -> dict:
    """Precision of the rules on held-out rows with a known reference."""
    rows = read_rows(path)
    a, b = run(rows)
    agreed = [(w, x, ref) for (w, ref), x, y in zip(rows, a, b) if x and x == y]
    base_exact = sum(rt.strict(x) == rt.strict(r) for (_w, r), x in zip(rows, a))
    k2 = sum(rt.strict(x) == rt.strict(ref) for _w, x, ref in agreed)
    third = [(w, x, ref) for w, x, ref in agreed
             if voice is None or [note.get(c, c) for c in skeleton(espeak_ipa(voice, w))]
             == skeleton(x)]
    k3 = sum(rt.strict(x) == rt.strict(ref) for _w, x, ref in third)
    res = {"held_out_rows": len(rows), "agreed": len(agreed),
           "small_alone_exact": round(base_exact / max(len(rows), 1), 4),
           "two_vote_exact": round(k2 / max(len(agreed), 1), 4),
           "three_way_rows": len(third),
           "three_way_exact": round(k3 / max(len(third), 1), 4)}
    lo2, hi2 = wilson(k2, len(agreed))
    lo3, hi3 = wilson(k3, len(third))
    print(f"validate {vlang}: {len(rows)} held-out rows; small alone exact "
          f"{res['small_alone_exact']:.1%}; agree on {len(agreed)} "
          f"({len(agreed) / max(len(rows), 1):.0%}), of which exact "
          f"{res['two_vote_exact']:.1%} (95% CI {lo2:.0%}-{hi2:.0%})")
    if voice is not None:
        print(f"    with the espeak-ng voter: {len(third)} of the agreed rows pass, "
              f"exact {res['three_way_exact']:.1%} (95% CI {lo3:.0%}-{hi3:.0%})")
    return res


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
    ap.add_argument("--validate", action="append", default=[], metavar="LANG=TSV",
                    help="held-out rows (word<TAB>phones) with a known reference: "
                         "report how often an agreed pronunciation is actually "
                         "right. Repeatable.")
    ap.add_argument("--no-espeak", action="store_true",
                    help="skip the espeak-ng third voter even if the language has one")
    args = ap.parse_args()

    small = rt.Byt5(rt.model_dir(args.models, "g2p", "small"), args.threads, args.provider)
    tiny = rt.Byt5(rt.model_dir(args.models, "g2p", "tiny"), args.threads, args.provider)

    def run(rows: list[tuple[str, str]]) -> tuple[list[str], list[str]]:
        out = []
        for model in (small, tiny):
            got: list[str] = []
            for i in range(0, len(rows), 128):
                got += model.generate([f"<{args.lang}>: {w}" for w, _p in rows[i:i + 128]])
            out.append([o.strip() for o in got])
        return out[0], out[1]

    seed_rows = read_rows(args.dict)
    seed_tokens = {t for _w, p in seed_rows for t in p.split()}
    voice = None if args.no_espeak else ESPEAK.get(args.lang)
    note = learn_notation(voice, seed_rows) if voice else {}
    if note:
        print(f"espeak-ng notation learned from the seed: {note}")

    validations = {}
    for item in args.validate:
        vlang, _, vpath = item.partition("=")
        if vlang != args.lang:
            print(f"skipping --validate {vlang}: this run's language tag is {args.lang}")
            continue
        validations[vlang] = validate(vlang, Path(vpath), note, voice, run)

    dictionary = {norm(w) for w, _p in seed_rows}
    counts = tokenize(args.wiki.read_text(encoding="utf-8"))
    total = sum(counts.values())
    script = Counter(dominant_script(t) for t in counts).most_common(1)[0][0]
    missing = [t for t, _n in counts.most_common()
               if t not in dictionary and len(t) >= MIN_LEN
               and dominant_script(t) == script
               and t not in FOREIGN.get(args.lang, set())][: args.top]
    if not missing:
        print("nothing missing")
        return 0
    share = sum(counts[t] for t in missing) / total
    print(f"{args.iso}: top {len(missing)} missing types cover {share:.1%} "
          f"of running-text tokens in the sample")

    vocab = load_vocab(args.voice)
    a, b = run([(w, "") for w in missing])
    kept, disagree, uncovered, off_convention, espeak_diff = [], [], [], [], []
    for w, x, y in zip(missing, a, b):
        if x != y or not x:
            disagree.append((w, x, y))
            continue
        if not all(covered(p, vocab) for p in x.split()):
            uncovered.append((w, x))
            continue
        if not all(t in seed_tokens for t in x.split()):
            off_convention.append((w, x))
            continue
        if voice and [note.get(c, c) for c in skeleton(espeak_ipa(voice, w))] != skeleton(x):
            espeak_diff.append((w, x, espeak_ipa(voice, w)))
            continue
        kept.append((w, x))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(f"{w}\t{p}\n" for w, p in kept), encoding="utf-8")
    kept_share = sum(counts[w] for w, _p in kept) / total
    summary = {
        "iso": args.iso, "lang": args.lang, "voice": args.voice,
        "espeak_voice": voice, "espeak_notation": note,
        "missing_types": len(missing), "missing_token_share": round(share, 4),
        "kept": len(kept), "kept_token_share": round(kept_share, 4),
        "disagreed": len(disagree), "not_in_voice_inventory": len(uncovered),
        "off_convention": len(off_convention), "espeak_disagreed": len(espeak_diff),
        "rule": "willwade/byt5-g2p-multilingual v2 small+tiny agreement"
                + (" + espeak-ng segment skeleton (notation mapped from the seed)"
                   if voice else "")
                + " + every phone in the target voice inventory"
                  " + every token already used by the seed dictionary",
        "validation": validations,
        "disagreements": [{"word": w, "small": x, "tiny": y} for w, x, y in disagree],
        "uncovered": [{"word": w, "phones": p} for w, p in uncovered],
        "off_convention_rows": [{"word": w, "phones": p} for w, p in off_convention],
        "espeak_disagreements": [{"word": w, "phones": p, "espeak": e}
                                 for w, p, e in espeak_diff],
    }
    sidecar = args.out.with_suffix(".provenance.json")
    sidecar.write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    print(f"kept {len(kept)} (they cover {kept_share:.1%} of tokens); "
          f"{len(disagree)} disagreed, {len(uncovered)} not in the voice inventory, "
          f"{len(off_convention)} outside the seed's conventions"
          + (f", {len(espeak_diff)} not confirmed by espeak-ng" if voice else ""))
    for w, p in kept[:12]:
        print(f"  {counts[w]:>6}  {w:<14} {p}")
    print(f"wrote {args.out} + {sidecar.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
