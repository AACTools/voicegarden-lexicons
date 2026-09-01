#!/bin/bash
# Build expanded (distilled) lexicon bundles for v2.
#
# Run from the repo root.
# Usage: bash scripts/build_expanded_v2.sh

set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
cd "$REPO"

FST_COMPILE="${FST_COMPILE:-floravox-fst-compile}"
TRAIN="/home/willwade/GitHub/AACTools/floravox/target/release/floravox-train-phonetisaurus"

# Languages with v2 distill data (exclude .3vote variants)
TAGS=()
for f in distill-v2/*.tsv; do
    base=$(basename "$f" .tsv)
    [[ "$base" == *.3vote ]] && continue
    TAGS+=("$base")
done

echo "Building expanded bundles for ${#TAGS[@]} languages"
echo ""

mkdir -p distill-fst-v2 expanded-v2

for tag in "${TAGS[@]}"; do
    echo "=== $tag ==="

    BASE="staging/$tag/merged.tsv"
    DISTILL="distill-v2/$tag.tsv"
    DISTILL_3VOTE="distill-v2/$tag.3vote.tsv"

    if [ ! -f "$BASE" ]; then
        echo "  !! SKIP: no base lexicon at $BASE"
        continue
    fi
    if [ ! -f "$DISTILL" ] && [ ! -f "$DISTILL_3VOTE" ]; then
        echo "  !! SKIP: no distill data for $tag"
        continue
    fi

    # Use 3-vote if available (eng-US, ell, swe had it in v1)
    USE_DISTILL="$DISTILL"
    [ -f "$DISTILL_3VOTE" ] && USE_DISTILL="$DISTILL_3VOTE"

    N_BASE=$(wc -l < "$BASE")
    N_DISTILL=$(wc -l < "$USE_DISTILL")

    # Create combined TSV
    COMBINED="expanded-v2/$tag.combined.tsv"
    cat "$BASE" "$USE_DISTILL" > "$COMBINED"
    N_COMBINED=$(wc -l < "$COMBINED")
    echo "  base: $N_BASE + distill: $N_DISTILL = $N_COMBINED combined"

    # FST compile
    FST_STEM="distill-fst-v2/$tag"
    echo "  FST compile..."
    $FST_COMPILE "$COMBINED" "$FST_STEM" 2>&1 | sed 's/^/    /'
    if [ ! -f "$FST_STEM.fst" ]; then
        echo "  !! FST compile failed"
        continue
    fi

    # Phonetisaurus train (holdout is fraction 0.0-1.0, eval-cap caps absolute count)
    echo "  Phonetisaurus train..."
    METRICS="expanded-v2/$tag.metrics.json"
    $TRAIN "$COMBINED" "expanded-v2/$tag.wfst.fst" \
        --metrics "$METRICS" \
        --order 7 --iters 8 --gmax 2 --pmax 2 \
        --eval-cap 2000 --holdout 0.01 \
        2>&1 | tail -5
    if [ ! -f "expanded-v2/$tag.wfst.fst" ]; then
        echo "  !! Phonetisaurus train failed"
        continue
    fi

    echo "  DONE ($tag)"
    echo ""
done

echo "=== All done ==="
echo ""

# Print summary
echo "FST files:"
ls -lh distill-fst-v2/*.fst 2>/dev/null | awk '{print "  " $NF " (" $5 ")"}'
echo ""
echo "Phonetisaurus models:"
ls -lh expanded-v2/*.wfst.fst 2>/dev/null | awk '{print "  " $NF " (" $5 ")"}'
echo ""

echo "Metrics:"
for f in expanded-v2/*.metrics.json; do
    [ -f "$f" ] || continue
    tag=$(basename "$f" .metrics.json)
    python3 -c "import json; d=json.load(open('$f')); print(f'  {tag}: exact={d[\"exact_match\"]:.4f} per={d[\"per\"]:.4f} states={d[\"states\"]} arcs={d[\"arcs\"]}')"
done