#!/usr/bin/env python3
"""Train a multilingual ByT5 G2P and/or P2G model on the built corpus.

ByT5 reads and writes raw UTF-8 bytes — no tokenizer to build or drift,
every script (hanzi, Arabic, Devanagari, Greek, Latin) handled by
construction. Task direction is the dataset: G2P maps
"<lang>: word" -> "IPA tokens"; P2G maps "<lang>: IPA tokens" -> word.

Usage (single direction):
  python train.py --task g2p --base google/byt5-small --out runs/g2p-small
Both directions, sequential:
  python train.py --task both --base google/byt5-small --out runs/

Then export to ONNX for floravox:
  python export_onnx.py --model runs/g2p-small/final --out onnx/g2p

Hardware: byt5-small trains ~2.7M pairs in roughly a day on one modern
GPU (24 GB VRAM at batch 64; gradient accumulation for less). CPU-only
works for smoke tests (--max-steps 50).

Notes:
  - Validation every --eval-steps on corpus/{task}.val.tsv; the best
    checkpoint by val exact-match is kept (exact match on the target
    string is the metric that matters for G2P).
  - fp16/bf16 enabled automatically when the GPU supports it.
  - Trainer checkpoints to disk; --resume resumes from out-dir.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

MAX_INPUT_LEN = 128   # bytes — covers "<lang>: " + 40-char words
MAX_TARGET_LEN = 160  # bytes — covers 60 phoneme tokens joined


def load_tsv(path: Path, task: str) -> list[tuple[str, str]]:
    """-> (input_text, target_text) with the lang-tag convention applied."""
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 3:
                continue
            lang, a, b = parts
            if task == "g2p":
                out.append((f"<{lang}>: {a}", b))
            else:
                out.append((f"<{lang}>: {a}", b))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task", choices=["g2p", "p2g", "both"], default="both")
    ap.add_argument("--corpus", default="corpus")
    ap.add_argument("--base", default="google/byt5-small",
                    help="base checkpoint (byt5-small ~300M, byt5-base ~580M)")
    ap.add_argument("--out", default="runs")
    ap.add_argument("--epochs", type=float, default=3.0)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--grad-accum", type=int, default=1)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--eval-steps", type=int, default=5000)
    ap.add_argument("--save-steps", type=int, default=5000)
    ap.add_argument("--max-steps", type=int, default=0,
                    help="0 = full run (epochs); set small for smoke tests")
    ap.add_argument("--resume", action="store_true",
                    help="resume from the newest checkpoint in the run dir")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    try:
        import torch
        from datasets import Dataset
        from transformers import (
            AutoModelForSeq2SeqLM,
            AutoTokenizer,
            DataCollatorForSeq2Seq,
            Seq2SeqTrainer,
            Seq2SeqTrainingArguments,
        )
    except ImportError:
        print(
            "transformers/datasets/torch not installed. On the training box:\n"
            "  pip install torch transformers datasets sentencepiece\n"
            "  (accelerate for multi-GPU: pip install accelerate)",
            file=sys.stderr,
        )
        return 2

    tasks = ["g2p", "p2g"] if args.task == "both" else [args.task]
    corpus = Path(args.corpus)

    for task in tasks:
        run_dir = Path(args.out) / f"{task}-{Path(args.base).name}"
        print(f"=== {task}: {args.base} -> {run_dir}")

        train_rows = load_tsv(corpus / f"{task}.train.tsv", task)
        val_rows = load_tsv(corpus / f"{task}.val.tsv", task)
        print(f"train {len(train_rows):,} / val {len(val_rows):,}")

        tokenizer = AutoTokenizer.from_pretrained(args.base)
        model = AutoModelForSeq2SeqLM.from_pretrained(args.base)

        def tokenize(batch):
            # ByT5 is byte-level: the SAME tokenizer serves input and
            # target (no special target tokenizer, and transformers>=5
            # removed as_target_tokenizer anyway).
            enc = tokenizer(
                batch["input"], max_length=MAX_INPUT_LEN, truncation=True,
                padding=False,
            )
            labels = tokenizer(
                batch["target"], max_length=MAX_TARGET_LEN,
                truncation=True, padding=False,
            )
            enc["labels"] = labels["input_ids"]
            return enc

        # Eval subsample: generation over the full 27k val set takes
        # ~34 min per eval; an even-spread 2k slice (4 min) is plenty
        # for best-checkpoint selection. Test-split scoring stays full
        # (eval_onnx.py).
        if len(val_rows) > 2000:
            step = len(val_rows) / 2000
            val_rows = [val_rows[int(i * step)] for i in range(2000)]
        train_ds = Dataset.from_dict(
            {"input": [r[0] for r in train_rows], "target": [r[1] for r in train_rows]}
        ).map(tokenize, batched=True, remove_columns=["input", "target"])
        val_ds = Dataset.from_dict(
            {"input": [r[0] for r in val_rows], "target": [r[1] for r in val_rows]}
        ).map(tokenize, batched=True, remove_columns=["input", "target"])

        def compute_metrics(eval_pred):
            preds, labels = eval_pred
            if isinstance(preds, tuple):
                preds = preds[0]
            if not _debug_dumped[0]:
                _debug_dumped[0] = True
                import numpy as _np
                _p = preds if not hasattr(preds, "argmax") else preds
                with open("/workspace/metrics_debug.txt", "w") as _f:
                    _f.write(f"preds type {type(_p).__name__} shape {getattr(_p, 'shape', None)}\n")
                    _f.write(f"labels type {type(labels).__name__} shape {getattr(labels, 'shape', None)}\n")
                    _arr_p = _np.asarray(_p)
                    _arr_l = _np.asarray(labels)
                    _f.write(f"preds[0][:30] {_arr_p[0][:30].tolist()}\n")
                    _f.write(f"labels[0][:30] {_arr_l[0][:30].tolist()}\n")
                    _f.write(f"preds sample rows: {_arr_p[:3, :12].tolist()}\n")

            def trim(ids, ignore):
                out = []
                for t in ids:
                    t = int(t)
                    if t == ignore or t == 1 or t == 0:  # -100, EOS, PAD
                        break
                    out.append(t)
                return out

            exact = 0
            total = 0
            for p, l in zip(preds, labels, strict=False):
                # Generated sequences keep the leading decoder-start
                # token (0); labels start at content. Skip it.
                p = p[1:] if len(p) and int(p[0]) == 0 else p
                lp = trim(p, -2)   # generated: no -100 present
                ll = trim(l, -100)
                total += 1
                if lp == ll:
                    exact += 1
            return {"exact_match": exact / max(total, 1)}

        # Resume: point Trainer at the newest saved checkpoint.
        import glob as _glob
        ckpts = sorted(
            _glob.glob(str(run_dir / "checkpoint-*")),
            key=lambda p: int(p.rsplit("-", 1)[1]),
        )
        resume_from = ckpts[-1] if (args.resume and ckpts) else None

        use_fp = "bf16" if torch.cuda.is_bf16_supported() else "fp16"
        kwargs = dict(
            output_dir=str(run_dir),
        )
        if args.max_steps > 0:
            # transformers 4.x: epochs AND max_steps together let epochs
            # win; pass ONLY max_steps for a hard cap.
            kwargs["max_steps"] = args.max_steps
        else:
            kwargs["num_train_epochs"] = args.epochs
        kwargs.update(
            per_device_train_batch_size=args.batch,
            per_device_eval_batch_size=args.batch,
            gradient_accumulation_steps=args.grad_accum,
            learning_rate=args.lr,
            # transformers 5 dropped warmup_ratio; fixed steps equivalent
            warmup_steps=max(10, int(0.03 * (args.max_steps or 1))),
            lr_scheduler_type="cosine",
            eval_strategy="steps",
            eval_steps=args.eval_steps,
            save_strategy="steps",
            save_steps=args.save_steps,
            save_total_limit=2,
            load_best_model_at_end=True,
            metric_for_best_model="exact_match",
            greater_is_better=True,
            predict_with_generate=True,
            generation_max_length=MAX_TARGET_LEN,
            fp16=use_fp == "fp16",
            bf16=use_fp == "bf16",
            logging_steps=200,
            seed=args.seed,
            report_to=[],
        )
        targs = Seq2SeqTrainingArguments(**kwargs)

        trainer = Seq2SeqTrainer(
            model=model,
            args=targs,
            train_dataset=train_ds,
            eval_dataset=val_ds,
            data_collator=DataCollatorForSeq2Seq(tokenizer, model=model),
            compute_metrics=compute_metrics,
        )
        trainer.train(resume_from_checkpoint=resume_from)

        final = run_dir / "final"
        trainer.save_model(str(final))
        tokenizer.save_pretrained(str(final))
        print(f"saved {final}")

        # keep only the final export + the last checkpoint (disk hygiene)
        for ckpt in sorted(run_dir.glob("checkpoint-*"))[:-1]:
            shutil.rmtree(ckpt, ignore_errors=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
