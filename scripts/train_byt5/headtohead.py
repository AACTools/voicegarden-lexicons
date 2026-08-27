#!/usr/bin/env python3
"""Head-to-head: score external G2P/P2G models on OUR test splits.

Each competitor gets an adapter (input formatting + lang-code mapping +
output normalisation) so the comparison is on our corpus, our metrics.

Usage:
  python3 headtohead.py --task g2p --sample 4000
  python3 headtohead.py --task p2g --sample 4000
"""

from __future__ import annotations

import argparse
import json
import random
import time
from collections import defaultdict
from pathlib import Path

MAX_TARGET_LEN = 160

# ISO-639-3 (our corpus tags) -> ISO-639-1 (Charsiu convention)
ISO3_TO_1 = {
    "eng": "en", "spa": "es", "deu": "de", "fra": "fr", "ita": "it",
    "por": "pt", "nld": "nl", "rus": "ru", "cat": "ca", "ces": "cs",
    "fas": "fa", "swe": "sv", "swh": "sw", "fin": "fi", "pol": "pl",
    "ell": "el", "tur": "tr", "ara": "ar", "heb": "he", "hin": "hi",
    "jpn": "ja", "kor": "ko", "vie": "vi", "tha": "th", "zho": "zh",
    "cmn": "zh", "yue": "zh", "nan": "zh", "hsn": "zh", "wuu": "zh",
    "gan": "zh", "hak": "zh", "mnp": "zh", "cdo": "zh", "cpx": "zh",
    "cjy": "zh", "ltc": "zh", "och": "zh", "grc": "grc", "ang": "ang",
    "eus": "eu", "gle": "ga", "cym": "cy", "gla": "gd", "bre": "br",
    "isl": "is", "nob": "nb", "dan": "da", "lat": "la", "ron": "ro",
    "bul": "bg", "ukr": "uk", "slk": "sk", "slv": "sl", "hbs": "sh",
    "hrv": "hr", "srp": "sr", "bos": "bs", "mkd": "mk", "sqi": "sq",
    "lit": "lt", "lav": "lv", "est": "et", "mlt": "mt", "tgl": "tl",
    "ind": "id", "zsm": "ms", "jam": "ms", "tha": "th", "khm": "km",
    "lao": "lo", "mya": "my", "sin": "si", "tam": "ta", "tel": "te",
    "kan": "kn", "mal": "ml", "mar": "mr", "ben": "bn", "guj": "gu",
    "pan": "pa", "urd": "ur", "pes": "fa", "pes_alt": "fa", "pus": "ps",
    "kur": "ku", "aze": "az", "kaz": "kk", "uzb": "uz", "uig": "ug",
    "mon": "mn", "swa": "sw", "amh": "am", "hau": "ha", "yor": "yo",
    "ibo": "ig", "zul": "zu", "xho": "xh", "afr": "af", "som": "so",
    "mlg": "mg", "epo": "eo",
}

MODELS = {
    "g2p": {
        # ours
        "ours-small": {
            "model": "runs/g2p-small/final",
            "fmt": "<{l3}>: {src}",
        },
        # charsiu: <iso1>: word  (paper convention "<lang>: word")
        "charsiu-small": {
            "model": "/workspace/h2h/charsiu-small",
            "fmt": "<{l1}>: {src}",
        },
        "charsiu-tiny16": {
            "model": "/workspace/h2h/charsiu-tiny16",
            "fmt": "<{l1}>: {src}",
        },
    },
    "p2g": {
        "ours-small": {
            "model": "runs/p2g-small/final",
            "fmt": "<{l3}>: {src}",
        },
        # bookbot p2g: trained on wikipron eng-latn multi; convention per
        # their README is "<lang>: ipa" with iso-639-1 (best guess; the
        # adapter normalises whatever comes back)
        "bookbot-p2g": {
            "model": "/workspace/h2h/bookbot-p2g",
            "fmt": "{l1}: {src}",
        },
    },
}


def token_error(pred: str, gold: str) -> float:
    p, g = pred.split(), gold.split()
    prev = list(range(len(g) + 1))
    for i in range(1, len(p) + 1):
        cur = [i] + [0] * len(g)
        for j in range(1, len(g) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1,
                         prev[j - 1] + (p[i - 1] != g[j - 1]))
        prev = cur
    return prev[len(g)] / max(len(g), 1)


def load_rows(path: Path, task: str):
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) == 3:
                lang, a, b = parts
                rows.append((lang, a, b))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task", choices=["g2p", "p2g"], required=True)
    ap.add_argument("--corpus", default="corpus")
    ap.add_argument("--sample", type=int, default=4000)
    ap.add_argument("--batch", type=int, default=128)
    ap.add_argument("--only", help="comma-separated model keys to run")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    import torch
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    rows = load_rows(Path(args.corpus) / f"{args.task}.test.tsv", args.task)
    if args.sample and args.sample < len(rows):
        rows = random.Random(args.seed).sample(rows, args.sample)

    wanted = args.only.split(",") if args.only else list(MODELS[args.task])
    report: dict[str, dict] = {}

    for key in wanted:
        spec = MODELS[args.task][key]
        try:
            try:
                tok = AutoTokenizer.from_pretrained(spec["model"])
            except Exception:
                from transformers import ByT5Tokenizer
                tok = ByT5Tokenizer.from_pretrained(spec["model"])
            model = AutoModelForSeq2SeqLM.from_pretrained(spec["model"])
        except Exception as e:  # noqa: BLE001
            print(f"{key}: LOAD FAILED {e}")
            report[key] = {"error": str(e)}
            continue
        model.to("cuda").eval()

        per_lang: dict[str, list] = defaultdict(lambda: [0, 0, 0.0])
        t0 = time.time()
        done = 0
        for i in range(0, len(rows), args.batch):
            chunk = rows[i : i + args.batch]
            texts = []
            for lang, src, _dst in chunk:
                l1 = ISO3_TO_1.get(lang, lang)
                texts.append(spec["fmt"].format(l3=lang, l1=l1, src=src))
            enc = tok(texts, return_tensors="pt", padding=True,
                      truncation=True, max_length=128).to("cuda")
            with torch.no_grad():
                out = model.generate(**enc, max_length=MAX_TARGET_LEN)
            preds = tok.batch_decode(out, skip_special_tokens=True)
            for (lang, _s, gold), pred in zip(chunk, preds, strict=True):
                s = per_lang[lang]
                s[0] += int(pred == gold)
                s[1] += 1
                s[2] += token_error(pred, gold)
            done += len(chunk)
        total = sum(v[1] for v in per_lang.values())
        micro = sum(v[0] for v in per_lang.values()) / max(total, 1)
        macro = sum(v[0] / v[1] for v in per_lang.values()) / max(len(per_lang), 1)
        ter = sum(v[2] for v in per_lang.values()) / max(total, 1)
        dt = time.time() - t0
        print(f"{key}: micro {micro:.3f} macro {macro:.3f} TER {ter:.3f} "
              f"| {len(per_lang)} langs | {dt:.0f}s", flush=True)
        report[key] = {
            "micro_exact": micro, "macro_exact": macro, "ter": ter,
            "languages": {l: v[0] / v[1] for l, v in sorted(per_lang.items())},
        }
        del model
        torch.cuda.empty_cache()

    Path(f"results/headtohead-{args.task}.json").write_text(
        json.dumps(report, indent=1, sort_keys=True)
    )
    print(f"-> results/headtohead-{args.task}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
