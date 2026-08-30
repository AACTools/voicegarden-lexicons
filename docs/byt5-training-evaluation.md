# Training the ByT5 multilingual G2P/P2G models

How the published models were built, and how it worked out. Written
after the fact: what worked, what didn't, what the numbers mean, and
what we would do differently.

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
