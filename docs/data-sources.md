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
| **VoxCommunis TextGrids** (pacscilab/VoxCommunis) | **CC0-1.0** | pre-made MFA alignments of CV validated splits (~80 locales, CV 17–20) | `tn`: 3,495 grids → 1,974 rows (≥2 alignments each), folded, **0.000%** vs the voice — first permissive tn lexicon. `kmr` evaluated and **parked**: 10,424 rows at 0.000% voice-drop but only **72.9% exact agreement** with WikiPron on shared words (near-misses: `o`/`oː`, `r`/`ɾ`) — below the ku bundle's own 95.3% guesser, so Epitran-derived rows add noise, not coverage. Key honest finding: grid pronunciations are **dictionary-driven** (the aligner's G2P output; audio sets timing, not phonology) — the value is a CC0 *spoken-vocabulary* filter on G2P output, not independent phonetic evidence. `scripts/harvest_voxcommunis.py` |
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
   - *align-it-ourselves track (lv pilot)*: **CV audio acquisition
     changed in Oct 2025** — releases are now exclusively on Mozilla
     Data Collective (datacollective.mozillafoundation.org, account +
     terms acceptance required); the old S3/HF mirrors are dead. The
     lv runbook: MDC → `cv-corpus-lv.tar.gz` → corpus prep →
     `mfa train`+`mfa align` (no pretrained latvian acoustic model:
     train on the CV audio seeded with the kaikki `lv` dictionary) →
     `scripts/harvest_voxcommunis.py` (it parses any MFA TextGrids,
     including ours) → fold to the vendored `aivars` inventory → the
     usual audit/expand-only gates. Scoped value (see the scoping
     table): worst effective coverage in the archive (46%) + 269
     validated hours. MFA install note: the PyPI wheel is unusable
     without the conda-forge `kalpy` binary — use
     `conda create -n mfa -c conda-forge montreal-forced-aligner`.
4. **MFA model-repo dictionaries** (~100 languages) — per-file license
   check needed; many are MIT/CC outputs.
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
4. **Function-word fill first, everywhere thin** — the top misses at
   et/lv/ku are not long-tail words but `ja/oli/ka`, `no/ar/par/bija`,
   `li/bi/ji/ye`: the scrapes skipped them, they carry a huge token
   share, and they hand-verify in minutes. The Icelandic `manual.tsv`
   pattern (`merge_sources.py` top-priority source) applies directly.
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
