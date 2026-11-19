# Sherpa piper voice ↔ VoiceGarden bundle coverage map

Working record for
[#3](https://github.com/AACTools/voicegarden-lexicons/issues/3) and
[#5](https://github.com/AACTools/voicegarden-lexicons/issues/5). Voice
inventory from `AACTools/sherpa-onnx-tts-models` @ 1.4.0 (`models.json`,
576 espeak_data-bearing piper/coqui/mimic3/melo voices); WikiPron counts
from `CUNY-CL/wikipron` `data/scrape/summary.tsv` (broad phonemic files,
2026-11).

## Published before this pass

| piper locale | bundle (base) | bundle (expanded-v2) | wrapper audit |
|---|---|---|---|
| de_DE | `de` | `deu` | 0% drop (SHERPA_CATALOG_AUDIT fr/pt/es/it/ru + deu sample) |
| en_US / en_GB | `en`, `en-GB`, `en-cmudict` | `eng-US` | — |
| es_ES / es_AR / es_MX | `es` | `spa-ES`, `spa-LatAm` | 0% drop |
| fr_FR | `fr` | `fra` | 0% drop |
| it_IT | `it` | `ita` | 0% drop |
| pt_BR | — | `por-BR` | 0% drop (audited vs cadu-medium) |
| pt_PT | `pt` | `por-PT` | — |
| ru_RU | `ru` | — | 0% drop |
| pl_PL | — | `pol` | **audited this pass**: 0.158% drop vs `piper-pl_PL-gosia-medium` tokens (204,409 words, digits excluded); unresolved = `r̝`×323 (WikiPron's notation for graphemic *rz*, ≈ `ʐ` — a one-symbol wrapper fold takes the drop to ~0.003%), ã×4, ‿×1, é×1 |
| ar_JO, hi_IN, id_ID, tr_TR, ur_PK, fa_IR, pl_PL, ro_RO, sk_SK, sl_SI, sv_SE†, nl_NL/BE, ca_ES, cs_CZ, da_DK, el_GR, fi_FI | (base where gruut has a pack) | ara/hin/ind/tur/urd/fas/pol/ron/slk/slv/swe/nld | — |

† **sv is no longer gruut-built**: gruut-lang-sv carries Swedish tone
digits the sv voices cannot consume (12,063 rows, 58.9% word-drop —
found by the round-3 shipped-artifact audit). The base `sv` bundle now
builds from the folded staging union (`staging/swe/merged.tsv`,
`fold_swedish.py`), 22,766 entries, audited vs sv_SE-alma.

**pt_BR note (issue #3):** the base `pt` bundle is gruut `pt-PT` data
(bcp47 `pt-PT`). pt_BR voices should resolve to the **expanded `por-BR`**
bundle (bcp47 `pt-BR`); routing pt_BR → base `pt` would read European
Portuguese phonology. The wrapper should prefer expanded por-BR for `pt-BR`
locales (its prefix matcher already picks `pt-BR` over `pt` when both
manifests are loaded).

## This pass: new base bundles (issue #5 track 1)

All WikiPron-scraped (CC BY-SA 4.0), packaged as base bundles in
`dist/lexicons.json`:

| bundle | bcp47 | voices it serves | WikiPron source | entries |
|---|---|---|---|---|
| af | af | mimic3-af_ZA (1) | afr_latn_broad_filtered | 2,127 |
| cy | cy | piper-cy_GB (2) | cym_latn_broad | 14,579 |
| et | et | coqui-et-cv (1) | est_latn_broad | 2,747 |
| eu | eu | piper-eu_ES (2) | eus_latn_broad | 11,977 |
| ga | ga | coqui-ga-cv (1) | gle_latn_broad | 9,546 |
| gu | gu | mimic3-gu_IN (1) | guj_gujr_broad | 4,086 |
| hr | hr | none — coqui-hr-cv is a grapheme model (see below) | hbs_latn_broad_filtered | 26,346 |
| sr | sr | piper-sr_RS (1×3) | hbs_cyrl_broad_filtered | 23,169 |
| kk | kk | piper-kk_KZ (3×3) | kaz_cyrl_broad | 669 ⚠ thin |
| lb | lb | piper-lb_LU (1×3) | ltz_latn_broad | 3,797 |
| lt | lt | coqui-lt-cv (1) | lit_latn_broad | 437 ⚠ thin |
| ml | ml | piper-ml_IN (2×3) | mal_mlym_broad | 9,477 |
| mt | mt | coqui-mt-cv (1) | mlt_latn_broad_filtered | 15,789 |
| no | no | piper-no_NO (1×3) | nob_latn_broad_filtered | 2,714 (Bokmål) |
| sq | sq | piper-sq_AL (1×3) | sqi_latn_broad | 4,866 |
| yue | yue | cantonese-yue-xiaomaiiwn (1) | yue_hani_standard_broad | 106,238 |

## Second wave: kaikki harvest + convention folds

`scripts/harvest_kaikki.py` extracts word→IPA from kaikki.org's full
Wiktionary dumps (CC BY-SA, same chain as WikiPron, but retaining
inflected forms WikiPron's scrape drops — the P2G direction's missing
paradigms). Measured effect on Icelandic: +5,768 inflected fills took
staging P2G exact from 7.8% to 12.0%; the expanded `isl` bundle grew
to 43,427 entries. Swedish added almost nothing (en.wiktionary is
IPA-poor there — 5.6k); Finnish (4.4 GB dump) not yet pulled.

| bundle | bcp47 | voices | source | entries | phone audit vs real voice |
|---|---|---|---|---|---|
| hu | hu | piper-hu_HU (2×3+4) | kaikki Hungarian | 67,835 | **0.000% drop** vs anna-medium; g2p 96.0%/PER 1.0% |
| ka | ka | piper-ka_GE (1×3) | kaikki Georgian, folded | 24,647 | **0.004%** vs natia-medium; g2p 99.0%/PER 0.2% |
| ko | ko | mimic3-ko_KO (1) | kaikki Korean, folded | 35,159 | **0.13%** vs kss tokens; laryngeal contrasts merged (see fold note) |
| uk | uk | piper-uk_UA-lada + coqui (lada only — ukrainian_tts is grapheme-based) | kaikki Ukrainian, folded | 55,209 | **0.004%** vs lada; glide breves → j/w; g2p 80.2% |
| vi | vi | piper-vi_VN (3×3) | kaikki Vietnamese (Hanoi), folded | 28,749 | **0.010%** vs vais1000; Chao tone letters → espeak tone digits (ngang=1 huyền=2 sắc=3 hỏi=4 ngã=5 nặng=6, per espeak's ph_vietnam definitions — tone 7 is espeak's clause-final ngang variant, not a lexical tone) |
| ne | ne | piper-ne_NP (3) + mimic3 (1) | kaikki Nepali, folded | 2,135 ⚠ | **0.047%** vs ne-google; aspiration as ʰ tokens, nasal vowels as vowel+̃ (both verified in the model inventory) |
| lv | lv | piper-lv_LV (1×3) | kaikki Latvian, folded | 1,704 ⚠ | **0.235%** per-word vs aivars; pitch accents → plain long vowels (espeak marks no tones) |
| zh | zh-CN | piper-zh_CN (2×3+6) | WikiPron cmn, folded | 147,316 | **0.005%** vs huayan-medium (digit words excluded, the wrapper-audit method); dictionary-only (Han WFSTs are huge and weak — OOV falls back char-wise to the dictionary) |

## Third wave: wave-1 bundles audited against their voices

The voice-token audit (`scripts/audit_voice_tokens.py`, vendored
inventories in `audit/voice-tokens/`) was extended to every wave-1
bundle — and caught the sr-class bug in five more places. All folded
and rebuilt:

| bundle | drop before | fold | drop after |
|---|---|---|---|
| sr | 98.7% | pitch accents → plain (`fold_serbian.py`) | 0.000% |
| hr | 97.9% | same (both scripts) | 0.000% vs the sr voice; vs its own coqui voice **79.5% — a grapheme model** (see below) |
| fin (expanded, published) | 15.50% | juncture ˣ stripped (`fold_finnish.py`) | 0.005% |
| af | 43.8% | χ→x, ɦ→h, ʋ→v, glide breves (`fold_afrikaans.py`) | 0.386% |
| cy | 4.7% | voiceless sonorants → plain (`fold_welsh.py`) | 0.014% |
| ml | 6.6% | ä→aː, ʱ→ʰ, dentals (`fold_malayalam.py`) | 0.021% |
| no/nob | 6.0% | tonal accents → plain (`fold_norwegian.py`) | 0.000% |

Clean without folds (audit now guards them): eu 0.017%, lb 0.369%,
sq 0.452%, kk 1.943% (thin).

**Grapheme/transliteration voices — no lexicon can serve them:** the
only voices for bg, et, ga, hr, lt, mt are coqui character-token models
(`a b c … <PAD> <EOS>`), and the only gu voice is a mimic3 ASCII
transliteration model. hr joined this list late (issue #12): its
inventory was only vendored in 2026-11, and the folded `hr` bundle
measures **79.496% drop** vs coqui-hr-cv — the inventory (Latin +
Cyrillic letters, punctuation) carries zero IPA symbols, so the
multi-char `<BOS>/<EOS>/<PAD>` tokens are a red herring; a lexicon
never emits them, and keying on letters would just re-spell what the
voice already reads natively. Their `bg/hr/et/ga/lt/mt/gu` bundles
remain valid G2P/P2G dictionary products but provision **no TTS
gain** for those voices; the wrapper should treat those locales as
`grapheme-voice: no bundle needed` (recorded in the audit table,
report-only). Every other bundled locale now audits clean against at
least one real voice inventory.

All numbers recomputable: `python3 scripts/audit_voice_tokens.py`
(wired into `make check-release`).

Convention folds (the `blocked:conventions` unlock pattern — per-language
rules validated against the target voice's `tokens.txt`):
- **ka** (`scripts/fold_georgian.py`): ä→ɑ, e̞→ɛ, o̞→ɔ, ɾ→r, devoiced
  spellings (b̥ d̥ ɡ̊)→plain, ʁ→ɣ, labialization stripped; ejectives
  merged into the plain series because the piper ka voices' espeak-derived
  inventories carry no ʼ distinction at all.
- **zh** (`scripts/fold_mandarin.py`): Chao tone contours → espeak tone
  digits {55:1, 35:2, 214:3, 21:3, 51:4, 53:4, 4:4}; WikiPron writes each
  syllable as base contour + ⁻-marked sandhi realization — the sandhi
  layer (what is actually spoken) wins, e.g. 你好 → tones 2 3, not 3 3;
  preglottalized vowels split (ˀa→ʔ a); ä→a, devoicing rings stripped,
  ASCII g→ɡ. zh and yue ship dictionary-only (no Phonetisaurus): Han
  WFSTs weighed 19–25 MB at ~30% exact — OOV falls back char-wise to
  the dictionary, where every Han char carries an entry.
- **ko** (`scripts/fold_korean.py`): narrow vowels to the espeak set
  (a̠→ɐ, ʌ̹→ʌ, o̞→o, e̞→e), h-variants merged, ɲ→n ʲ, and the three-way
  laryngeal contrast (plain/aspirated/fortis/unreleased) merged to
  plain — the ko voice family's token inventory distinguishes none of
  it (validated against kss's 50 tokens, 0.13% drop).
- **sr/hr** (`scripts/fold_serbian.py`): the four-way Serbo-Croatian
  pitch-accent diacritics (ǎ ě ǒ ȃ …) folded to plain vowels, length
  kept — the sr voice's inventory carries none of the marks. Caught by
  the new voice-token audit: the v0.5.0/v0.5.1 `sr` bundle measured
  **98.7% drop** against its own voice before this fold (sr was never
  voice-audited when it shipped). Both scripts re-folded from the hbs
  union; now 0.000%.
- **fin** (`scripts/fold_finnish.py`): the Wiktionary juncture mark ˣ
  (attached in WikiPron rows, standalone in kaikki) is not in the fi
  voices' inventory — the published expanded `fin` bundle measured
  **15.50% drop** vs harri (26,967 of 174,010 words). Stripped;
  0.005%. The bundle was rebuilt with kaikki inflected fills included.
- **SIGMORPHON 2020 G2P data** (15 languages incl. geo/hun/kor/lit/vie/
  ice, Wiktionary-derived) inspected as a fold reference: conventions
  match kaikki closely (hun 94% exact on shared words after
  segmentation). **Not ingested** — the repo carries no explicit
  license file (Wiktionary CC BY-SA chain is asserted only in the task
  paper); kaikki reaches the same words with an unambiguous grant.

Staged but not yet bundled:
- **fin** — kaikki Finnish is a 4.4 GB pull; it would *enrich* the
  existing expanded `fin` bundle (P2G paradigms), not add a locale.
  Next kaikki pulls for enrichment: swe (via the Swedish-language
  wiktionary dump, not en), isl (done), deu/nld/ita (already
  gruut-sourced; kaikki would add inflected forms).

Notes:
- `sr` / `hr` are one Serbo-Croatian scrape split by script: the Serbian
  piper voice consumes Cyrillic text, the Croatian coqui voice Latin.
  Training + provenance live in `staging/hbs/`; pitch accents folded
  (`scripts/fold_serbian.py`, 0.000% vs the sr voice).
- `no` carries Bokmål data under the macrolanguage tag because that is
  what the voice is labelled; the expanded `nob` bundle (bcp47 `nb`) is
  the distilled superset and should be preferred once the wrapper aliases
  `no` → `nb`.
- ⚠ thin scrapes (kk 669, lt 437): the dictionary tier is nearly empty;
  most words fall through to the per-bundle Phonetisaurus. Usable but
  flagged — NOTICE carries the warning.

## Blocked / needs study (issue #5 "honest, not silent")

| locale | voices | WikiPron status | verdict |
|---|---|---|---|
| hu (Hungarian) | piper-hu_HU (2×3) | narrow only (64,689) | **UNBLOCKED via kaikki** → `hu` bundle (0.000% drop, g2p 96%) |
| ka (Georgian) | piper-ka_GE (1×3) | **narrow only** (20,894) | **UNBLOCKED via kaikki + fold** → `ka` bundle (0.004% drop) |
| ko (Korean) | mimic3-ko_KO (1) | **narrow only** (36,146 filtered) | **UNBLOCKED via kaikki + fold** → `ko` bundle (0.13% drop; laryngeal contrasts merged — the voice inventory distinguishes none) |
| uk (Ukrainian) | piper-uk_UA (2×3) + coqui | **narrow only** (53,021) | **UNBLOCKED via kaikki + fold** → `uk` bundle (0.004% vs lada; the ukrainian_tts voice is grapheme-based, needs no lexicon) |
| vi (Vietnamese) | piper-vi_VN (3×3) | narrow only, 3 dialects (27–32k each) | **UNBLOCKED via kaikki + fold** → `vi` bundle (Hanoi; 0.010%; tone digits follow espeak's ph_vietnam definitions) |
| ne (Nepali) | piper ne_NP (3) + mimic3 (1) | **narrow only** (2,329); kaikki 2.1k | **UNBLOCKED via kaikki + fold** → `ne` bundle ⚠ thin (0.05% drop) |
| lv (Latvian) | piper-lv_LV (1×3) | **narrow only** (1,437) | **UNBLOCKED via kaikki + fold** → `lv` bundle ⚠ thin (0.23% drop) |
| zh_CN (Mandarin) | piper zh_CN (2×3) | cmn_hani_broad 168,655 | **BUNDLED** → `zh` (tone-contour fold, 0.005% drop, digit words excluded) |
| ku (Kurdish) | piper-ku_TR (1×3) | **none** | `blocked:no-data` — Common Voice + MFA is the only permissive route |
| tn (Tswana) | mimic3-tn_ZA (1) | **none** | `blocked:no-data` — same |
| mul (multilingual) | omnivoice / mms-patched (2) | n/a | **out-of-scope** — no `espeak_data` (native front-ends, like MMS); a single-language bundle would be wrong for a multilingual voice |
| is (Icelandic) | piper is_IS (4×3) | published, numbers were broken | **fixed** — 37 hand-verified number entries (`staging/isl/manual.tsv`) + kaikki inflected fills; expanded bundle 43,427 entries |

The narrow-only set shares one root cause: WikiPron's broad (phonemic)
scrape never happened for them (the scrapes that exist are narrow
allophonic). A narrow→broad fold study (per-language diacritic-stripping
rules, validated against the voice's `tokens.txt` via the #3 ladder) is
the single unlock for ne/ko/ka/hu/uk/vi/lv — roughly 60 voices. The
Korean measurement above shows the fold is real work per language
(narrow diacritics are semantic there: tense vs plain vowels, unreleased
stops), so these stay blocked until someone writes and validates the
per-language fold tables.

## Icelandic number fix detail (issue #5)

The `isl` scrape contained 10,002 words but almost no numerals: digits
2–9 (most forms), tólf, every compound tens (þrjátíu…níutíu), and the
ordinals were missing, so digit normalization fell through to the WFST,
which mis-guessed them. Fix: 37 hand-verified entries in
`staging/isl/manual.tsv`, derived from in-dictionary attested patterns
(sjötugasti → sjötíu, níund- forms, tví- cluster forms) and standard
Icelandic phonology written in the scrape's own conventions
(preaspiration `h`, devoicing `r̥`, `a uː`/`o uː`/`ø yː` diphthongs).
`merge_sources.py` now applies `manual.tsv` as a top-priority source.
Cross-checked against espeak-ng (see `docs/espeak-data-verification.md`).
Bundle rebuilt: 37,659 entries, WFST exact 87.2% / PER 2.7%.
