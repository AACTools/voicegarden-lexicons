# Developer experience & competitive evaluation

*Measured, not asserted. Numbers from this machine (Ryzen, single-thread
for ONNX), published artifacts as downloaded from HF. espeak-ng as the
incumbent baseline.*

## Cold start / warm latency / memory (the integration reality)

| engine | cold start | warm per word | resident memory | artifact size |
|---|---|---|---|---|
| espeak-ng (process spawn) | **10-65 ms** | **9 ms** | ~5 MB | ~2 MB binary |
| floravox FST lexicon (mmap) | **<5 ms** | **<0.1 ms** | ~0 (pages on demand) | 5-15 MB/lang |
| floravox WFST (deu, debug build) | ~650 ms* | ~1 ms | ~70 MB* | 33-44 MB/lang |
| **ByT5 tiny int8 (ONNX)** | **410 ms** (307 load) | **64 ms** | **122 MB** | **18.5 MB** |
| ByT5 small int8 (ONNX) | ~2-3 s (est.) | ~600-850 ms | ~400+ MB | 301 MB |

*WFST cold includes process spawn of an unstripped debug binary and the
full model read; release build + warm process would be much lower. The
WFST number is a worst case, honestly labeled.

## What this actually means for a developer

**espeak-ng is still faster at everything.** A 9 ms/word rules engine
versus 64 ms/word for our best neural variant. If raw speed is the
requirement and GPL is acceptable, espeak-ng wins. Our claim was never
speed — it is licence, IPA convention fidelity, dialect coverage, and
P2G. That claim stands.

**The tiering is the real product.** A floravox integration that ships
lexicon+WFST gets espeak-class speed (lexicon is sub-0.1 ms) with
neural quality only for true OOV — the 64 ms/word only bites on words
the lexicon has never seen, once (cache).

**Cold start is the weak spot.** 410 ms to first phoneme for the tiny.
For a screen reader that phonemizes at startup, that's acceptable; for
a CLI invocation per word it's not — but the CLI already prefers
lexicon/WFST tiers.

**Memory: the tiny is embeddable-but-not-trivial.** 122 MB RSS
(includes Python + ORT; a Rust C-API host would be less, roughly
50-70 MB) for an 18.5 MB model. The lexicon tier remains the only
true microcontroller option.

## How easy is it to use? (honest assessment)

**What works well:**
- One `hf download` + `load_dir()` gets you a working model —
  verified from a fresh machine
- `onnx_reference.py` is copy-paste-runnable and encodes every
  convention (byte+3, EOS, causal mask, bootstrap)
- `LangMap` turns user-facing `en-GB` into `<eng-UK>` prefixes
- Rust C-API path exists (`Byt5G2p::load_dir` in floravox-g2p,
  integration-tested against the published tiny)

**Friction points (real, experienced during this evaluation):**
1. **Five non-obvious conventions.** byte+3, EOS, causal mask,
   length-2 bootstrap, `<tag>: ` prefixes. We hit every one ourselves —
   twice in two different codebases (training harness AND floravox's
   own runtime had the byte+3 bug). The reference script mitigates but
   the model itself cannot enforce them.
2. **No pip/npm package.** A consumer must fetch the ONNX files and
   wire ~50 lines themselves. A `pip install floravox-g2p` with the
   conventions baked in would remove the entire class of bugs we hit.
3. **No KV-cache decoder.** Our decode is quadratic per word; the
   64 ms/word could plausibly be ~15-25 ms with a cached graph. Until
   then the neural tier is slower than it needs to be.
4. **Two repos per direction per size** (4 total) — the consumer has
   to know which to pick. A single repo with variants, or a
   `model_type="tiny|int8"` selector API, would be simpler.
5. **Symbol inventories differ by source language** (gruut vs WikiPron
   IPA choices). A voice's phoneme_id_map needs a translation layer for
   some languages; we document but don't ship one.

## Versus the field (no overselling)

| | ours | espeak-ng | CharsiuG2P | gruut |
|---|---|---|---|---|
| licence | CC BY-SA (weights), MIT code | **GPL** | MIT code, mixed data | MIT |
| languages | 136 variety tags | ~100 (rules) | ~100 | 13 |
| dialects | **yes** (en-GB/en-US/...) | voice variants | en-us/uk only | en-US only |
| G2P quality | 0.73 micro / 0.64 macro (our test) | untested head-to-head | 0.17 on our conventions | n/a (is the source) |
| P2G | **yes, multilingual** | no | no | no |
| speed | 64 ms/w neural; <0.1 ms lexicon | **9 ms/w** | similar to ours | <1 ms |
| memory | 18.5 MB tiny / 122 MB RSS | **~5 MB** | similar to ours | ~15 MB/lang |
| validated ONNX | **yes, + int8** | n/a | no | no |

**Honest gaps:** we never ran espeak-ng through our own test split
(the top-line comparison row is process-speed only, not quality). Our
quality numbers are on our conventions — by construction favorable.
The macro 0.64 means a third of languages are below that; the long
tail is thin.

## Highest-leverage next steps (if we continue)

1. **`pip install` package** wrapping the conventions (biggest DX win,
   kills the bug class we twice paid for)
2. **KV-cache decoder export** (2-4x neural speedup, no retrain)
3. **espeak-ng quality head-to-head** on our split (we owe the table
   an honest quality row, not just speed)
4. Single repo with variant selector (fetch simplicity)
5. Symbol-translation tables per voice family (gruut ↔ WikiPron IPA)
