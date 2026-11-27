# Data sources: what we tapped, what unlocks what

> **Note (2026-11-18):** the `scripts/train_byt5` / `scripts/fuzzy` code referenced below moved to the private [willwade/floravox-training](https://github.com/willwade/floravox-training) repo. This repo keeps the data pipeline.

Roadmap record for the campaign in
[#5](https://github.com/AACTools/voicegarden-lexicons/issues/5), grouped
by what each source unlocks. Licensing is the gate: bundles ship
WikiPron/kaikki/Wiktionary (CC BY-SA), gruut (CC BY-SA via Wiktionary),
CMUDict (BSD), and hand-authored entries — nothing GPL-chain, nothing
non-commercial.

## Tapped this pass (2026-11)

| source | license | unlocked | measured outcome |
|---|---|---|---|
| **kaikki.org full dumps** | CC BY-SA 4.0 (Wiktionary) | P2G paradigm coverage everywhere; hu from "narrow-blocked" | isl +5,768 inflected fills → P2G exact 7.8→12.0%, expanded bundle 43,427 entries. **hu**: 68k clean words, 94% convention agreement with SIGMORPHON, 0.000% phone drop vs piper anna — best new bundle. **ko**: 35k after `fold_korean.py` (laryngeal contrasts merged — the voice inventory distinguishes none), 0.13% drop vs kss. kat: 24.6k after fold. Caveat: en.wiktionary IPA density varies wildly by language (Swedish added only 5.6k; Finnish dump is 4.4 GB, not yet pulled). `scripts/harvest_kaikki.py` |
| **VoxCommunis TextGrids** (pacscilab/VoxCommunis) | **CC0-1.0** | pre-made MFA alignments of CV validated splits (~80 locales, CV 17–20) | `tn`: 3,495 grids → 1,974 rows (≥2 alignments each), folded, **0.000%** vs the voice — first permissive tn lexicon. `kmr` evaluated and **parked**: 10,424 rows at 0.000% voice-drop but only **72.9% exact agreement** with WikiPron on shared words (near-misses: `o`/`oː`, `r`/`ɾ`) — below the ku bundle's own 95.3% guesser, so Epitran-derived rows add noise, not coverage. `et` evaluated and **parked**: 33k rows but the cvu dictionary is broad-transcription — it *loses* the Estonian Q1/Q2/Q3 quantity system the WikiPron seed writes (`ɑː/ɑˑ`, gemination `ː`); broad→narrow folding would invent phonology (side-aware folds reach only 42.2%) — et is queued for the from-audio recipe, which emits seed conventions by construction. `kk` evaluated and **parked**: 546 rows, 63.5% agreement ceiling — Epitran-kk vs WikiPron-kaz disagree on the vowel inventory itself (ɘ/i, ø/ʏ, ə/ɤ/ɯ are distinct phonemes), not on notation. Key honest finding: grid pronunciations are **dictionary-driven** (the aligner's G2P output; audio sets timing, not phonology) — the value is a CC0 *spoken-vocabulary* filter on G2P output, not independent phonetic evidence; it pays out only where the source dictionary's conventions already match the seed's (tn: no seed; kmr/et/kk: mismatch). `scripts/harvest_voxcommunis.py` |
| **per-language convention folds** (ours) | n/a (transforms) | ka, zh, ko, uk, vi, ne, lv, sr/hr, sv, fin, af, cy, ml, no | validated against each target voice's real `tokens.txt` (recomputable: `scripts/audit_voice_tokens.py`): all ≤0.4% per-word drop (hr via the sr voice — coqui-hr-cv turned out to be a grapheme model, see [sherpa-coverage](sherpa-coverage.md)). This is the template for any future locale |
| **SIGMORPHON 2020 G2P data** | asserted Wiktionary CC BY-SA in the task paper, **no explicit LICENSE in the repo** | fold reference for geo/hun/kor/lit/vie/ice | used as convention validation only (hun 94% exact vs kaikki). **Not ingested** pending an explicit grant; kaikki reaches the same words unambiguously |

## Next, highest leverage first

0. **ByT5 v3 retraining prep (DONE — corpus built)**: `langs.json`
   carries 149 languages (7 new); `scripts/train_byt5/build_corpus.py`
   rebuilt the corpus from the folded staging unions: **4.31M train
   rows over 151 languages** (v2: 4.12M/136), and the phone inventory
   dropped 7,574 → **1,672 symbols** — the v2 corpus was carrying
   duplicate unfolded conventions (the same contamination class the
   review loop removed from the bundles; the builder no longer re-reads
   raw kaikki.tsv over the folded merges). New languages: hun 66k,
   kor 34k, kat 24k, ukr 54k, vie 28k, nep 2k, lav 1.7k; grown: lt
   25k, it 89k, nl 69k, fin 170k, isl 15k. **Remaining: the GPU
   training run itself** (small+tiny G2P and P2G, the v2 recipe —
   ~$18 at v2 cloud rates per docs/byt5-training-evaluation.md), then
   distill-v3 for the 24 base-only locales using the small+tiny
   agreement gate, built from the folded merged files only.
   **Corpus rebuilt again (2026-11-27)**: 153 languages / 4.45M entries
   (test 45,020, val 44,174, train 4.36M). Now includes `kur` and `tsn`
   (which had no `merged.tsv` for the builder to see — so v2 had no P2G
   for ku or tn at all) and the rows added since the previous build:
   lav +41,215 (CV alignment fill), nob +7,993 (kaikki), afr +230.
   **The evaluation split changed.** The old one was an alphabetical
   head slice — deliberately, to keep near-duplicate spellings together —
   at the cost of being every language's shortest early-alphabet words
   (86–100% of test words shared one first letter; Hungarian's test set
   was suffix entries only). It is now alphabetical word *families*
   (shared 3-letter key; one Han character; two Hangul syllables)
   assigned at random, seeded per language, with bound morphemes kept
   for training only. Measured with the same exact test on all four
   schemes — share of test words with an edit-distance-1 neighbour in
   TRAIN, mean over eng/deu/fra/swe/nob/lav/spa/cmn:

   | scheme | neighbour in train | most common first letter |
   |---|---|---|
   | per-word random | 74% | 10–16% |
   | head slice (old) | 40% | 86–100% |
   | fixed 25-word blocks | 47% | 10–50% |
   | **word families (new)** | **44%** | **10–39%** |

   Families leak about as much as the old slice while removing its bias.
   The residue is not mostly morphology — in a 100k-word dictionary most
   words have *some* one-letter neighbour — so the round-trip harness
   now scores every language twice, on all test rows and on those
   without a train neighbour. Usable test rows: Norwegian 27 → 123,
   Hungarian 0 → 805, Latvian 16 → 388. (An earlier suffix-only
   heuristic put this leakage at 0–5%; it missed substitutions and
   insertions, and those figures should not be quoted.) The v2
   round-trip baseline was measured on the old split and is not
   comparable; v2 must not be re-scored on the new one, since it trained
   on those rows. **Pipeline smoke-tested on this corpus (2026-11-27,
   CPU, ~10 min):** train 50 steps → export → evaluate all pass, and the
   harness loads the exported graphs. Facts that cost time to learn:

   - the exporter's quality gate cannot be passed by an undertrained
     model — a smoke needs `export_onnx.py --no-gate`;
   - `export_onnx.py` writes flat into `--out` (the published layout),
     so `eval_onnx.py --onnx <out>`, with no `/g2p`; it also takes a
     local model directory, not a Hugging Face repo id;
   - its two `optimum` strategies are inert under the pinned
     `transformers==5.23.0` (`AutoModelForVision2Seq` no longer
     exists); the manual `torch.onnx` path is the one that runs;
   - the manual export is faithful at the logit level (encoder hidden
     states within 1.4e-06 of PyTorch, decoder logits within 1e-04,
     identical top-2 ids), and the runtime's length-2 decoder bootstrap
     matches Hugging Face's real first step within 8e-05. Greedy text
     from an *untrained* model still diverges between the two — tie-
     flips on nearly flat logits — so never judge an export by text
     equality on an untrained model;
   - "missing keys in the checkpoint model loaded:
     `encoder.embed_tokens.weight`…" at the end of training is benign:
     all 172 tensors are present and none moved more than 0.006 from
     its base value;
   - open question: trained checkpoints come out with the input
     embeddings and the output head no longer tied, though the config
     says tied. The export uses the checkpoint's own head weights, so
     inference is self-consistent, but this has not been explained.
1. **kaikki for the remaining blocked locales** — done for uk/kor/vie/
   nep/lav (this PR). Finnish pulled and merged. Swedish-language
   wiktionary dump for swe enrichment (en.wiktionary is IPA-poor
   there).
2. **Unihan kCantonese / CC-CEDICT** — deterministic jyutping/pinyin →
   IPA per Han char/word. Boosts `yue` heteronym resolution and `zh`
   word coverage; Unihan is permissively licensed (Unicode terms),
   CC-CEDICT is CC BY-SA 4.0 (chain-compatible).
3. **Common Voice (CC0) + MFA forced alignment** — the classic route;
   now **two-track**:
   - *VoxCommunis track (done where covered)*: ~80 locales already
     aligned (CC0) — see the source table above. No lv grids exist.
   - *align-it-ourselves track (lv — **DONE at full scale 2026-11-20**)*:
     CV 27.0 lv acquired from MDC (CC0, 6.34 GB, 199,667 validated
     clips); **full corpus** → `mfa align` (acoustic model trained on a
     15k-clip slice, G2P on the seed) → `scripts/harvest_voxcommunis.py`
     (min 2 attestations; plausibility guard) →
     `scripts/fold_latvian_cvfill.py` → **`lv` 1,704 → 42,919 entries**
     (fill 0.015% voice-drop, 100% agreement on 881 shared words,
     guesser exact 38.6% → **83.3%**). Epitran lav-Latn measured and
     rejected for the alignment dictionary (3% seed agreement, voicing
     errors); MFA's Phonetisaurus trained on the seed is the dictionary
     source, so OOV rows inherit seed conventions by construction.
     `et` and `ga` are queued on this same recipe (et explicitly: the
     VoxCommunis park left it as the only route). (MFA note: the PyPI
     wheel is unusable without conda-forge's `kalpy` —
     `conda create -n mfa -c conda-forge montreal-forced-aligner`.)
4. **MFA model-repo dictionaries — checked 2026-11-27; no arbiter for the
   weak locales.** The index is the GitHub Releases of
   `MontrealCorpusTools/mfa-models` (one release per model, tag
   `dictionary-<name>-v<ver>`; the release body carries maintainer, phone
   set, word count and license; human-readable mirror at
   mfa-models.readthedocs.io). `mfa model list` comes back empty on a
   fresh install because its unauthenticated GitHub API calls fail
   silently — read the releases API with a token instead. 143
   dictionaries; the suffix names the source: `_cv` is Vox Communis with
   an **Epitran** phone set (kazakh_cv, dutch_cv, …) — the same
   Epitran-derived material already parked under VoxCommunis, not an
   independent lexicon; `_mfa` is curated, **CC BY 4.0** (compatible with
   these bundles). Curated dictionaries overlapping ours: english
   (US/UK), german, french, russian, spanish, portuguese ×3, mandarin,
   korean, ukrainian, czech, polish, swedish, croatian, swahili. **None
   for kk, lb, sq, ne, lv, af, et, ga, lt or no.** Possible enrichment
   where a bundle is smaller than the MFA dictionary (swedish_mfa 49,655
   vs `sv` 22,766; croatian_mfa 61,060 vs `hr` 26,346 — but hr's only
   voice is a grapheme model): same harvest → seed-agreement → fold →
   audit pipeline as kaikki. Not a route to cleaning the thin locales.
   **`swedish_mfa` tried the same day and parked** (49,655 words, 37,858
   beyond our `sv` seed): after folding notation (tone letters → stress
   mark, dental diacritics and aspiration stripped, ʋ → v) the two
   dictionaries agree on 55% of the 11,797 shared words with stress
   ignored and 16.5% with it — a different transcription tradition, not
   stray symbols: retroflexes written `ɖ ʈ` where the seed has `r d`,
   `r t`; `ʂ` where the seed has `ɕ`; `'eː` against `'ɛ`; vowel length
   (`'ɪ`/`'iː`, `'a`/`'ɑː`); reduced unstressed vowels in the seed
   (`ʊ`) against full ones in MFA (`ɔ`). Only 40% of MFA entries carry a
   tone, so stress is absent from most of them while the seed marks it on
   every word. The kaikki fills that shipped agree with their seed at
   88–97%; this is in the parked VoxCommunis range (42–73%).
5. **Epitran (MIT)** — third voter for distillation next to ByT5
   small/tiny, and a fold reference for thin scrapes (kk, lt).
6. **UniMorph (CC BY-SA 4.0)** — inflection tables × our validated G2P
   = synthetic P2G training data at scale for the P2G-weak languages
   (isl 12%, hun 10%, swe, fin 10.4%).

## Per-locale gems (license check before use)

Lexique (fr), NST/Språkbanken (sv/no — check Nordic terms), EKI/Filosoft
(et), IPhOD/BEEP (en variants).

## Vocabulary scoping: where coverage actually hurts (2026-11-19)

`scripts/scope_vocabulary.py` measures each bundle's dictionary against
a ~30k-token Wikipedia sample per locale (cached under `runs-cv-scope/`,
gitignored) plus public Common Voice stats — the scoping step route #3
demanded before any alignment campaign. Reproduce with
`python3 scripts/scope_vocabulary.py` (add `--refresh` to resample).

- `tok_cov` — dictionary hit-rate on running text (the zero-risk tier).
- `est_eff` — plus the per-bundle guesser's holdout exact-match over
  the misses: `tok_cov + (1−tok_cov)·exact`. An **estimate**: holdout
  words are dictionary-like, runtime misses (names, inflections) are
  harder, so weak-guesser rows are optimistic.
- `cv_val_h` — CV *validated* hours (what MFA can align); `miss_typ` is
  an upper bound on general-text need, CV's sentence count bounds what
  alignment can add.

| lang | tok_cov | est_eff | dict | g2p | cv_val_h | cv sent |
|---|---|---|---|---|---|---|
| tn | — | — | — | — | 4.3 | 1,767 |
| kk | 13% | **40%** | 2,259 | 31% | 2.5 | 6,286 |
| lv | 12% | **46%** | 1,704 | 39% | **269** | 33,913 |
| lb | 38% | 69% | 3,797 | 51% | ~0 | 7 |
| no | 35% | 70% | 2,714 | 54% | 2.3 | 4,419 |
| ne | 14% | 75% | 2,135 | 71% | 1.4 | 1,321 |
| ga | 63% | 76% | 9,546 | 35% | 15 | 4,730 |
| sq | 24% | 82% | 4,866 | 76% | 9.1 | 50,009 |
| af | 47% | 85% | 2,073 | 71% | 1 | 4,826 |
| et | 17% | 88% | 2,747 | 85% | 63 | 10,874 |
| ku | 9% | 96% | 2,132 | 95% | 82 | 17,034 |
| de | 72% | 98% | 277,912 | 94% | 1,399 | 2.0M |
| hu | 55% | 98% | 67,835 | 96% | 139 | 326,553 |
| ka | 40% | 99% | 24,647 | 99% | 266 | 137,656 |

**Post-campaign state (2026-11-20, same Wikipedia samples re-scored):**
the table above records the pre-campaign scoping snapshot. Since then:
`lv` 1,704 → 42,919 entries — **tok_cov 12% → 67%, est_eff 46% → 94%**
(guesser 39% → 83.3%; the residual misses are English intrusions,
numerals, and a handful of function words); `ku` shipped at 2,559
(+ kaikki fill; est_eff 92% — the dictionary tier doubled but the
guesser's holdout now includes kaikki's harder inflected forms);
`tn` shipped at 1,974 (alignment-harvested; est_eff 97% on first
measurement). kk remains the weakest locale (VoxCommunis parked; thin
audio). **kaikki fill (2026-11-26):** `no` 2,714 → 10,707 entries
(guesser 54.4% → 76.1%) and `af` 2,073 → 2,303 (71.2% → 76.4%) —
kaikki rows folded through each language's existing fold plus a
narrow-diacritic cleanup (`scripts/fold_kaikki_fill.py`): 88.9% /
97.1% agreement with the seed on shared words, 0.009% / 0.434%
voice-drop.

**What it settles.** Baselines validate the tiered architecture —
de/hu/ka sit at 98–99% effective despite 40–72% dictionary coverage,
because their guessers are strong; **across-the-board CV+MFA would buy
nothing there**. The archive's real exposure is concentrated:

1. **`lv` is the campaign jackpot** — worst effective coverage in the
   archive (46%) *and* 269 validated CV hours (33,913 sentences).
   Alignment there multiplies a 1,704-entry dictionary many times over.
2. **`kk` is the opposite pole** — equally weak (40%) but 2.5 h of
   audio: CV cannot save it. Route stays kaikki/Epitran/MFA-dict
   (routes #4/#5), as already ranked.
3. **`et` (63 h), `ga` (15 h), `ku`/kmr (82 h), `tn` (4.3 h, forced)**
   are the remaining viable alignment targets, in that order of
   expected gain-per-hour; ga's opaque orthography makes dictionary
   rows the only fix for its 35% guesser.
4. **Function-word fill — tried, measured, reverted.** The top misses at
   et/af/no are not long-tail words but `ja/oli/ka`, `op/om/na`,
   `etter/seg/eller`. Verified in the raw kaikki dump (2026-11-26):
   Wiktionary has **no IPA** for them (`men`, `da`, `også`: empty
   `sounds`; `eller`: audio only) — more scraping cannot fix this.
   `scripts/distill_missing.py` distills them with the archive's 2-vote
   rule, and its `--validate` measures that rule on held-out rows where
   the reference is known. On random held-out words the agreed outputs
   are **correct only 33–73% of the time — at or below the WFST guesser
   those words would otherwise reach** (no 33% vs 74%, af 59% vs 68%,
   sq 73% vs 76%, lb 55% vs 51%). Adding espeak-ng as an independent
   third voter helps (no 47%, af 68%, sq 77%) but still does not beat the
   guesser. An earlier commit shipped 151 af + 104 no rows on a two-vote
   rule plus inspection; that was reverted — the rows were model output
   of unproven accuracy on the most frequent words. **Success criterion
   for v3:** three-way precision must beat each locale's own guesser
   with margin, at n ≥ 100 held-out rows. Not reachable for `ku` (tag
   postdates the v2 corpus) or `et` (grapheme voice — no consumer).
5. `lb`/`no`/`ne` have almost no CV audio — cheap sources only
   (kaikki headroom, NST/Språkbanken for no).

Caveats: Wikipedia proxies runtime text, not CV's read-sentence
distribution; est_eff is optimistic where the guesser is weak; foreign
intrusions (English `the` in ga text) inflate miss counts slightly
(script purity per locale is in `audit/vocabulary-scoping.json`).

## Verifiers only — never ingest

MMS lexicons (**CC-BY-NC** — would contaminate the whole permissive
chain), espeak-ng/coqui lexicons inside voice archives (GPL chain — see
`docs/espeak-data-verification.md`), CELEX2 (no-redistribution).
