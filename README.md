# voicegarden-lexicons

Pronunciation dictionaries for text to speech, published under permissive licenses and free to download. Part of the [VoiceGarden](https://github.com/AACTools) group.

## The problem

Before a TTS engine can speak, it has to turn each word into phonemes. The tool everyone uses for that job is espeak-ng, but espeak-ng is GPL, so projects that need to stay Apache or MIT cannot ship it. sherpa-onnx is removing it for exactly this reason ([k2-fsa/sherpa-onnx#3731](https://github.com/k2-fsa/sherpa-onnx/issues/3731)).

This archive is the replacement: MIT and BSD lexicons, one bundle per language, downloadable as plain files or through a small library.

## What is in a bundle

Each language is a `<lang>.tar.gz` containing:

| File | What it is |
|---|---|
| `<lang>.fst` + `<lang>.pho` | the lexicon in floravox's format: word to space-separated phonemes |
| `phonetisaurus.fst` | a Phonetisaurus model trained on this lexicon, for words the lexicon does not know |
| `lexicon.txt` | the same data in sherpa-onnx's plain text format (`word\tp1 p2 p3`), so any sherpa-onnx binding (Python, C, C++, Node) can use it with no new code |
| `NOTICE` | where the data came from and its license |

`lexicons.json` lists every bundle: download URL, SHA-256, size, entry count, and license. Fourteen languages are published:

| Bundle | Entries | | Bundle | Entries |
|---|---|---|---|---|
| de | 277,912 | | ru | 545,315 |
| en | 124,384 | | es | 595,857 |
| en-cmudict | 135,166 | | pt | 81,219 |
| fr | 90,114 | | + ca, cs, fa, it, nl, sv, sw | |

## Why the data is good

The lexicons come from [gruut](https://pypi.org/project/gruut/) (MIT), and gruut is the phonemizer piper's non-English voices were trained with. That matters: the symbols already match the voices. We measured 236,000 symbols from the German lexicon against the piper German voice and 0.00% failed to resolve. English also has a CMUDict bundle (BSD-style license). Each bundle also carries a Phonetisaurus model for unknown words, trained on that same lexicon, so its symbols match by construction. (The separately published cmudict WFST is deliberately not used because it outputs ARPABET, which would not match.) On German, trained on the 95% split and evaluated on the held-out 5%, it scores 93.6% exact pronunciations with a 1.4% phoneme error rate. Every bundle records its own scores in `lexicons.json`.

## Three ways to use it

1. From Rust:

```console
cargo add voicegarden-lexicons
```

```rust
use voicegarden_lexicons::LexiconArchive;

let archive = LexiconArchive::default_archive()?;   // reads the manifest
let bundle = archive.fetch("de")?;                  // downloads once, then caches
let mut g2p = bundle.phonemizer()?;                 // lexicon + spelling fallback
```

Bundles are cached under `~/.voicegarden/lexicons`. Set `VOICEGARDEN_LEXICON_DIR` to move the cache or `VOICEGARDEN_LEXICON_URL` to use a mirror.

2. From any language with an FFI: [floravox](https://github.com/AACTools/floravox) builds `libfloravox_capi.so` with a small C API (`vg_phonemizer_open_lang`, `vg_phonemize_token`, free). Python via ctypes:

```python
import ctypes
lib = ctypes.CDLL("libfloravox_capi.so")
lib.vg_phonemizer_open_lang.restype = ctypes.c_void_p
lib.vg_phonemize_token.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                   ctypes.c_char_p, ctypes.c_int]
p = lib.vg_phonemizer_open_lang(b"de")
buf = ctypes.create_string_buffer(512)
lib.vg_phonemize_token(p, b"guten", buf, len(buf))
print(buf.value.decode())     # g uː t ə n
```

3. As plain files: download a bundle from [releases](https://github.com/AACTools/voicegarden-lexicons/releases). If you use sherpa-onnx, point its lexicon setting at `lexicon.txt` inside.

## Matching voices to languages

`lexicons.json` keys each bundle on `bcp47`, the same language code the [sherpa-onnx-tts-models](https://github.com/AACTools/sherpa-onnx-tts-models) registry records per model. Routing a voice to its phonemization data is a lookup across the two files. The plan is to merge them into one registry later.

## Building locally

```console
make all          # download sources, build every bundle + manifest
make build-lang LANG=de
cargo test        # library tests, offline
```

You need python3, curl, and `cargo install --git https://github.com/AACTools/floravox --tag v0.6.0 floravox-g2p --bin floravox-fst-compile`. `docs/build.md` describes the pipeline step by step.

## License

The build code here is Apache-2.0 OR MIT. Each bundle carries its data source's license, recorded in `lexicons.json` and the NOTICE inside the bundle. No GPL data is included.
