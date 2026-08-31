#!/bin/bash
# Post-processing harness for the harmonized retrain (run on the vast.ai training box).
#
# Chained after run-harmonized.sh. Steps:
#   1. Wait for ALLDONE (tiny P2G training to finish)
#   2. Re-run small P2G (OOM'd at batch 64; retry with batch 32)
#   3. Export all models to ONNX (manual TorchScript export, validated)
#   4. Per-language eval on each variant
#   5. Head-to-head vs published baselines
#   6. Tar + report
#
# Usage (on training box):
#   bash post-harness.sh 2>&1 | tee /workspace/post-harness.log

set -euo pipefail

REPO=/workspace/voicegarden-lexicons
CORPUS=/workspace/corpus-h
LOG=$REPO/post-harness.log

STEP=1

step() {
    echo
    echo "=== STEP $STEP: $* ==="
    echo "$(date -u +%H:%M:%S) STEP$STEP: $*" >> /workspace/timing.log
    ((STEP++))
}

wait_for_alldone() {
    echo "waiting for ALLDONE marker (tiny P2G finish)..."
    while ! grep -q 'ALLDONE' /workspace/h-tiny.log 2>/dev/null; do
        sleep 120
        # show heartbeat
        tail -1 /workspace/h-tiny.log 2>/dev/null | grep -oP '[0-9]+/63032' | tr -d '\n'
        echo -n ' '
    done
    echo ' ALLDONE'
}

ensure_model() {
    local path="$1" label="$2"
    if [ -d "$path" ]; then
        echo "$label: $path OK"
        return 0
    else
        echo "$label: $path MISSING"
        return 1
    fi
}

export_onnx() {
    local model="$1" task="$2" out="$3"
    if [ -d "$out/encoder_model.onnx" ]; then
        echo "  ONNX already exists at $out — skipping"
        return 0
    fi
    echo "  exporting $model ($task) -> $out"
    python3 "$REPO/scripts/train_byt5/export_onnx.py" \
        --model "$model" --task "$task" --out "$out" 2>&1 | tail -5
    if [ ! -f "$out/encoder_model.onnx" ]; then
        echo "  FAILED: no encoder_model.onnx in $out"
        return 1
    fi
}

eval_onnx() {
    local onnx="$1" task="$2" out_json="$3"
    if [ -f "$out_json" ]; then
        echo "  eval already exists at $out_json — skipping"
        return 0
    fi
    echo "  evaluating $onnx ($task)"
    python3 "$REPO/scripts/train_byt5/eval_onnx.py" \
        --onnx "$onnx" --task "$task" --corpus "$CORPUS" \
        --sample 4000 --seed 7 --out "$out_json" 2>&1 | tail -5
}

# ======================================================================
# STEP 1: Wait for tiny P2G to finish
# ======================================================================
step "Wait for ALLDONE"

wait_for_alldone

# Verify what exists
echo "Existing models:"
ls -d "$REPO"/runs-h-small/*/final 2>/dev/null || echo " (none in runs-h-small)"
ls -d "$REPO"/runs-h-tiny/*/final 2>/dev/null || echo " (none in runs-h-tiny)"

# ======================================================================
# STEP 2: Re-run small P2G (OOM'd at batch 64)
# ======================================================================
step "Small P2G retrain (batch 32 to avoid OOM)"

if ensure_model "$REPO/runs-h-small/p2g-byt5-small/final" "Small P2G"; then
    echo "Already exists — skipping"
else
    echo "Retraining small P2G with --batch 32..."
    cd "$REPO"
    python3 scripts/train_byt5/train.py \
        --task p2g --corpus "$CORPUS" --epochs 2 --batch 32 \
        --grad-accum 2 \
        --out runs-h-small 2>&1 | tee /workspace/h-small-p2g.log
    echo "Small P2G done"
fi

# ======================================================================
# STEP 3: Export all models to ONNX
# ======================================================================
step "Export G2P small to ONNX"

export_onnx \
    "$REPO/runs-h-small/g2p-byt5-small/final" \
    g2p \
    "$REPO/onnx-h/g2p-small"

step "Export G2P tiny to ONNX"

export_onnx \
    "$REPO/runs-h-tiny/g2p-byt5-small/final" \
    g2p \
    "$REPO/onnx-h/g2p-tiny"

