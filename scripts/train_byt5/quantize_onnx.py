#!/usr/bin/env python3
"""Quantize an exported ByT5 ONNX dir to int8 — correctly.

torch.onnx in torch>=2.9 emits every model weight as a Constant NODE
(even with dynamo=False — the legacy initializer-based exporter is
gone). onnxruntime's quantize_dynamic only rewrites weights that are
graph INITIALIZERS, so quantizing a modern torch export is a silent
no-op: the "quantized" model comes out the same size and the same
fp32 accuracy-to-size. This bit us once — the tell is an int8 dir the
same byte size as fp32.

This script promotes Constant node outputs to initializers first
(purely structural: initializers and Constant outputs are both static
graph values), then runs quantize_dynamic, then verifies the result
actually shrank and still decodes correctly.

Usage:
  python quantize_onnx.py --src onnx/g2p-tiny --out onnx-int8/g2p-tiny \
      [--task g2p]   # enables the greedy-decode gate after quantizing
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import onnx
from onnxruntime.quantization import quantize_dynamic, QuantType


def promote_constants(model: onnx.ModelProto) -> tuple[onnx.ModelProto, int]:
    """Move Constant node tensors into graph.initializer.

    quantize_dynamic only considers initializer-backed MatMul/Conv
    weights; Constant-node weights are invisible to it.
    """
    graph = model.graph
    promoted = 0
    keep_nodes = []
    new_initializers = []
    for node in graph.node:
        if node.op_type != "Constant":
            keep_nodes.append(node)
            continue
        tensor = None
        for attr in node.attribute:
            if attr.name == "value":
                tensor = attr.t
                break
        if tensor is None or not tensor.dims:
            # scalar/no-value constants: leave as nodes (cheap, and some
            # are genuinely control-flow plumbing)
            keep_nodes.append(node)
            continue
        # detach name from node, reattach as initializer
        t = onnx.TensorProto()
        t.CopyFrom(tensor)
        t.name = node.output[0]
        new_initializers.append(t)
        promoted += 1
    del graph.node[:]
    graph.node.extend(keep_nodes)
    graph.initializer.extend(new_initializers)
    return model, promoted


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", required=True, help="fp32 ONNX export dir")
    ap.add_argument("--out", required=True, help="destination int8 dir")
    ap.add_argument("--task", choices=["g2p", "p2g"], help="run decode gate after quantizing")
    ap.add_argument("--fp32-out", help="also save the promoted-initializer fp32 here "
        "(single-file, no .onnx.data sidecar — recommended for publishing)")
    args = ap.parse_args()

    src = Path(args.src)
    out = Path(args.out)
    if not (src / "encoder_model.onnx").exists():
        print(f"missing {src}/encoder_model.onnx", file=sys.stderr)
        return 1
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)

    # 1. promote constants -> initializers (in a temp staging dir)
    stage = out.parent / f".{out.name}-fp32-init"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    for f in ("encoder_model.onnx", "decoder_model.onnx"):
        m = onnx.load(str(src / f))
        m, n = promote_constants(m)
        onnx.checker.check_model(m)
        onnx.save(m, str(stage / f))
        print(f"{f}: promoted {n} constants -> initializers")
    for f in ("added_tokens.json", "special_tokens_map.json", "tokenizer_config.json"):
        if (src / f).exists():
            shutil.copy(src / f, stage / f)

    # 2. quantize
    for f in ("encoder_model.onnx", "decoder_model.onnx"):
        quantize_dynamic(str(stage / f), str(out / f), weight_type=QuantType.QInt8)
    for f in ("added_tokens.json", "special_tokens_map.json", "tokenizer_config.json"):
        if (stage / f).exists():
            shutil.copy(stage / f, out / f)

    # 3. verify it actually shrank (guards against the silent no-op)
    for f in ("encoder_model.onnx", "decoder_model.onnx"):
        before = (stage / f).stat().st_size
        after = (out / f).stat().st_size
        ratio = after / before
        print(f"{f}: fp32={before/1e6:.1f}MB int8={after/1e6:.1f}MB ({ratio:.2f}x)")
        if ratio > 0.6:
            print(f"  WARNING: {f} barely shrank — quantization may be a no-op", file=sys.stderr)
    if args.fp32_out:
        fp32_out = Path(args.fp32_out)
        shutil.rmtree(fp32_out, ignore_errors=True)
        shutil.copytree(stage, fp32_out)
        print(f"promoted fp32 kept -> {fp32_out}")
    shutil.rmtree(stage, ignore_errors=True)

    # 4. decode gate
    if args.task:
        sys.path.insert(0, str(Path(__file__).parent))
        from export_onnx import validate

        ok, details = validate(out, args.task)
        for d in details:
            print(f"  {d}")
        if not ok:
            print("int8 decode gate FAILED", file=sys.stderr)
            return 1
        print("int8 decode gate OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
