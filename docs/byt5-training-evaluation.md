# Training the ByT5 multilingual G2P/P2G models

> **Note (2026-11-18):** the `scripts/train_byt5` / `scripts/fuzzy` code referenced below moved to the private [willwade/floravox-training](https://github.com/willwade/floravox-training) repo. This repo keeps the data pipeline.

## v2: Harmonized retrain (2026-08-30)

In August 2026 the models were retrained on a **harmonized 4.12M-pair
corpus** (+27% over v1's 3.02M), 142 language tags, with per-language
IPA conventions unified via a learned many-to-many EM aligner
(scripts/train_byt5/m2m_align.py (now in willwade/floravox-training, private)).

The retrain used the same architecture (byt5-small / tiny config) and
hyperparameters as v1, but with M2M-converted wikipron fill replacing
the raw union. The new models are published at:

- [G2P small](https://huggingface.co/willwade/byt5-g2p-multilingual)
- [G2P tiny](https://huggingface.co/willwade/byt5-g2p-multilingual-tiny)
- [P2G small](https://huggingface.co/willwade/byt5-p2g-multilingual)
- [P2G tiny](https://huggingface.co/willwade/byt5-p2g-multilingual-tiny)

Results on the same stratified 4000-row test set (v1 vs v2 on the
harmonized test split):

| model | v1 micro | v2 micro | Δ |
|---|---|---|---|
| g2p-small | 0.663 | **0.730** | +0.067 |
| g2p-tiny | 0.582 | **0.718** | +0.136 |
| p2g-small | 0.483 | 0.483 | 0.000 |
| p2g-tiny | 0.397 | 0.397 | 0.000 |

(The v1 scores on this test are lower than the published 0.731 because
the v1 test had mixed conventions, making tie-breaking easier. The v2
scores are on a harder, convention-clean test.)

Key per-language gains: spa +0.256, fra +0.222, por +0.570, nld +0.174.
Regression: deu -0.072, eng-UK -0.039. Detailed per-language diffs in
[floravox/results-h/](https://github.com/AACTools/floravox/tree/main/results-h).

Training run: RTX 3090, ~8h, ~$1.20 (small + tiny, both directions).

The English fine-tune experiment (below) is from v1 and remains
instructive despite the v2 corpus changes.

---

## The English fine-tune experiment (2026-08-30): a negative result

Hypothesis: English scores lower than every comparable language
(fine-tuned small: 48% exact on the original holdout; German 94%)
because English was under-trained amid 3M competing pairs. A
concentrated fine-tune should lift it.

Setup: corpus-ft = eng-US (122k) + eng-UK (78k) + CMUDict-as-IPA
(only 2,266 genuinely new words, gruut already absorbed the rest)
plus a 300k replay sample from the other languages; 1 epoch, both
directions, both models fine-tuned from the published checkpoints on
an RTX 3090 (~40 min each).

Result: no improvement.

| model | published | fine-tuned |
|---|---|---|
| small | 52.1% | 52.9% (+0.8, noise) |
| tiny | 54.6% | 52.2% (-2.4, worse) |

The tiny's validation loss *rose* during training, the classic
degradation signature. The published checkpoints were kept.

What this tells us: English is not under-trained. The models already
fit the English data; held-out accuracy is bounded by the corpus's
internal inconsistencies (stress placement and vowel-reduction
conventions differ between the merged sources) and by English
orthography itself. Adding more of the same data cannot fix that.
The real lever, if English ever needs to improve, is corpus
convention cleanup: one source of truth for stress and reduction
rules, retrained from the cleaned data. That is a data-engineering
project, not a training run.

The corpus builder and CMUDict converter live in
`scripts/train_byt5/build_ft_corpus.py` and the floravox repo's
`floravox-g2p/examples/cmu2tsv.rs`, so the experiment is reproducible.

## 1. What was built

Four models (g2p/p2g × 300M/17M), trained on a 3.02M-pair corpus of
136 variety-keyed languages, published to HF with validated ONNX +
int8 variants:

| | micro exact | macro exact | TER |
|---|---|---|---|
| g2p-small | 0.731 | 0.636 | 0.140 |
| g2p-tiny | 0.729 | **0.654** | **0.139** |
| p2g-small | 0.533 | 0.582 | 0.467 |
| p2g-tiny | 0.495 | **0.614** | 0.505 |

## 2. Data audit

**Sources and licences** (verified during the work):
- WikiPron: CC BY-SA 4.0 (117 languages; dialect splits preserved:
  eng-US/UK, por-BR/PT, spa-ES/LatAm, cym N/S, hye E/W, ben Rarh/Dhaka,
  20+ Sinitic). Code Apache-2.0 but data follows Wiktionary terms.
- gruut lexicons: MIT (13 languages, stress-marked, voice-facing
  conventions — what piper-family voices consume).
- Weights released CC BY-SA 4.0 (conservative share-alike reading).
  **No closed-sourcing** — decided consciously.

**Data quality findings:**
- The gruut/WikiPron merge needs care: union-training halved German
  P2G (50%→16%) due to IPA convention conflicts. Fixed with merge
  strategies (gruut-only where gruut exists). Residual risk: the two
  sources still differ in symbol inventories *between* languages.
- WikiPron `filtered` vs unfiltered files per dialect — the filtered
  (dedup) ones are the right source; we take them.
- **The two silent-failure modes that cost the most**:
  1. Hand-written gate expectations were wrong twice (gruut spa uses
     ASCII "g", por uses IPA "ɡ"; por-BR "gato" ends in "o"). Fix:
     corpus-derived gates. Lesson: never hand-write test expectations
     when the corpus is the ground truth.
  2. The variety-merge tmux loop silently skipped 12 dialect dirs →
     v2 initially trained without eng/spa/por entirely (124 langs
     instead of 136), and cross-lingual transfer produced *plausible*
     garbage that passed casual inspection. Fix: corpus-tag guard
     before training. Lesson: cross-lingual transfer masks missing
     training data — verify tags, not outputs.

**Corpus stats**: 3.02M pairs, 136 tags, 1504 phone symbols, ~200MB.
Alphabetical split (no train/test leakage across near-duplicate
spellings). Junk filters drop <0.01%.

## 3. Training audit

**What worked:**
- byt5-small fine-tune: converged fast (early stop ~40% of budget),
  0.73 micro. Language-balanced √-frequency sampling lifted macro
  (tiny macro 0.654 vs the micro gap it implies).
- From-scratch tiny: **needs real warmup** (6% of steps). With ~10-step
  warmup it plateaued at byte-unigram entropy and produced
  language-tag echoes; with proper warmup it ties the 300M model
  (0.729 vs 0.731) at 1/18th size.
- group_by_length: ~30-40% step-time cut on short sequences.
- Early stopping saved ~60% of the smalls' GPU budget.

**What didn't / surprises:**
- p2g ceiling (~0.5-0.6 micro) is homophones, not model capacity —
  exact-match fundamentally understates P2G (Spanish b/v: 0.18 raw,
  near-zero TER). A homophone-credited scorer is written but not yet
  wired into the headline numbers.
- The small p2g (0.533) early-stopped possibly too eagerly vs tiny's
  10-epoch budget (0.495 micro but 0.614 macro). Different budgets
  confound the size comparison for p2g.
- English G2P (~0.70 in earlier runs on flatter splits) remains the
  weakest big language — deep orthography; the lexicon+WFST tiers
  carry it in deployment.

**Cost accounting:** ~$6 (first run, plus ~$4 lost to the broken-ONNX
redo) + ~$8 (corrected-corpus rerun + tiny retries) ≈ **$18 total GPU
for everything**, inside the $25 credit.

## 4. Inference audit (the optimization matrix)

Measured: fp32 / int8-dynamic / int8-static / fp16 × small/tiny,
single-thread CPU:

| | best variant | ms/word | size |
|---|---|---|---|
| small | int8 | 834 | 301 MB |
| **tiny** | **int8** | **77** | **18.5 MB** |

- int8: strict win (75% smaller, faster, no quality loss) — **but only
  after fixing torch.onnx constant-folding** (weights in Constant
  nodes are invisible to ORT quantization; convert to initializers).
- fp16 on CPU: 2-3× slower — rejected.
- KV-cache decoder export: designed, not yet built (linear-time decode
  is the next big lever after these).
- 77 ms/word for an 18.5 MB multilingual model = embeddable.

## 5. Usage audit

- Published artifact is consumable end-to-end: `hf download` +
  `onnx_reference.py` verified locally from a fresh pull.
- The conventions (byte+3, EOS, causal mask, length-2 bootstrap) cost
  days to discover; all encoded in the reference script. Any
  integration should start from it.
- Missing piece: the BCP-47 `langs.json` resolution table
  (user-facing `en-GB` → internal `eng-UK`) — data exists in the
  corpus tags; the floravox-side wiring is the remaining work.
- Sinitic varieties score 0 for G2P (logographic) — by design they
  need the dictionary tier; the model card says so.

## 6. Honest ledger of mistakes

1. Three "broken exports" were one broken harness (greedy decode
   prefix-reset) — v1 ONNX was probably fine; we destroyed the v1
   weights on a wrong diagnosis. The checkpoint-safety rule (never
   destroy until published) came from this.
2. The id=byte+3 convention took four sessions of debugging to find.
3. Hand-written gate expectations: wrong twice before being banned.
4. Silent variety-merge failure trained a model without English —
   caught only by corpus archaeology after publication claims.
5. 20-epoch tiny overcorrect (24h ETA) caught by watching the log.

Each has a structural fix now in the pipeline (corpus-derived gates,
tag guards, reference consumers, checkpoint retention).

## 7. Recommended next steps (ranked)

1. **Wire the tiny-int8 into floravox** as the default OOV tier
   (18.5 MB, 77 ms — fits the piper embeddability profile).
2. langs.json BCP-47 resolution + `from_voice()` in the Rust API.
3. Homophone-credited P2G scorer for honest headline numbers.
4. KV-cache decoder export (the remaining big speed lever).
5. Sinitic dictionary tier (graceful degradation for cmn/yue/...).
6. Consider byt5-base for the *small* slot only if English matters
   enough to chase the last points — else the tiny is the product.

## 8. Comparison to the field (final)

- CharsiuG2P: exists, MIT code, ~100 languages — but espeak-derived
  training data (GPL taint), no dialect splits, wrong output
  conventions for gruut-voices, no P2G. On our test through the same
  harness: 0.168 vs our 0.731 (conventions, not just quality).
- Bookbot P2G: English-only.
- Multilingual P2G at this scale with validated ONNX + int8 + dialect
  tags: nothing else we found. The claim "best open multilingual P2G"
  survives scrutiny on coverage + licence + artefact quality, with the
  homophone caveat noted.

## P2G round-trip baseline (v2 models, 2026-11-26)

The respeller tier (rust-tts-wrapper #109: `<phoneme>` → a spelling an
orthographic engine can read) is gated on a measurement this archive
did not have: *does a phoneme string survive the trip through a
spelling?* `scripts/p2g_roundtrip.py` answers it per language on
held-out rows of the v2 test split (n = 500 per language, capped by
availability):

- **same word** — P2G returned the original spelling. A safe no-op: an
  engine pronounces it natively, whether or not our own G2P happens to
  transcribe it like the reference row.
- **verified homophone** — a *different* spelling that our G2P maps back
  to exactly the reference IPA. This is the respeller's value-add.
- **broken** — neither: the respeller changed the pronunciation. **This
  is the gate.**
- **respell in-charset** — the respelling uses only letters attested in
  that language's own spellings (whole train split). Guards against
  phoneme strings in disguise that only our G2P could read back.

Inference follows `onnx_reference.py`'s conventions with batching; a
`--selftest` proves the batched decoder against the single-sequence
reference before any number is reported (passes on CPU and CUDA). The
v2 test split is an **alphabetical head slice** per language, not a
random sample, so short early-alphabet words are over-represented, and
101 languages have fewer than 100 clean rows (†) — treat those as
indicative only. Hungarian has no clean held-out rows at all (its test
split is entirely suffix entries). Full numbers: `results/p2g-roundtrip-{small,tiny}.json`.

### Bundle languages, small model

| language | n | same word | verified homophone | **broken** | PER (misses) | respell in-charset | tier | tiny broken |
|---|---|---|---|---|---|---|---|---|
| Spanish (Latin America) (`spa-LatAm`) | 500 | 20% | 80% | **0%** | 0% | 100% | ship | 0% |
| Georgian (`kat`) | 170 | 83% | 16% | **1%** | 1% | 100% | ship | 4% |
| Spanish (`spa`) | 500 | 38% | 61% | **1%** | 0% | 100% | ship | 1% |
| Spanish (Spain) (`spa-ES`) | 500 | 43% | 56% | **2%** | 0% | 100% | ship | 0% |
| Portuguese (Portugal) (`por-PT`) | 500 | 62% | 36% | **2%** | 0% | 100% | ship | 4% |
| Italian (`ita`) | 500 | 95% | 3% | **3%** | 5% | 100% | ship | 3% |
| Basque (`eus`) | 119 | 15% | 82% | **3%** | 1% | 100% | ship | 6% |
| Albanian (`sqi`) | 48 † | 88% | 8% | **4%** | 7% | 100% | ship | 8% |
| Portuguese (Brazil) (`por-BR`) | 500 | 70% | 24% | **6%** | 2% | 100% | usable with care | 10% |
| Maltese (`mlt`) | 157 | 86% | 8% | **6%** | 3% | 100% | usable with care | 4% |
| Estonian (`est`) | 27 † | 93% | 0% | **7%** | 5% | 100% | usable with care | 0% |
| Gujarati (`guj`) | 40 † | 72% | 20% | **8%** | 10% | 100% | usable with care | 15% |
| French (`fra`) | 500 | 35% | 57% | **8%** | 2% | 100% | usable with care | 12% |
| German (`deu`) | 500 | 82% | 8% | **10%** | 7% | 100% | usable with care | 11% |
| Lithuanian (`lit`) | 197 | 77% | 13% | **11%** | 4% | 100% | usable with care | 16% |
| Vietnamese (`vie`) | 287 | 60% | 29% | **11%** | 3% | 100% | usable with care | 26% |
| Welsh (`cym`) | 145 | 71% | 16% | **13%** | 12% | 100% | usable with care | 12% |
| Kazakh (`kaz`) | 15 † | 73% | 13% | **13%** | 12% | 100% | usable with care | 27% |
| Ukrainian (`ukr`) | 257 | 83% | 3% | **14%** | 9% | 100% | usable with care | 19% |
| Nepali (`nep`) | 18 † | 56% | 28% | **17%** | 15% | 100% | weak | 22% |
| Latvian (`lav`) | 16 † | 69% | 6% | **25%** | 14% | 100% | weak | 38% |
| Luxembourgish (`ltz`) | 37 † | 57% | 16% | **27%** | 18% | 100% | weak | 81% |
| Swedish (`swe`) | 221 | 57% | 14% | **29%** | 17% | 100% | weak | 47% |
| Malayalam (`mal`) | 94 † | 59% | 12% | **30%** | 9% | 100% | weak | 26% |
| Norwegian Bokmål (`nob`) | 27 † | 67% | 0% | **33%** | 23% | 100% | weak | 78% |
| English (US) (`eng-US`) | 500 | 39% | 24% | **37%** | 14% | 100% | do not ship | 50% |
| Afrikaans (`afr`) | 20 † | 35% | 25% | **40%** | 7% | 100% | do not ship | 85% |
| Korean (`kor`) | 9 † | 0% | 56% | **44%** | 8% | 100% | do not ship | 67% |
| English (UK) (`eng-UK`) | 500 | 24% | 28% | **48%** | 17% | 100% | do not ship | 60% |
| Irish (`gle`) | 95 † | 36% | 13% | **52%** | 30% | 100% | do not ship | 53% |
| English (`eng`) | 500 | 31% | 17% | **52%** | 22% | 100% | do not ship | 68% |
| Mandarin (`cmn`) | 500 | 0% | 39% | **61%** | 33% | 100% | do not ship | 76% |
| Dutch (`nld`) | 500 | 18% | 20% | **61%** | 13% | 100% | do not ship | 60% |
| Persian (`fas`) | 500 | 7% | 22% | **71%** | 23% | 100% | do not ship | 93% |
| Cantonese (`yue`) | 500 | 0% | 28% | **72%** | 38% | 100% | do not ship | 88% |

Tiers: ship ≤ 5% broken, usable with care ≤ 15%, weak ≤ 35%, do not
ship above. Macro over all 150 languages with rows: 23.3% broken,
60.0% same word, 16.7% verified homophone (tiny: 30.7% broken).

### Rows the models have never seen

Rows added to the bundles after the v2 training run are held out by
construction, and they tell a different story from the test split —
the head slice flatters thin-training locales:

| post-v2 held-out rows | n | same word | verified homophone | **broken** | tiny broken |
|---|---|---|---|---|---|
| `lav` (CV-aligned fill) | 500 | 93% | 1% | **6%** | 23% |
| `afr` (kaikki fill) | 215 | 58% | 16% | **26%** | 44% |
| `nob` (kaikki fill) | 500 | 63% | 6% | **31%** | 36% |
| `kur` | 193 | 0% | 1% | **99%** | 96% |

### What this settles for #109

- **Shippable now, per language:** the Spanish and Portuguese varieties,
  Georgian, Italian, Basque (small model only — the tiny tier is
  roughly 1.5× worse everywhere and should not back the respeller).
  Note Italian "ships" almost entirely by returning the same word
  (95%): safe, but little value-add; Spanish and Basque are where the
  model genuinely respells (56–82% verified homophones).
- **Not shippable:** every English variety, Dutch, Persian, Mandarin,
  Cantonese, Irish — and the tiny model as a whole.
- **`kur` and `tn` have no P2G at all**: their language tags postdate
  the v2 corpus. They need the v3 training run.
- **`same word` hides convention noise in the v2 corpus**: Norwegian's
  test rows score 0% on raw IPA round-trip while the model returns the
  right word two times in three — the G2P transcribes it differently
  from the reference row (`a` vs `ɑ`), the duplicate-unfolded-
  conventions contamination the v3 corpus builder fixed. Gate on
  `broken`, not on raw IPA equality.

### Reproducing

CPU is ~0.65 rows/s for the small model (a 13-hour sweep); an RTX 3060
does ~40 rows/s (the whole table above in ten minutes, about $0.10 on
Vast.ai). On a `pytorch/pytorch:*-cuda12.4-cudnn9` image,
`onnxruntime-gpu==1.20.2` falls back to CPU **silently** unless cuDNN
is on the loader path — check `nvidia-smi`, and export
`LD_LIBRARY_PATH` over `site-packages/nvidia/*/lib`.

## Distillation precision (v2 models, 2026-11-26)

The expanded tier's rule — keep a model-generated pronunciation only
when the small and tiny G2P models agree — had never been measured
against references. `scripts/distill_missing.py --validate LANG=TSV`
does: on held-out rows with a known pronunciation, how often is an
agreed output actually right?

| language | held-out rows | small alone | 2-vote agreed | + espeak-ng as 3rd voter | WFST guesser |
|---|---|---|---|---|---|
| Norwegian Bokmål (`nob`) | 291 | 18.6% | 33.3% (24–44%) | 47.4% (23–72%, n=19) | 74% |
| Afrikaans (`afr`) | 234 | 39.3% | 58.7% (50–67%) | 68.3% (57–78%, n=79) | 68% |
| Albanian (`sqi`) | 48 | 64.6% | 72.5% (56–85%) | 77.3% (54–93%, n=22) | 76% |
| Luxembourgish (`ltz`) | 37 | 24.3% | 54.5% (19–88%) | 100% (48–100%, n=6) | 51% |
| Kazakh (`kaz`) | 15 | 53.3% | 70.0% (30–99%) | no espeak voice | 31% |
| Nepali (`nep`) | 18 | 83.3% | 86.7% (58–100%) | no espeak voice | 71% |

Two readings:

- **The agreement filter works as a filter**: agreed rows beat the
  single small model in every language (no 19% → 33%, af 39% → 59%,
  lb 24% → 55%). The espeak voter — an independent rule-based system,
  its notation mapped onto the seed's by a map learned from the seed —
  lifts it further.
- **It is still not good enough to write into a dictionary.** On random
  held-out words the best rows are correct 68–77% in af/sq, no better
  than the WFST guesser they would replace, and far below it for
  Norwegian. These locales had only 2–4k training rows in v2; the
  models are simply thin there. 2-vote rows were briefly shipped for
  af/no on inspection alone and reverted the same day.

**Gate for v3:** three-way precision must beat the locale's own guesser
with margin, measured on at least 100 held-out rows. Note the confound
in the Norwegian row: its reference transcriptions and the model's
output use different symbols for the same sounds (`a` vs `ɑ`), which
depresses "correct" — the label-noise problem the next section covers.

## Label noise in the dictionaries (2026-11-27)

Why is exact accuracy so low everywhere — for the models *and* for the
WFST guessers trained on the same data? Part of the answer is the
labels. A model-free test: in a phonemic language, words that share a
spelled ending should share a pronunciation. Grouping each dictionary's
words by their last three letters and scoring the last two phones
against the group's majority:

| dictionary | words | distinct phones | rime groups (≥5 words) | same ending → same pronunciation |
|---|---|---|---|---|
| Hungarian | 64,730 | 77 | 1,795 | **99.4%** |
| Finnish | 170,358 | 76 | 1,129 | **98.9%** |
| Estonian | 2,747 | 91 | 136 | 96.2% |
| Italian | 90,748 | 89 | 688 | 95.7% |
| German | 306,913 | 113 | 1,255 | 93.4% |
| Afrikaans | 2,276 | 64 | 115 | 94.4% |
| Latvian | 1,674 | 84 | 78 | 90.0% |
| Swedish | 22,598 | 83 | 771 | 89.9% |
| Albanian | 4,861 | 87 | 267 | **87.0%** |
| Dutch | 68,906 | 144 | 1,098 | 85.4% |
| Norwegian Bokmål | 9,875 | 102 | 302 | **84.7%** |
| Luxembourgish | 3,795 | 72 | 165 | **64.1%** |

The disagreements are systematic, not random — the same sound written
two ways: rhotics `ɹ`/`ɾ`/`r` (Albanian `-tor`: `ɔ ɹ` / `o ɾ` / `ɔ ɾ`),
gemination as `k` or `kː` (Norwegian `-ikk`: `ɪ k` / `ɪ kː` / `i k`),
vowel pairs `ɪ`/`i`, `o`/`ɔ`, `ʊ`/`u`, `ə`/`ɛ`, and Afrikaans `a`/`ɑ`
(`arm → ɑ r m` beside `ander → a n d ə r`). Some is genuine linguistic
variation; much is transcriber notation. A Norwegian probe: 12.5% of
double-letter words carry no geminate mark (`abbedissen → ɑ b e d ɪ s n̩`),
yet the same set holds true exceptions (`abbé`, `aberrant`); 1.4% of
entries contradict a ≥90%-unanimous rime majority, and espeak-ng sides
with the majority against the entry in 81 of those 135 cases.

Consequences:

- every exact-match number in this archive is a floor, including the
  published guesser holdout rates (a guesser cannot learn a rule the
  labels do not follow);
- the round-trip gate above undercounts correct rows where the model's
  symbol differs from the reference's;
- most importantly for TTS, **the voice receives different phoneme
  symbols for the same sound depending on which entry it came from**.
  These voices were trained on espeak-ng's phonemes; today the seed
  dictionaries agree with espeak's output (skeleton, notation mapped
  from the seed) only 17–41% of the time.

Cleaning is possible but is not a regular expression: it needs
orthographic laws per language (double letters are geminates in
Norwegian — except in loans), within-dictionary majority consensus, and
an independent arbiter for every candidate fix (espeak-ng, which is
what the voices expect anyway). It should precede the v3 training run:
v3's builder deduplicated symbols across languages, but within-language
synonymy of this kind survives that.
