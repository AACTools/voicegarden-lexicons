# Building a bundle, end to end

The build (`build.py`) is deterministic given its sources:

1. Download the source lexicon:
   - gruut languages: the `gruut-lang-<xx>` sdist from PyPI (MIT);
     `lexicon.db` is SQLite (`word_phonemes(word, phonemes, pron_order,
     role)`).
   - `en`: core `gruut` sdist bundles `gruut/data/en-us/lexicon.db`.
   - `en-cmudict`: cmusphinx/cmudict master (BSD-2-style).
2. Convert to floravox TSV: default pronunciation per word
   (`pron_order = 0`), whitespace-normalized phoneme strings.
3. Compile with `floravox-fst-compile` (from the floravox tag recorded in
   `floravox_tag`): `lang.fst` + `lang.pho`.
4. Package `lang.tar.gz` containing the lexicon pair, an optional
   `phonetisaurus.fst` (English bundles carry the BSD-3 cmudict WFST from
   AdolfVonKlein/phonetisaurus-downloads), and a NOTICE with source and
   license provenance.
5. Emit the manifest entry: SHA-256, size, entry count, licenses.

Consumers should verify SHA-256 against `lexicons.json` (the fetcher
crate does this by default).

## Adding a language

Add an entry to `LANGUAGES`/`EXTRAS` in `build.py` and open a PR; CI
builds and validates it. Requirements: a permissively-licensed word→IPA
source whose symbols are compatible with espeak-style voice inventories
(floravox's symbol resolver handles length marks, tie bars, ASCII
homoglyphs, and unsupported diacritics).

## Relationship to sherpa-onnx-tts-models

`lexicons.json` keys on `bcp47`, the same join key that registry exposes
per model (`model.language[].lang_code`), so voice→lexicon routing is a
manifest join today. The planned end state merges both registries into
one published list; until then they stay sibling repos.
