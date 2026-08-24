# Multilingual ByT5 G2P/P2G — training runbook

Goal: the neural tier (roadmap M4) that beats the WFST where WFSTs
can't go — deep orthographies (eng 63%, gle 35%), logographic scripts
(cmn 4%, yue 30%), unwritten-vowel languages (Arabic dialects), and
every language too small for a good WFST.

Byte-level ByT5 means no tokenizer work for any script; the same model
serves G2P (`<lang>: word -> IPA`) and a mirror for P2G
(`<lang>: IPA -> word`). Corpus: 130 languages, ~2.7M pairs, built from
the measured staging dirs (see ../results/metrics.json for the WFST
baseline each language must beat or match).

## One-time setup on the training box

```sh
git clone https://github.com/AACTools/voicegarden-lexicons
cd voicegarden-lexicons

python3 -m venv .venv && source .venv/bin/activate
# VERIFIED dependency set (transformers 5.x / optimum-onnx era —
# optimum[exporters] and as_target_tokenizer no longer exist):
pip install torch transformers datasets sentencepiece \
            optimum-onnx onnxruntime accelerate
# GPU: pip install torch --index-url https://download.pytorch.org/whl/cu124
python3 -c "import torch; print(torch.cuda.is_available())"
```

Hardware guide (byt5-small, 2.67M pairs, 3 epochs):

| GPU | batch | grad-accum | approx time |
|---|---|---|---|
| 24 GB (3090/4090) | 64 | 1 | ~20 h |
| 16 GB (4060 Ti/T4x2) | 32 | 2 | ~28 h |
| 80 GB (A100/H100) | 128 | 1 | ~8 h, or use byt5-base |

Rent whichever; the scripts checkpoint every 5k steps and resume.

## Run

```sh
# 1. Build the corpus (2 min, CPU) — output is committed, so if
#    staging/ already has the data you can skip to 2.
python3 scripts/train_byt5/build_corpus.py

# 2. Smoke test on the GPU box (minutes): proves the pipeline end to
#    end — tokenize, train, save, export, evaluate. Already verified
#    CPU-side; this re-proves it on the rented stack.
python3 scripts/train_byt5/train.py --task g2p --max-steps 50 --batch 8 \
    --eval-steps 25 --save-steps 25 --out runs-smoke
python3 scripts/train_byt5/export_onnx.py --model runs-smoke/g2p-byt5-small/final --task g2p --out onnx-smoke
python3 scripts/train_byt5/eval_onnx.py --onnx onnx-smoke/g2p --task g2p --sample 100

# 3. Real run, both directions (sequential; ~a day total on a 24 GB GPU)
python3 scripts/train_byt5/train.py --task both --base google/byt5-small --out runs

# 4. Export + evaluate both directions on the test split
python3 scripts/train_byt5/export_onnx.py --model runs/g2p-byt5-small/final --task g2p --out onnx
python3 scripts/train_byt5/export_onnx.py --model runs/p2g-byt5-small/final --task p2g --out onnx
python3 scripts/train_byt5/eval_onnx.py --onnx onnx/g2p --task g2p
python3 scripts/train_byt5/eval_onnx.py --onnx onnx/p2g --task p2g

# 5. Commit the artifacts
git add results/byt5-*.json && git commit -m "byt5 tier: eval results"
# onnx/ and runs/ are large — do NOT commit; see "Shipping" below
```

## Acceptance gates

- `results/byt5-g2p.json` macro-exact ≥ 0.75 (WFST macro is ~0.63
  across the 130; the neural tier must be clearly better on the weak
  35 and not worse on the strong 43).
- Spot checks vs WFST rows: eng ≥ 0.70 (WFST 0.634), cmn ≥ 0.30
  (WFST 0.040), gle ≥ 0.50 (WFST 0.352), ara ≥ 0.60 (WFST ~0.45).
- Latency sanity: eval_onnx prints ms/example; for OOV-tier duty the
  cached + WFST-front architecture tolerates ~50-100 ms/ex on CPU.

## Shipping (after gates pass)

1. Copy `onnx/{g2p,p2g}/` off the box (~2 × 300 MB fp32; re-export
   fp16/int8 if size matters for embedding).
2. Publish as release assets here (or a sibling repo) — the runtime
   side (floravox `Byt5G2p::load` / `ByT5P2g::load`) already takes
   `encoder_model.onnx` + `decoder_model.onnx` paths directly.
3. Wire the tier chain in the consumer (floravox-cli `g2p` /
   `floravox-p2g --byt5`), re-run `audit_g2p.py` against piper voices.

## Failure modes / notes

- OOM: halve --batch, double --grad-accum; MAX lens are in train.py.
- `optimum` export naming drift: floravox's loader discovers tensor
  names, but if optimum renames files entirely, adjust export_onnx.py.
- Arabic/Hebrew diacritics: kept verbatim — ByT5 handles the bytes; do
  not "clean" them, voices need them.
- The val split gates checkpoint choice by exact-match; don't raise
  --eval-steps above 10k or best-checkpoint selection gets coarse.
