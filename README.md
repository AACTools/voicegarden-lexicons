# voicegarden-lexicons

> Permissively-licensed pronunciation lexicons for TTS — the espeak-ng
> replacement. Part of the [VoiceGarden](https://github.com/AACTools)
> group.

The universal phonemizer today is espeak-ng — and it's GPL, which is why
embedders keep reimventing per-language G2P and why sherpa-onnx is
looking for a way out ([k2-fsa/sherpa-onnx#3731](https://github.com/k2-fsa/sherpa-onnx/issues/3731)).
This archive publishes **MIT/BSD lexicons, keyed by language and voice
alphabet**, consumable with one line from Rust (or a plain download).

## What's published

Per language (`<lang>.tar.gz` release artifacts):

| File | Contents |
|---|---|
| `<lang>.fst` + `<lang>.pho` | floravox FST lexicon (word → phonemes), mmap-friendly |
| `NOTICE` | source + license provenance |

Per-language Phonetisaurus OOV WFSTs are planned — they will be
**trained on these IPA lexicons** so OOV output matches the bundle's
alphabet (the published cmudict WFST emits ARPABET and is deliberately
not bundled for that reason).

`lexicons.json` — the manifest: one entry per language with download
URL, SHA-256, sizes, license, and source provenance.

### Sources (data licenses travel with the bundles)

| Source | License | Languages |
|---|---|---|
| [gruut-lang-*](https://pypi.org/project/gruut/) | MIT | ca, cs, de, en, es, fa, fr, it, nl, pt, ru, sv, sw |
| [CMUDict](https://github.com/cmusphinx/cmudict) | BSD-2-style | en (alternate `en-cmudict`, ARPABET→IPA via floravox ingest) |

gruut is the phonemizer piper's non-English voices were trained with, so
its symbols map onto those voices' inventories with **zero dropped
symbols** through [floravox](https://github.com/AACTools/floravox)'s
symbol resolution (validated: 236k symbols sampled from gruut de against
piper `de_DE-thorsten`, 0.00% dropped).

## Rust consumption

```console
cargo add voicegarden-lexicons
```

```rust
use voicegarden_lexicons::LexiconArchive;

let archive = LexiconArchive::default()?;        // fetches/caches the manifest
let bundle = archive.fetch("de")?;               // downloads once, caches
let mut g2p = bundle.phonemizer()?;              // lexicon (+WFST) + spelling fallback
// feed to floravox_core::synth::Synthesizer with any piper/MMS voice
```

Caching lives under `~/.voicegarden/lexicons` (override with
`VOICEGARDEN_LEXICON_DIR`); the base URL is overridable for mirrors
(`VOICEGARDEN_LEXICON_URL`).

## Joining with voice models

The manifest keys on `lang_code` — the same shape
[sherpa-onnx-tts-models](https://github.com/AACTools/sherpa-onnx-tts-models)
uses per model — so routing a voice to its phonemization data is a
manifest join: `model.language[0].lang_code → lexicons[lang]`. A merged
manifest (voices + lexicons in one registry) is the planned end state.

## Building locally

```console
make all          # downloads sources, builds every bundle + manifest
make LANG=de      # one language
cargo test        # fetcher-crate tests (offline, fixtures)
```

Requires: python3, curl, and `cargo install --git https://github.com/AACTools/floravox --tag v0.5.1 --bin floravox-fst-compile`.

## License

The build code here is Apache-2.0 OR MIT. Each bundle carries its data
source's license — see `lexicons.json` per entry and the NOTICE files
inside bundles. No GPL data is included.
