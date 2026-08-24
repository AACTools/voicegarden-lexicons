#!/usr/bin/env python3
"""Export a trained ByT5 G2P/P2G checkpoint to ONNX for floravox.

Produces the exact layout floravox's Byt5G2p / ByT5P2g loaders expect:
  onnx/<task>/encoder_model.onnx
  onnx/<task>/decoder_model.onnx

Programmatic export via optimum.onnxruntime (robust against CLI
argument drift across optimum 1.x/2.x): loads the checkpoint,
ORTModelForSeq2SeqLM.from_pretrained(..., export=True), save_pretrained,
then keeps only the two sessions floravox needs.

Usage:
  python export_onnx.py --model runs/g2p-byt5-small/final --task g2p --out onnx
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

KEEP = ("encoder_model.onnx", "decoder_model.onnx")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", required=True, help="checkpoint dir (final)")
    ap.add_argument("--task", choices=["g2p", "p2g"], required=True)
    ap.add_argument("--out", default="onnx")
    args = ap.parse_args()

    out = Path(args.out) / args.task
    tmp = out.parent / f".{args.task}-export-tmp"
    if out.exists():
        print(f"{out} exists — remove it to re-export", file=sys.stderr)
        return 1

    try:
        from optimum.onnxruntime import ORTModelForSeq2SeqLM
        from transformers import AutoTokenizer
    except ImportError:
        print(
            "optimum-onnx not installed. On the training box:\n"
            "  pip install optimum-onnx",
            file=sys.stderr,
        )
        return 2

    print(f"exporting {args.model} -> {tmp}")
    model = ORTModelForSeq2SeqLM.from_pretrained(args.model, export=True)
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model.save_pretrained(str(tmp))
    tokenizer.save_pretrained(str(tmp))

    out.mkdir(parents=True, exist_ok=True)
    for name in KEEP:
        src = tmp / name
        if not src.exists():
            print(
                f"MISSING {name} in export output — layout changed? "
                f"contents: {sorted(p.name for p in tmp.glob('*.onnx'))}",
                file=sys.stderr,
            )
            return 1
        shutil.move(str(src), out / name)
    shutil.rmtree(tmp, ignore_errors=True)

    (out / "README.txt").write_text(
        f"floravox {args.task} ByT5 tier — exported from {args.model}\n"
        f"load with: Byt5G2p::load(\"{out / 'encoder_model.onnx'}\", "
        f"\"{out / 'decoder_model.onnx'}\")\n"
        f"input convention: \"<lang>: <text>\", lang = ISO 639-3\n"
    )
    print(f"{out}: {list(KEEP)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
