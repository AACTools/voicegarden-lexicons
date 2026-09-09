#!/usr/bin/env python3
"""Precision audit for neural->FST distillation.

Question: when small+tiny AGREE on a pronunciation, how often is it
correct? Measures on held-out test words (corpus/g2p.test.tsv) —
words the models never saw in training.

For each audited language:
  - sample N test words (single alpha token, like distill.py)
  - run BOTH tiny + small ONNX (identical conventions/distill path)
  - apply the agreement filter
  - report: agreement rate, exact-match precision of agreed
    predictions, PER (phoneme error rate) on agreed predictions

Usage:
  python3 distill_audit.py --lang deu --n 200 &
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from onnx_reference import run  # noqa: E402

import onnxruntime as ort  # noqa: E402

REPO = Path("/home/willwade/GitHub/AACTools/voicegarden-lexicons")
TINY = "/tmp/opencode/tiny-g2p/onnx"
SMALL = "/tmp/opencode/small-g2p/onnx-int8"


def load_test(tag: str) -> list[tuple[str, str]]:
    rows = []
    for line in open(REPO / "corpus/g2p.test.tsv", encoding="utf-8"):
        parts = line.rstrip("\n").split("\t")
        if len(parts) != 3 or parts[0] != tag:
            continue
        word, ipa = parts[1], parts[2]
        if re.fullmatch(r"[^\W\d_]{2,}", word, re.UNICODE):
            rows.append((word, ipa))
    return rows


def norm(s: str) -> str:
    return " ".join(s.split())


FOLD_MAP = str.maketrans({"ɑ": "a", "ɔ": "o", "ɡ": "g"})
FOLD_STRIP = "ːʰ̟̠̈ʲ"


def fold(s: str) -> str:
    """Convention-fold: ɑ→a, ɔ→o, ɡ→g, strip length/aspiration/placement
    diacritics, ignore diphthong tokenization (ai vs a i). For measuring
    'same phone, different symbol' vs real errors when truth and model
    conventions differ (e.g. tur, spa)."""
    out = []
    for tok in norm(s).split():
        tok = tok.translate(FOLD_MAP)
        tok = "".join(c for c in tok if c not in FOLD_STRIP)
        if tok:
            out.append(tok)
    return "".join(out)


def fold_greek(s: str) -> str:
    """Ell-specific convention fold on top of fold(): Greek sources
    disagree systematically on (a) trill vs tap r, (b) whether nasals
    survive before voiced stops (nd/mb/ng vs d/b/g), (c) whether an
    unstressed iota in hiatus is transcribed (a ʝ i a vs a ʝ a). These
    are transcription conventions, not different pronunciations."""
    toks = [t for t in norm(s).split() if t]
    toks = ["ɾ" if t == "r" else t for t in toks]
    out = []
    for i, t in enumerate(toks):
        if t in ("n", "m") and i + 1 < len(toks) and toks[i + 1] in ("d", "b", "g"):
            continue  # de-nasalized before voiced stops
        out.append(t)
    # Iota offglide: drop a standalone "i" whose neighbours are a
    # consonant and a vowel (a ʝ i a -> a ʝ a).
    vowels = set("aeɛiouɔɛʏyɑɒ")
    dropped = []
    for i, t in enumerate(out):
        if (
            t == "i"
            and dropped
            and dropped[-1] not in vowels
            and i + 1 < len(out)
            and out[i + 1] in vowels
        ):
            continue
        dropped.append(t)
    return fold(" ".join(dropped))


def per(ref: str, hyp: str) -> float:
    # phoneme-token levenshtein / len(ref)
    r, h = ref.split(), hyp.split()
    prev = list(range(len(r) + 1))
    for j, hj in enumerate(h, 1):
        cur = [j] + [0] * len(r)
        for i, ri in enumerate(r, 1):
            cur[i] = min(prev[i] + 1, cur[i - 1] + 1,
                         prev[i - 1] + (ri != hj))
        prev = cur
    dist = prev[-1] if h else len(r)
    return dist / max(len(r), 1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", required=True, help="corpus tag of truth rows, e.g. deu")
    ap.add_argument("--prompt-tag", default=None,
                    help="tag used in the model prompt when it differs "
                         "from the truth tag (e.g. truth 'eng', prompt 'eng-US')")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="audit")
    ap.add_argument("--greek-folds", action="store_true",
                    help="apply ell convention folds (r/ɾ, nasal-drop, iota offglide)")
    args = ap.parse_args()

    rows = load_test(args.lang)
    if not rows:
        print(f"{args.lang}: no test rows")
        return
    random.seed(args.seed)
    random.shuffle(rows)
    rows = rows[: args.n]

    so = ort.SessionOptions()
    so.intra_op_num_threads = 1
    so.inter_op_num_threads = 1
    sessions = {}
    for name, d in [("tiny", TINY), ("small", SMALL)]:
        enc = ort.InferenceSession(f"{d}/encoder_model.onnx", so)
        dec = ort.InferenceSession(f"{d}/decoder_model.onnx", so)
        sessions[name] = (enc, dec)

    agreed_exact = agreed_fold = agreed_total = 0
    per_sum = 0.0
    examples = []
    for word, truth in rows:
        prompt = f"<{args.prompt_tag or args.lang}>: {word}"
        try:
            t_out = norm(run(*sessions["tiny"], prompt))
            s_out = norm(run(*sessions["small"], prompt))
        except Exception as e:  # noqa: BLE001
            print(f"  infer fail {word}: {e}", file=sys.stderr)
            continue
        if t_out != s_out:
            continue
        agreed_total += 1
        ok = t_out == norm(truth)
        agreed_exact += ok
        f = fold_greek if args.greek_folds else fold
        agreed_fold += f(t_out) == f(truth)
        p = per(norm(truth), t_out)
        per_sum += p
        if not ok and len(examples) < 8:
            examples.append({"w": word, "want": norm(truth), "got": t_out})

    n_eval = len(rows)
    out = {
        "lang": args.lang,
        "prompt_tag": args.prompt_tag or args.lang,
        "n_test": n_eval,
        "agreed": agreed_total,
        "agreement_rate": round(agreed_total / max(n_eval, 1), 3),
        "precision_exact": round(agreed_exact / max(agreed_total, 1), 3),
        "precision_folded": round(agreed_fold / max(agreed_total, 1), 3),
        "per_on_agreed": round(per_sum / max(agreed_total, 1), 3),
        "wrong_examples": examples,
    }
    outdir = REPO / args.out
    outdir.mkdir(exist_ok=True)
    json.dump(out, open(outdir / f"{args.lang}.audit.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
