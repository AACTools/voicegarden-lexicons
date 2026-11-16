# espeak-ng-data: what it is, and how VoiceGarden can use it (verification only)

Investigation for [#5](https://github.com/AACTools/voicegarden-lexicons/issues/5),
after the licensing correction: **espeak-ng-data is a verification input,
never a bundle source.** Bundle data derives from WikiPron/Wiktionary (CC
BY-SA) only. This note records what the archives actually contain and what
the verification path costs.

## What is inside a voice archive

`sherpa-onnx-tts-models` 1.4.0 records `espeak_data: "espeak-ng-data"` on
576 piper / coqui / mimic3 / melo voices. Unpacking one
(`vits-piper-is_IS-bui-medium.tar.bz2`, 64 MB) shows:

* `espeak-ng-data/` — 19 MB, 120 files. This is **espeak-ng's full runtime
  data**, identical in kind across voices: compiled `*_dict` binaries for
  every espeak language (af_dict … yue_dict), the phoneme tables
  (`phondata`, `phontab`, `phonindex`, `phondata-manifest`), `intonations`,
  and `voices/` per-language configs. It is *not* per-voice data — the
  per-voice selector is just the voice's language code (`is` here).
* `tokens.txt` + `*.onnx.json` — the model's own phone inventory
  (`phoneme_id_map`), which is what the wrapper already maps our phones
  against (issue #3 audit).
* The compiled dictionaries are espeak-ng's binary format (header + hash
  table + rules). Decoding them without espeak-ng code means reimplementing
  espeak's lookup — GPL-adjacent territory and pointless: the same
  phonemization is one `espeak-ng --ipa` call away.

Licensing: the data ships under espeak-ng's terms (GPL-adjacent; the
archives redistribute it with the voice). Using it as a phonetic *source*
for bundles would contaminate the CC BY-SA chain — the same reason floravox
has a strict no-espeak policy. Running the GPL `espeak-ng` binary locally to
produce a *comparison* is fine: nothing espeak-derived enters a bundle.

## What verification actually costs: a measured example

We ran espeak-ng 1.52 (`-v is -q --ipa`) over the 31 hand-written Icelandic
number entries (`staging/isl/manual.tsv`) and compared with our IPA:

* **exact match: 2/31 (6%)** — raw comparison is useless as a quality gate.
* But nearly every difference is a *systematic convention gap*, not a
  pronunciation disagreement. Icelandic pattern:

  | ours (Wiktionary broad) | espeak-ng --ipa | rule |
  |---|---|---|
  | `eiː a uː o uː` | `eɪː aʊː oʊː` | digraph spelling, element-wise vs fused |
  | `t` medial fortis | `d` | espeak writes unaspirated stops as lenis letters |
  | `v` | `ʋ` | symbol choice |
  | `ɪ ʏ` | `i y` | espeak does not mark laxness |
  | `þrj…` | `þ ə r j…` | epenthetic schwa before Þr- clusters |
  | `m̥` | `m` (+ following `d`) | devoicing diacritic vs assimilation |
  | `tʰ` | `t` | aspiration only initially, often unmarked |

  After a ~10-rule fold table (Icelandic), the remaining disagreements were
  genuine minor convention residue (e.g. espeak lacks the `j` glide in
  *níunda*), not errors.

## Verdict

1. **As a source: no.** Blocked by licensing, and the symbols would need
   the same fold work anyway.
2. **As a verifier: yes, with per-language work.** The archive tells you
   the voice's original front-end would have phonemized `X` as `Y`; a
   per-language fold table (~10–20 rules) turns that into a second opinion
   on scraped data. It is free (the data ships with the voice) and needs
   only the system `espeak-ng` binary at audit time — never at runtime and
   never in the bundle.
3. **Priority ranking:** verification value is highest exactly where our
   data is thinnest (thin scrapes: kaz, lit; narrow-only candidates: kat,
   kor, nep) and where we hand-augment (the Icelandic numbers were checked
   this way — the fold confirmed structure on all 31 entries).
4. **The wrapper's runtime route (route 2 in #5)** is independent of us:
   it may generate install-time lexicons from the archive's espeak-ng-data
   under its own licensing judgement. VoiceGarden bundles remain the
   WikiPron-sourced alternative for projects that need permissive data.

## Proposed follow-up (not built yet)

`scripts/verify_against_espeak.py` — probe word list per language →
`espeak-ng --ipa` → fold table (`audit/espeak-folds/<lang>.tsv`) → report
agreement rate next to the bundle in `expanded.json` / `lexicons.json`.
Start with the languages that already ship bundles + have voices (de, fr,
es, it, ru, is, …), reuse the Greek-fold precedent from
`docs/distill-audit.md` for reporting.
