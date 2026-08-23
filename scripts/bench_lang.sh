#!/usr/bin/env bash
# Train + benchmark one language, both directions (G2P and P2G).
#
# Usage: scripts/bench_lang.sh LANG [LEXICON.tsv]
#
# Expects staging/<lang>/merged.tsv (or a lexicon passed explicitly).
# Trains two WFSTs with floravox-train-phonetisaurus (forward and
# --reverse), captures the trainer holdout eval, and appends a row to
# results/metrics.json. Idempotent per language: a metrics row that
# already has both directions is skipped unless FORCE=1.
#
# Env: FLORAVOX_BIN (default: floravox checkout's target/debug)

set -euo pipefail

LANG_CODE="${1:?usage: bench_lang.sh LANG [LEXICON.tsv]}"
LEX="${2:-staging/${LANG_CODE}/merged.tsv}"
FLORAVOX_BIN="${FLORAVOX_BIN:-$HOME/GitHub/AACTools/floravox/target/debug}"
RESULTS="results/metrics.json"
TRAIN="$FLORAVOX_BIN/floravox-train-phonetisaurus"
OUT="staging/${LANG_CODE}"

[ -x "$TRAIN" ] || { echo "trainer not found at $TRAIN (set FLORAVOX_BIN)"; exit 2; }
[ -f "$LEX" ] || { echo "lexicon $LEX missing — run merge_sources.py"; exit 2; }

mkdir -p "$OUT" results

# metrics.json helpers (jq optional; python fallback always available)
metrics_get() { python3 - "$1" "$2" <<'PY'
import json, sys
try:
    rows = json.load(open("results/metrics.json"))
except Exception:
    sys.exit(1)
for r in rows:
    if r.get("lang") == sys.argv[1] and sys.argv[2] in r:
        print(r[sys.argv[2]]); sys.exit(0)
sys.exit(1)
PY
}
metrics_set() { python3 - "$1" "$2" "$3" <<'PY'
import json, sys
lang, key, val = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
try:
    rows = json.load(open("results/metrics.json"))
except Exception:
    rows = []
for r in rows:
    if r.get("lang") == lang:
        r[key] = val; r.setdefault("entries", 0); break
else:
    rows.append({"lang": lang, "entries": 0, key: val})
json.dump(rows, open("results/metrics.json", "w"), indent=1, sort_keys=True)
PY
}

ENTRIES=$(wc -l < "$LEX")

if [ "${FORCE:-0}" != 1 ] && metrics_get "$LANG_CODE" g2p >/dev/null 2>&1 \
   && metrics_get "$LANG_CODE" p2g >/dev/null 2>&1; then
  echo "$LANG_CODE already benchmarked (FORCE=1 to redo) — skipping"
  exit 0
fi

echo "== $LANG_CODE ($ENTRIES entries): G2P"
"$TRAIN" "$LEX" "$OUT/wf-g2p.fst" 2>&1 | tee "$OUT/g2p.train.log" | grep "^eval:"
python3 - "$OUT/g2p.train.log" <<'PY'
import json, re, sys
log = open(sys.argv[1]).read()
m = re.search(r"eval: exact ([\d.]+)%, PER ([\d.]+)%, coverage ([\d.]+)%", log)
row = {"exact": float(m.group(1)), "per": float(m.group(2)), "coverage": float(m.group(3))}
print(json.dumps(row))
open(sys.argv[1] + ".json", "w").write(json.dumps(row))
PY
metrics_set "$LANG_CODE" g2p "$(cat "$OUT/g2p.train.log.json")"
metrics_set "$LANG_CODE" entries "$ENTRIES"

echo "== $LANG_CODE: P2G"
"$TRAIN" --reverse "$LEX" "$OUT/wf-p2g.fst" 2>&1 | tee "$OUT/p2g.train.log" | grep "^eval (p2g):"
python3 - "$OUT/p2g.train.log" <<'PY'
import json, re, sys
log = open(sys.argv[1]).read()
m = re.search(r"eval \(p2g\): exact ([\d.]+)%, CER ([\d.]+)%, coverage ([\d.]+)%", log)
row = {"exact": float(m.group(1)), "cer": float(m.group(2)), "coverage": float(m.group(3))}
print(json.dumps(row))
open(sys.argv[1] + ".json", "w").write(json.dumps(row))
PY
metrics_set "$LANG_CODE" p2g "$(cat "$OUT/p2g.train.log.json")"

echo "$LANG_CODE done — see $RESULTS"
