#!/usr/bin/env bash
# The long runner: harvest WikiPron, merge with gruut bundles, train +
# benchmark both directions for every language, commit + push as each
# language lands. Safe to kill and restart — every step is idempotent
# and resumable via marker files + metrics.json.
#
# Usage:
#   scripts/harvest_and_train.sh [--min 1000] [--limit N] [--langs a,b]
#
# Flow per language:
#   1. wikipron.tsv      (harvest, skipped when .wikipron.done exists)
#   2. gruut.tsv         (extracted from the published bundle if any)
#   3. merged.tsv        (merge_sources.py)
#   4. wf-g2p.fst + wf-p2g.fst + holdout metrics (bench_lang.sh)
#   5. git commit + push (results/metrics.json + staging logs)
#
# Requires: floravox built (FLORAVOX_BIN), network, git push rights.

set -euo pipefail
cd "$(dirname "$0")/.."

MIN=1000
LIMIT=0
LANGS=""
while [ $# -gt 0 ]; do
  case "$1" in
    --min) MIN="$2"; shift 2 ;;
    --limit) LIMIT="$2"; shift 2 ;;
    --langs) LANGS="$2"; shift 2 ;;
    *) echo "unknown arg $1"; exit 2 ;;
  esac
done

HARVEST_ARGS=(--min "$MIN" --out staging)
[ -n "$LANGS" ] && HARVEST_ARGS+=(--langs "$LANGS")
[ "$LIMIT" -gt 0 ] && HARVEST_ARGS+=(--limit "$LIMIT")

echo "=== 1/3 harvest WikiPron (min $MIN entries)"
python3 scripts/harvest_wikipron.py "${HARVEST_ARGS[@]}"

echo "=== 2/3 extract gruut lexicons for overlap languages"
for bundle in dist/*.tar.gz; do
  [ -e "$bundle" ] || continue
  lang=$(basename "$bundle" .tar.gz)
  d="staging/$lang"
  mkdir -p "$d"
  if [ ! -f "$d/gruut.tsv" ] && [ -f "$d/wikipron.tsv" ]; then
    tar -xzOf "$bundle" lexicon.txt > "$d/gruut.tsv" 2>/dev/null \
      && echo "  $lang: gruut bundle extracted" || rm -f "$d/gruut.tsv"
  fi
done

echo "=== 3/3 merge + train + bench, one commit per language"
for d in staging/*/; do
  lang=$(basename "$d")
  [ -f "$d/wikipron.tsv" ] || continue
  python3 scripts/merge_sources.py "$lang" || continue
  if bash scripts/bench_lang.sh "$lang"; then
    if [ -n "$(git status --porcelain results staging/$lang 2>/dev/null)" ]; then
      git add results/metrics.json "staging/$lang" 2>/dev/null || true
      git commit -q -m "bench($lang): g2p+p2g trained+measured (harvest_and_train)" \
        && echo "  committed $lang" \
        && git push -q || echo "  WARNING: push failed for $lang (will retry next run)"
    fi
  else
    echo "  $lang: bench failed — left for the next run"
  fi
done

echo "=== done. leaderboard:"
python3 - <<'PY'
import json
try:
    rows = json.load(open("results/metrics.json"))
except Exception:
    rows = []
print(f"{'lang':6} {'entries':>8} {'G2P PER%':>9} {'P2G exact%':>11} {'P2G CER%':>9}")
for r in sorted(rows, key=lambda r: -r.get("entries", 0)):
    g = r.get("g2p", {}); p = r.get("p2g", {})
    print(f"{r['lang']:6} {r.get('entries', 0):>8} "
          f"{g.get('per', 0):>9.1f} {p.get('exact', 0):>11.1f} {p.get('cer', 0):>9.1f}")
PY
