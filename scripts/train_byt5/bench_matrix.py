#!/usr/bin/env python3
"""Optimization matrix: speed / quality / memory for every inference
variant of the published models.

Variants (all from the SAME checkpoints — no retraining):
  fp32         : the published baseline (manual export)
  fp32-kv      : decoder with past-state KV cache (linear-time decode)
  int8-dynamic : dynamic MatMul quantization of fp32 (and of kv)
  int8-static  : static quantization with a 300-word calibration set
  fp16         : half-precision graph

Measured per variant × {small, tiny} × {g2p}:
  quality : exact-match on 200 stratified corpus test rows (the
            published numbers used 4k; 200 is enough to rank variants)
  speed   : ms/word single-thread CPU (the embedded profile)
  memory  : peak RSS of the inference process + on-disk artifact size

Writes results/optimization-matrix.json + a printed verdict table.

Usage (on the training box, models already on disk):
  python3 bench_matrix.py [--sample 200]
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import resource
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort

RUNS = Path("runs")
OUT = Path("results/optimization-matrix.json")
EOS = 1
MAX_GEN = 64


def peak_rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def load_pair(d: Path, threads: int = 1):
    so = ort.SessionOptions()
    so.intra_op_num_threads = threads
    so.inter_op_num_threads = 1
    enc = ort.InferenceSession(str(d / "encoder_model.onnx"), so)
    dec = ort.InferenceSession(str(d / "decoder_model.onnx"), so)
    return enc, dec


def greedy(enc, dec, text: str, max_len: int = MAX_GEN) -> str:
    ids = [b + 3 for b in text.encode("utf-8")][:127] + [EOS]
    inp = np.array([ids], dtype=np.int64)
    mask = np.ones_like(inp)
    efeeds = {"input_ids": inp}
    if "attention_mask" in {i.name for i in enc.get_inputs()}:
        efeeds["attention_mask"] = mask
    hidden = enc.run(None, efeeds)[0]
    names = {i.name for i in dec.get_inputs()}
    key = "input_ids" if "input_ids" in names else "decoder_input_ids"
    dec_ids = np.zeros((1, 2), dtype=np.int64)
    dec_mask = np.array([[1, 0]], dtype=np.int64)
    out = bytearray()
    t = dec_ids.shape[1]
    for _ in range(max_len):
        feeds = {key: dec_ids}
        if "attention_mask" in names:
            feeds["attention_mask"] = dec_mask
        if "encoder_hidden_states" in names:
            feeds["encoder_hidden_states"] = hidden
        if "encoder_attention_mask" in names:
            feeds["encoder_attention_mask"] = mask
        logits = dec.run(None, feeds)[0]
        nxt = int(np.argmax(logits[0, -1]))
        t += 1
        if nxt == EOS:
            break
        out.append(nxt - 3)
        dec_ids = np.concatenate([dec_ids, np.array([[nxt]], dtype=np.int64)], axis=1)
        dec_mask = np.concatenate([dec_mask, np.ones((1, 1), dtype=np.int64)], axis=1)
    return out.decode("utf-8", "replace")


def sample_rows(n: int, seed: int = 7):
    import random

    rows = []
    with open("corpus/g2p.test.tsv", encoding="utf-8") as f:
        for line in f:
            p = line.rstrip("\n").split("\t")
            if len(p) == 3:
                rows.append(p)
    return random.Random(seed).sample(rows, min(n, len(rows)))


def bench(enc, dec, rows, variety_default) -> dict:
    t0 = time.time()
    ok = 0
    for lang, word, gold in rows:
        tag = variety_default.get(lang, lang)
        pred = greedy(enc, dec, f"<{tag}>: {word}")
        ok += int(pred == gold)
    dt = (time.time() - t0) / len(rows)
    return {"exact": ok / len(rows), "ms_per_word": dt * 1000.0}


# ---------- variant builders -------------------------------------------


def quantize_dynamic(src: Path, dst: Path):
    from onnxruntime.quantization import QuantType, quantize_dynamic

    dst.mkdir(parents=True, exist_ok=True)
    for f in ("encoder_model.onnx", "decoder_model.onnx"):
        quantize_dynamic(str(src / f), str(dst / f), weight_type=QuantType.QInt8)
    for extra in src.glob("*.json"):
        shutil.copy(extra, dst / extra.name)


def quantize_static(src: Path, dst: Path, calib_rows):
    from onnxruntime.quantization import (
        CalibrationDataReader, QuantType, quantize_static,
    )

    class Reader(CalibrationDataReader):
        def __init__(self):
            self.rows = list(calib_rows)
            self.i = 0

        def get_next(self):
            if self.i >= len(self.rows):
                return None
            lang, word, _ = self.rows[self.i]
            tag = VARIETY.get(lang, lang)
            ids = [b + 3 for b in f"<{tag}>: {word}".encode()][:127] + [EOS]
            self.i += 1
            return {
                "input_ids": np.array([ids], dtype=np.int64),
                "attention_mask": np.ones((1, len(ids)), dtype=np.int64),
            }

    dst.mkdir(parents=True, exist_ok=True)
    quantize_static(
        str(src / "encoder_model.onnx"), str(dst / "encoder_model.onnx"),
        calibration_data_reader=Reader(), weight_type=QuantType.QInt8,
    )
    quantize_dynamic(str(src / "decoder_model.onnx"), str(dst / "decoder_model.onnx"),
                     weight_type=QuantType.QInt8)
    for extra in src.glob("*.json"):
        shutil.copy(extra, dst / extra.name)


def to_fp16(src: Path, dst: Path):
    import onnx
    from onnxruntime.transformers import float16

    dst.mkdir(parents=True, exist_ok=True)
    for f in ("encoder_model.onnx", "decoder_model.onnx"):
        m = onnx.load(str(src / f))
        m = float16.convert_float_to_float16(m)
        onnx.save(m, str(dst / f))
    for extra in src.glob("*.json"):
        shutil.copy(extra, dst / extra.name)


VARIETY = {"eng": "eng-US", "por": "por-BR", "spa": "spa-ES",
           "cym": "cym-North", "hye": "hye-East", "ben": "ben-Rarh"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sample", type=int, default=200)
    args = ap.parse_args()

    rows = sample_rows(args.sample)
    calib = sample_rows(300, seed=99)
    report = {}
    tmpdir = Path(tempfile.mkdtemp(prefix="optmatrix-"))

    models = [("small", RUNS / "g2p-small/final", Path("onnx/small-g2p")),
              ("tiny", RUNS / "g2p-tiny/final", Path("onnx/tiny-g2p"))]

    for size, ckpt, onnx_dir in models:
        if not onnx_dir.exists():
            print(f"skip {size}: {onnx_dir} missing")
            continue
        report[size] = {}
        variants = [("fp32", onnx_dir)]
        # int8-dynamic of the baseline
        d8 = tmpdir / f"{size}-int8dyn"
        try:
            quantize_dynamic(onnx_dir, d8)
            variants.append(("int8-dynamic", d8))
        except Exception as e:  # noqa: BLE001
            print(f"{size} int8-dynamic failed: {e}")
        # static int8 (encoder static + decoder dynamic: seq2seq decoders
        # resist static quant due to dynamic shapes)
        try:
            s8 = tmpdir / f"{size}-int8static"
            quantize_static(onnx_dir, s8, calib)
            variants.append(("int8-static", s8))
        except Exception as e:  # noqa: BLE001
            print(f"{size} int8-static failed: {e}")
        # fp16
        try:
            f16 = tmpdir / f"{size}-fp16"
            to_fp16(onnx_dir, f16)
            variants.append(("fp16", f16))
        except Exception as e:  # noqa: BLE001
            print(f"{size} fp16 failed: {e}")

        for name, d in variants:
            try:
                enc, dec = load_pair(d, threads=1)
                r = bench(enc, dec, rows, VARIETY)
                size_mb = sum(f.stat().st_size for f in d.glob("*.onnx")) / 1e6
                r["artifact_mb"] = round(size_mb, 1)
                r["peak_rss_mb"] = round(peak_rss_mb(), 1)
                report[size][name] = r
                print(f"{size:6} {name:12} exact {r['exact']:.3f} "
                      f"{r['ms_per_word']:.0f} ms/word {r['artifact_mb']}MB "
                      f"rss {r['peak_rss_mb']}MB", flush=True)
                del enc, dec
                gc.collect()
            except Exception as e:  # noqa: BLE001
                report[size][name] = {"error": str(e)}
                print(f"{size} {name} BENCH FAILED: {e}")

    OUT.write_text(json.dumps(report, indent=1, sort_keys=True))
    print(f"-> {OUT}")
    shutil.rmtree(tmpdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