step "Export P2G small to ONNX"

export_onnx \
    "$REPO/runs-h-small/p2g-byt5-small/final" \
    p2g \
    "$REPO/onnx-h/p2g-small"

step "Export P2G tiny to ONNX"

export_onnx \
    "$REPO/runs-h-tiny/p2g-byt5-small/final" \
    p2g \
    "$REPO/onnx-h/p2g-tiny"

# ======================================================================
# STEP 4: Per-language eval
# ======================================================================
step "Eval G2P small per-language"

eval_onnx \
    "$REPO/onnx-h/g2p-small" \
    g2p \
    "$REPO/results-h/eval-g2p-small.json"

step "Eval G2P tiny per-language"

eval_onnx \
    "$REPO/onnx-h/g2p-tiny" \
    g2p \
    "$REPO/results-h/eval-g2p-tiny.json"

step "Eval P2G small per-language"

eval_onnx \
    "$REPO/onnx-h/p2g-small" \
    p2g \
    "$REPO/results-h/eval-p2g-small.json"

step "Eval P2G tiny per-language"

eval_onnx \
    "$REPO/onnx-h/p2g-tiny" \
    p2g \
    "$REPO/results-h/eval-p2g-tiny.json"

# ======================================================================
# STEP 5: Head-to-head vs published baselines
# ======================================================================
step "Head-to-head G2P (ours vs published)"

python3 "$REPO/scripts/train_byt5/headtohead.py" \
    --task g2p --corpus "$CORPUS" --sample 4000 \
    --only ours-small 2>&1 | tail -10

step "Head-to-head P2G"

python3 "$REPO/scripts/train_byt5/headtohead.py" \
    --task p2g --corpus "$CORPUS" --sample 4000 \
    --only ours-small 2>&1 | tail -10

# ======================================================================
# STEP 6: Package results
# ======================================================================
step "Package and report"

RESULTS_DIR="$REPO/results-h"
mkdir -p "$RESULTS_DIR"

# Summarize eval numbers
echo ""
echo "========== FINAL RESULTS SUMMARY =========="
for f in "$RESULTS_DIR"/eval-*.json; do
    [ -f "$f" ] || continue
    name=$(basename "$f" .json)
    micro=$(python3 -c "import json; d=json.load(open('$f')); print(f'{d[\"micro_exact\"]:.3f}')" 2>/dev/null || echo "?")
    macro=$(python3 -c "import json; d=json.load(open('$f')); print(f'{d[\"macro_exact\"]:.3f}')" 2>/dev/null || echo "?")
    langs=$(python3 -c "import json; d=json.load(open('$f')); print(len(d['languages']))" 2>/dev/null || echo "?")
    echo "  $name: micro $micro | macro $macro | $langs langs"
done

# Tar up the models and evals
TARBALL="/workspace/voicegarden-models-h.tar.gz"
echo ""
echo "Packaging ONNX models + results -> $TARBALL"
tar czf "$TARBALL" \
    -C "$REPO" \
    onnx-h results-h \
    --exclude="*.tmp" \
    2>/dev/null

echo ""
echo "========== POST-HARNESS COMPLETE =========="
echo "Date: $(date -u)"
echo "G2P small: $(ls "$REPO/onnx-h/g2p-small/encoder_model.onnx" 2>/dev/null && echo OK || echo MISSING)"
echo "G2P tiny: $(ls "$REPO/onnx-h/g2p-tiny/encoder_model.onnx" 2>/dev/null && echo OK || echo MISSING)"
echo "P2G small: $(ls "$REPO/onnx-h/p2g-small/encoder_model.onnx" 2>/dev/null && echo OK || echo MISSING)"
echo "P2G tiny: $(ls "$REPO/onnx-h/p2g-tiny/encoder_model.onnx" 2>/dev/null && echo OK || echo MISSING)"
echo "Tar: $(ls -lh $TARBALL 2>/dev/null | awk '{print $5}')"
echo "Log: /workspace/post-harness.log"
echo ""
echo "Next: scp the tar ball from the box, then publish models to Hugging Face"
echo "  scp -P 16086 root@ssh1.vast.ai:/workspace/voicegarden-models-h.tar.gz ./"