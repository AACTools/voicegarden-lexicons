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
| **per-language convention folds** (ours) | n/a (transforms) | ka, zh, ko, uk, vi, ne, lv, sr/hr, sv, fin, af, cy, ml, no | validated against each target voice's real `tokens.txt` (recomputable: `scripts/audit_voice_tokens.py`): all ≤0.4% per-word drop. This is the template for any future locale |
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
3. **Common Voice (CC0) + MFA forced alignment** — the only permissive
   route for `ku`/`tn` (no lexical data exists anywhere). Labor-heavy;
   produces speech-matched pronunciations rather than transcriber
   conventions. Scope per locale before committing.
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

## Verifiers only — never ingest

MMS lexicons (**CC-BY-NC** — would contaminate the whole permissive
chain), espeak-ng/coqui lexicons inside voice archives (GPL chain — see
`docs/espeak-data-verification.md`), CELEX2 (no-redistribution).
