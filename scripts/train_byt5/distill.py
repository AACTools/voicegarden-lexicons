#!/usr/bin/env python3
"""Distill the neural G2P into FST lexicons (pseudo-labeling).

For each language: take wordfreq's top-N words NOT in the existing
lexicon, infer pronunciations with BOTH the small and tiny published
models (batched GPU inference — fast), keep only words where they
AGREE (high-confidence pseudo-labels), and write an expansion TSV
ready for fst-compile.

The agreement filter is the quality control: two independently-sized
models converging on the same IPA is a strong signal; disagreement
throws the word away rather than shipping a bad pronunciation.

Usage (on a CUDA box with the HF checkpoints):
  python3 distill.py --lang en --tag eng-US --n 100000 --out distill/
  python3 distill.py --all            # every wordfreq-covered language
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

# wordfreq code -> corpus tag (subset with real wordfreq coverage and
# our lexicons; tags not listed use the wordfreq code directly)
# wordfreq code -> corpus tag. ONLY tags present in langs.json (the
# trained set) are listed — distilling with an untrained tag produces
# unvalidated output (see distill/quarantine/). bul/cat/ces/hun/lit/
# lav/mkd/rus/ukr/vie are NOT trained; removed until they are.
LANG_MAP = {
    "en": "eng-US", "de": "deu", "es": "spa-ES", "fr": "fra",
    "it": "ita", "pt": "por-BR", "nl": "nld",
    "pl": "pol", "fi": "fin", "sv": "swe",
    "tr": "tur", "ar": "ara", "hi": "hin", "id": "ind",
    "ro": "ron",
    "el": "ell", "da": "dan", "nb": "nob",
    "et": "est",
    "bn": "ben-Rarh", "ta": "tam",
    "ur": "urd", "fa": "fas", "he": "heb",
    "sl": "slv", "sk": "slk",
    "is": "isl",
}

MAX_INPUT = 128
MAX_TARGET = 160


def clean_words(words, min_len=2):
    out = []
    for w in words:
        if len(w) < min_len or not w.isalpha():
            continue
        out.append(w)
    return out


def load_lexicon(staging: Path, tag: str) -> set:
    lex = set()
    for p in (staging / tag / "merged.tsv", staging / tag / "gruut.tsv"):
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                lex.add(line.split("\t")[0].strip().lower())
    return lex


def batched_generate(model, tok, texts, batch=192):
    import torch
    preds = []
    model.eval()
    with torch.no_grad():
        for i in range(0, len(texts), batch):
            chunk = texts[i:i + batch]
            enc = tok(chunk, return_tensors="pt", padding=True,
                      truncation=True, max_length=MAX_INPUT).to("cuda")
            out = model.generate(**enc, max_length=MAX_TARGET,
                                 num_beams=1)
            preds.extend(tok.batch_decode(out, skip_special_tokens=True))
    return preds


def distill_lang(wf_code: str, tag: str, n: int, staging: Path,
                 out_dir: Path, models: dict, min_freq_rank: int = 0):
    from wordfreq import top_n_list

    words = top_n_list(wf_code, n)
    words = clean_words(words[min_freq_rank:])
    lex = load_lexicon(staging, tag)
    oov = [w for w in words if w not in lex]
    if not oov:
        print(f"{tag}: no OOV words, skipping")
        return None

    prompts = [f"<{tag}>: {w}" for w in oov]
    small = batched_generate(models["small"], models["tok"], prompts)
    tiny = batched_generate(models["tiny"], models["tok"], prompts)

    agree = []
    for w, s, t in zip(oov, small, tiny, strict=True):
        if s == t and s.strip():
            agree.append((w, s.strip()))

    stats = {
        "lang": tag, "wordfreq_top": n, "clean": len(words),
        "lexicon": len(lex), "oov": len(oov),
        "agreed": len(agree),
        "agreement_rate": round(len(agree) / max(len(oov), 1), 3),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / f"{tag}.tsv").open("w", encoding="utf-8") as f:
        for w, p in agree:
            f.write(f"{w}\t{p}\n")
    (out_dir / f"{tag}.stats.json").write_text(json.dumps(stats, indent=1))
    print(f"{tag}: {len(oov)} OOV -> {len(agree)} agreed "
          f"({stats['agreement_rate']:.0%}) -> {out_dir}/{tag}.tsv")
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lang", help="wordfreq code (en, de, ...)")
    ap.add_argument("--tag", help="override the corpus tag (e.g. --lang es --tag spa-LatAm "
                    "reuses the es wordlist with the LatAm prompt)")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--n", type=int, default=100_000,
                    help="wordfreq top-N per language")
    ap.add_argument("--staging", default="staging")
    ap.add_argument("--out", default="distill")
    args = ap.parse_args()

    import torch
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    assert torch.cuda.is_available(), "needs CUDA (batched inference)"

    tok = AutoTokenizer.from_pretrained("google/byt5-small")
    print("loading small + tiny (fp32)...", flush=True)
    models = {
        "tok": tok,
        "small": AutoModelForSeq2SeqLM.from_pretrained(
            "willwade/byt5-g2p-multilingual").to("cuda").eval(),
        "tiny": AutoModelForSeq2SeqLM.from_pretrained(
            "willwade/byt5-g2p-multilingual-tiny").to("cuda").eval(),
    }
    print("models loaded", flush=True)

    staging = Path(args.staging)
    out_dir = Path(args.out)
    langs = ([(args.lang, getattr(args, "tag", None) or LANG_MAP.get(args.lang, args.lang))]
             if args.lang else sorted(LANG_MAP.items()))
    # guard: only wordfreq-supported codes
    from wordfreq import available_languages
    wf_ok = available_languages()
    skipped = [(c, t) for c, t in langs if c not in wf_ok]
    if skipped:
        print(f"skipping (no wordfreq data): {[c for c, _ in skipped]}")
    langs = [(c, t) for c, t in langs if c in wf_ok]

    all_stats = []
    for wf_code, tag in langs:
        try:
            s = distill_lang(wf_code, tag, args.n, staging, out_dir, models)
            if s:
                all_stats.append(s)
        except Exception as e:  # noqa: BLE001
            print(f"{tag}: FAILED {e}")

    if all_stats:
        (out_dir / "summary.json").write_text(json.dumps(all_stats, indent=1))
        total_oov = sum(s["oov"] for s in all_stats)
        total_agree = sum(s["agreed"] for s in all_stats)
        print(f"\nTOTAL: {total_oov} OOV -> {total_agree} new lexicon entries "
              f"({total_agree/max(total_oov,1):.0%} agreement)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
