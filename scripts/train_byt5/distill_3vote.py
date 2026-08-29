#!/usr/bin/env python3
"""Three-voter precision test for eng distill salvage.

The 2-vote (small+tiny agreement) eng-US precision measured 61.9%.
The WFST tier (gruut-trained, MIT) makes independent errors — if they
are uncorrelated with the neural models', requiring all three to
agree should raise precision at the cost of coverage.

Measures on the same held-out sample as distill_audit.py (seed 42):
  - P(exact | small=tiny)          the shipped-filter baseline
  - P(exact | small=tiny=wfst)     3-vote
  - wfst-only precision            (also: WFST quality on this split)
  - fold variants for convention differences

Usage:
  python3 distill_3vote.py --lang eng --prompt-tag eng-US \
      --phonetisaurus /path/to/phonetisaurus-stem --n 200
"""
from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from onnx_reference import run  # noqa: E402

import onnxruntime as ort  # noqa: E402

REPO = Path("/home/willwade/GitHub/AACTools/voicegarden-lexicons")
FLORAVOX = str(Path.home() / "GitHub/AACTools/floravox/target/debug/floravox")
TINY = "/tmp/opencode/tiny-g2p/onnx"
SMALL = "/tmp/opencode/small-g2p/onnx-int8"


def load_test(tag: str) -> list[tuple[str, str]]:
    rows = []
    for line in open(REPO / "corpus/g2p.test.tsv", encoding="utf-8"):
        parts = line.rstrip("\n").split("\t")
        if len(parts) != 3 or parts[0] != tag:
            continue
        if re.fullmatch(r"[^\W\d_]{2,}", parts[1], re.UNICODE):
            rows.append((parts[1], parts[2]))
    return rows


def norm(s: str) -> str:
    return " ".join(s.split())


FOLD_MAP = str.maketrans({"ɑ": "a", "ɔ": "o", "ɡ": "g"})
FOLD_STRIP = "ːʰ̟̠̈ʲ"


def fold(s: str) -> str:
    out = []
    for tok in norm(s).split():
        tok = tok.translate(FOLD_MAP)
        tok = "".join(c for c in tok if c not in FOLD_STRIP)
        if tok:
            out.append(tok)
    return "".join(out)


def wfst_batch(stem: str, words: list[str]) -> dict[str, str]:
    out = subprocess.run(
        [FLORAVOX, "g2p", "--phonetisaurus", stem, *words],
        capture_output=True, text=True, check=True,
    ).stdout
    res = {}
    for line in out.splitlines():
        if "\t" in line:
            w, p = line.split("\t", 1)
            res[w] = norm(p)
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", required=True)
    ap.add_argument("--prompt-tag", default=None)
    ap.add_argument("--phonetisaurus", required=True)
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rows = load_test(args.lang)
    random.seed(args.seed)
    random.shuffle(rows)
    rows = rows[: args.n]

    wf = wfst_batch(args.phonetisaurus, [w for w, _ in rows])

    so = ort.SessionOptions()
    so.intra_op_num_threads = 1
    so.inter_op_num_threads = 1
    sessions = {}
    for name, d in [("tiny", TINY), ("small", SMALL)]:
        enc = ort.InferenceSession(f"{d}/encoder_model.onnx", so)
        dec = ort.InferenceSession(f"{d}/decoder_model.onnx", so)
        sessions[name] = (enc, dec)

    tag = args.prompt_tag or args.lang
    st = dict(n=0, two_agree=0, two_exact=0, two_fold=0,
              three_agree=0, three_exact=0, three_fold=0,
              wfst_exact=0, wfst_fold=0)
    for word, truth in rows:
        truth_n = norm(truth)
        prompt = f"<{tag}>: {word}"
        try:
            t_out = norm(run(*sessions["tiny"], prompt))
            s_out = norm(run(*sessions["small"], prompt))
        except Exception:  # noqa: BLE001
            continue
        w_out = wf.get(word)
        st["n"] += 1
        if w_out is not None:
            st["wfst_exact"] += w_out == truth_n
            st["wfst_fold"] += fold(w_out) == fold(truth_n)
        if t_out != s_out:
            continue
        st["two_agree"] += 1
        st["two_exact"] += t_out == truth_n
        st["two_fold"] += fold(t_out) == fold(truth_n)
        if w_out is not None and w_out == t_out:
            st["three_agree"] += 1
            st["three_exact"] += t_out == truth_n
            st["three_fold"] += fold(t_out) == fold(truth_n)

    d = {k: v for k, v in st.items()}
    d.update({
        "lang": args.lang, "prompt_tag": tag,
        "two_vote_precision": round(st["two_exact"] / max(st["two_agree"], 1), 3),
        "two_vote_folded": round(st["two_fold"] / max(st["two_agree"], 1), 3),
        "three_vote_precision": round(st["three_exact"] / max(st["three_agree"], 1), 3),
        "three_vote_folded": round(st["three_fold"] / max(st["three_agree"], 1), 3),
        "three_vote_coverage_of_two": round(st["three_agree"] / max(st["two_agree"], 1), 3),
        "wfst_only_precision": round(st["wfst_exact"] / max(st["n"], 1), 3),
        "wfst_only_folded": round(st["wfst_fold"] / max(st["n"], 1), 3),
    })
    outdir = REPO / "audit"
    outdir.mkdir(exist_ok=True)
    json.dump(d, open(outdir / f"{args.lang}.3vote.json", "w"), indent=1)
    print(json.dumps(d, ensure_ascii=False))


if __name__ == "__main__":
    main()
