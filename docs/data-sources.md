# Data sources: what we tapped, what unlocks what

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
| **per-language convention folds** (ours) | n/a (transforms) | ka, zh, ko | validated against each target voice's real `tokens.txt`: ka 0.004% drop (`fold_georgian.py`), zh 0.107% (`fold_mandarin.py`, Chao contours + sandhi layer → espeak tone digits), ko 0.13% (`fold_korean.py`). This is the template for the remaining narrow-only locales |
| **SIGMORPHON 2020 G2P data** | asserted Wiktionary CC BY-SA in the task paper, **no explicit LICENSE in the repo** | fold reference for geo/hun/kor/lit/vie/ice | used as convention validation only (hun 94% exact vs kaikki). **Not ingested** pending an explicit grant; kaikki reaches the same words unambiguously |

## Next, highest leverage first

0. **ByT5 v3 retraining prep (this PR)**: `langs.json` now carries the
   seven new harvest locales (hun kat kor ukr vie nep lav → 149
   languages) so `scripts/train_byt5/build_corpus.py` can fold the
   new staged corpora into the v3 training set. v3 corpus would gain:
   hu 67.8k, uk 55.2k, ko 35.2k, kat 24.6k, vi 28.7k (plus the kaikki
   inflected fills for isl/fin and the folded conventions for
   sr/hr/af/cy/ml/nob — all now single-convention per language, which
   is exactly what the v2 harmonization was for). Distillation v3 for
   the new expanded candidates follows the same small+tiny agreement
   gate; the distill corpus must be built from the FOLDED merged
   files (clean_distill.py exists because v2's wasn't — see the swe
   incident).
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
