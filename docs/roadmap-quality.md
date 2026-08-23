# Phonemization quality roadmap: beat espeak-ng on merit, not just licence

Status: ACTIVE. Commit early, commit often. Every phase ends with numbers
in `results/metrics.json` and a release.

## Mission

floravox + voicegarden-lexicons become the best open phonemization stack
available: G2P (words→phonemes) and P2G (phonemes→words), every language
we can source, quality that beats espeak-ng *on accuracy* while staying
MIT/BSD/CC-BY-SA clean. Drop-in phonemizer for piper-family voices and
anything else that today depends on espeak.

## Where we start (measured, v0.2.0 bundles)

| lang | entries | G2P (PER, holdout) | P2G (homophone-exact / CER / coverage) |
|---|---|---|---|
| en | 124k | baseline exists (trainer eval) | 39.2% / 41.4% / 98.6% |
| es | 596k | tbd | this release |
| de | 278k | tbd | this release |

Published Phonetisaurus-class baselines for P2G sit at ~35–45% exact on
English; we are at parity. The plan below is how we move past it.

## The five levers, ranked by expected gain

### 1. Data scale-up (biggest, cheapest win)

WikiPron scrape (`CUNY-CL/wikipron`, CC BY-SA 4.0) provides **304
languages, 132 with ≥1k broad-phonemic entries, 40 with ≥10k**. gruut
gives 13 curated languages. English adds CMUDict.

Per language: harvest → normalise (broad phonemic, IPA, NFC) → merge with
gruut where both exist (gruut wins conflicts: it is segmented and
stress-marked consistently) → dedupe.

- Target: **60+ shipped languages** (every lang with ≥1k entries where the
  licence allows), top-40 with trained WFSTs in both directions.
- `scripts/harvest_wikipron.py` (idempotent, resumable, rate-limited).
- English triple-merge (CMUDict+gruut+WikiPron) as the flagship.

### 2. Training improvements (quality, not just coverage)

- **Tuning sweep per language**: `--order {6,8,9} × --gmax/--pmax
  {(2,2),(3,2),(2,3)} × --iters {8,12}`, pick best holdout, record in
  metrics. Deep orthographies (en, fr) want gmax 3.
- **Stress handling**: today `ˈæ` is just another symbol, which multiplies
  the phoneme inventory and hurts short words. Experiments: (a) strip
  stress before training, reinsert with a rule layer; (b) keep as-is;
  (c) train both. Decide per language on holdout PER.
- **Backoff weight tuning**: stupid-backoff α=0.4 is untuned; sweep
  {0.3,0.4,0.5}.
- **Model diet**: prune arcs below a weight threshold to shrink the 44 MB
  en model; verify quality delta ≤0.5 PER.

### 3. Dialects and variants

- WikiPron ships `broad` (phonemic) and `narrow` (phonetic): keep both,
  keyed by variant (`en_US broad` default; `narrow` for alignment work).
- en_US vs en_GB: gruut en (US) + WikiPron `eng-US`/`eng-UK` filtered
  files where present.
- Lookup API: lexicon keys carry an optional `#variant` suffix; the
  compiler gains `--variants` to emit one fst per variant with fallback
  to the default.

### 4. The neural tier — how we actually exceed espeak

Rules (espeak) are brittle: hand-maintained, inconsistent across
languages, unfixable at scale. The stack that beats it:

- Train a **multilingual ByT5 G2P** on the full merged corpus (target:
  all harvested languages, `<lang>: word` → IPA, byte-level so every
  script works). Then the mirror **P2G** model.
- ByT5-small (~300M) is enough for parity+; the tiers below it (lexicon
  exact + WFST near-miss) mean the neural model only handles true OOV,
  so inference cost stays low (cached).
- Export ONNX, ship as `floravox-g2p --features onnx` tier 3, exactly
  where `Byt5G2p` plugs in today.
- Training scripts live in `scripts/train_byt5/` (python, transformers);
  runs on one consumer GPU (~day). Not in CI.

### 5. Evaluation as a first-class artefact

- `scripts/bench_lang.sh LANG` → trains both directions + emits metrics.
- `results/metrics.json`: the leaderboard; CI regenerates on bundle
  change and fails on regression >0.5 PER.
- Head-to-head where possible: espeak-ng `--ipa` and epitran installed as
  optional comparators (the numbers to beat, published in the table).

### Piper integration (the deliverable that makes it matter)

- `scripts/piper_coverage.py`: given a piper voice's `phoneme_id_map`,
  verify our G2P output covers its symbol table (this already exists as
  `audit_g2p.py`; promote it to CI per language).
- Conversion shim: our IPA → piper/espeak symbol conventions per voice
  family, so piper voices can phonemize through floravox with zero
  espeak dependency.

## Mechanics

- **Repo layout**: harvest/merge/train/bench scripts in `scripts/`,
  per-language staging in `staging/<lang>/`, published bundles unchanged
  (`dist/`), metrics in `results/`.
- **Long runner**: `scripts/harvest_and_train.sh [langs...]` loops
  languages end-to-end, commits after each language, pushes; safe to
  re-run (skips finished work via marker files). This is the "days-long"
  job that builds the corpus.
- **Cadence**: every language that finishes = one commit + metrics row.
  Weekly release tags once the table grows.

## Milestones

| M | Contents | Done when |
|---|---|---|
| M1 | harvest + merge for top-20 WikiPron langs; es/de P2G measured | metrics.json has 20 rows |
| M2 | tuning sweep on en/es/de; stress experiment; model diet | PER improves or decision documented |
| M3 | 60-language harvest; variant/dialect keys | 60 bundles publish |
| M4 | ByT5 multilingual G2P+P2G trained, ONNX, wired as tier 3 | beats WFST tier on 10-lang sample |
| M5 | piper coverage CI + conversion shim; espeak comparison table | a piper voice speaks via floravox-only phonemization |
