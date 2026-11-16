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
| ar_JO, hi_IN, id_ID, tr_TR, ur_PK, fa_IR, pl_PL, ro_RO, sk_SK, sl_SI, sv_SE, nl_NL/BE, ca_ES, cs_CZ, da_DK, el_GR, fi_FI | (base where gruut has a pack) | ara/hin/ind/tur/urd/fas/pol/ron/slk/slv/swe/nld | — |

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
| hr | hr | coqui-hr-cv (1) | hbs_latn_broad_filtered | 26,346 |
| sr | sr | piper-sr_RS (1×3) | hbs_cyrl_broad_filtered | 23,169 |
| kk | kk | piper-kk_KZ (3×3) | kaz_cyrl_broad | 669 ⚠ thin |
| lb | lb | piper-lb_LU (1×3) | ltz_latn_broad | 3,797 |
| lt | lt | coqui-lt-cv (1) | lit_latn_broad | 437 ⚠ thin |
| ml | ml | piper-ml_IN (2×3) | mal_mlym_broad | 9,477 |
| mt | mt | coqui-mt-cv (1) | mlt_latn_broad_filtered | 15,789 |
| no | no | piper-no_NO (1×3) | nob_latn_broad_filtered | 2,714 (Bokmål) |
| sq | sq | piper-sq_AL (1×3) | sqi_latn_broad | 4,866 |
| yue | yue | cantonese-yue-xiaomaiiwn (1) | yue_hani_standard_broad | 106,238 |

Notes:
- `sr` / `hr` are one Serbo-Croatian scrape split by script: the Serbian
  piper voice consumes Cyrillic text, the Croatian coqui voice Latin.
  Training + provenance live in `staging/hbs/`.
- `no` carries Bokmål data under the macrolanguage tag because that is
  what the voice is labelled; the expanded `nob` bundle (bcp47 `nb`) is
  the distilled superset and should be preferred once the wrapper aliases
  `no` → `nb`.
- hbs phones carry pitch-accent diacritics (ě ôː) from Wiktionary; the
  wrapper's combining-mark decomposition handles them as it did for ru.
- ⚠ thin scrapes (kk 669, lt 437): the dictionary tier is nearly empty;
  most words fall through to the per-bundle Phonetisaurus. Usable but
  flagged — NOTICE carries the warning.

## Blocked / needs study (issue #5 "honest, not silent")

| locale | voices | WikiPron status | verdict |
|---|---|---|---|
| ne (Nepali) | piper ne_NP (3) + mimic3 (1) | **narrow only** (2,329) | `blocked:conventions` — narrow→broad fold needed before harvest |
| ko (Korean) | mimic3-ko_KO (1) | **narrow only** (36,146 filtered) | `blocked:conventions` |
| ka (Georgian) | piper-ka_GE (1×3) | **narrow only** (20,894) | `blocked:conventions` |
| hu (Hungarian) | piper-hu_HU (2×3) | **narrow only** (64,689) | `blocked:conventions` (bonus locale, not in #5's table) |
| uk (Ukrainian) | piper-uk_UA (2×3) + coqui | **narrow only** (53,021) | `blocked:conventions` |
| vi (Vietnamese) | piper-vi_VN (3×3) | narrow only, 3 dialects (27–32k each) | `blocked:conventions` + dialect choice |
| lv (Latvian) | piper-lv_LV (1×3) | **narrow only** (1,437) | `blocked:conventions` |
| ku (Kurdish) | piper-ku_TR (1×3) | **none** | `blocked:no-data` |
| tn (Tswana) | mimic3-tn_ZA (1) | **none** | `blocked:no-data` |
| zh_CN (Mandarin) | piper zh_CN (2×3) | cmn_hani_broad 168,655 (staged, untrained-packaged) | follow-up: cmn bundle |
| is (Icelandic) | piper is_IS (4×3) | published, numbers were broken | **fixed this pass** — 37 hand-verified number entries (`staging/isl/manual.tsv`), bundle rebuilt |

The narrow-only set shares one root cause: WikiPron's broad (phonemic)
scrape never happened for them (the scrapes that exist are narrow
allophonic). A narrow→broad fold study (per-language diacritic-stripping
rules, validated against the voice's `tokens.txt` via the #3 ladder) is
the single unlock for ne/ko/ka/hu/uk/vi/lv — roughly 60 voices.

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
