# voicegarden-lexicons

Pronunciation dictionaries for text to speech, published under permissive licenses. Part of the [VoiceGarden](https://github.com/AACTools) group.

Text has to be turned into phonemes before a TTS engine can speak it. The tool most projects use for that, espeak-ng, is GPL, so projects that need to stay Apache-2.0 or MIT cannot ship it; sherpa-onnx is removing it for that reason ([k2-fsa/sherpa-onnx#3731](https://github.com/k2-fsa/sherpa-onnx/issues/3731)). This archive publishes MIT and BSD lexicons, one bundle per language.

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

## Expanded bundles (distilled)

A base lexicon covers the words in its source dictionary. Real text runs wider, and the frequent words a lexicon misses are the costly ones: each falls through to the slower OOV tiers. For 11 languages we closed that gap. Frequency wordlists marked the words a lexicon does not know, the published ByT5 G2P models ([willwade/byt5-g2p-multilingual](https://huggingface.co/willwade/byt5-g2p-multilingual), [tiny](https://huggingface.co/willwade/byt5-g2p-multilingual-tiny)) proposed pronunciations, and only words where the small and tiny checkpoints agree were kept. Every language was then audited against held-out dictionary words before shipping; the method, per-language precision numbers, and the languages we rejected are in [docs/distill-audit.md](docs/distill-audit.md).

| Bundle | Added entries | Audited entry accuracy | Top-50k word hit rate |
|---|---|---|---|
| spa-ES | 31,964 | 100% | 75 → 98% |
| por-PT | 43,491 | 98% (agreement) | 80 → 99% |
| deu | 37,062 | 97% | 67 → 94% |
| pol | 57,954 | 96% | 48 → 98% |
| ita | 47,365 | 96% | 49 → 88% |
| fra | 43,943 | 93% | 68 → 95% |
| tur | 46,503 | 93% | 12 → 87% |
| spa-LatAm | 51,528 | 92% (agreement) | 55 → 97% |
| ell | 30,266 | 86% | 10 → 75% |
| swe | 22,900 | 82% | 25 → 48% |
| eng-US | 9,253 | 98% (3-vote) | 86 → 90% |

English needed extra care: unfiltered its entries scored 62%, so it ships only the words where the Phonetisaurus model also agrees (measured 98% on the same split). Greek and Swedish went through the same filter.

Expanded bundles live in `dist/expanded/` with the same file layout as the base bundles. `expanded.json` records what came from a dictionary and what came from distillation, per language.

One caveat, stated plainly: the candidate words came from frequency lists, so the hit-rate gains are by construction. The independent-text validation is a known follow-up.

## Data sources

| Source | License | Languages |
|---|---|---|
| [gruut](https://pypi.org/project/gruut/) | MIT | ca, cs, de, en, es, fa, fr, it, nl, pt, ru, sv, sw |
| [CMUDict](https://github.com/cmusphinx/cmudict) | BSD-style | en (alternate `en-cmudict` bundle) |

gruut is the phonemizer piper's non-English voices were trained with. Measured on German: 236,000 symbols sampled from the lexicon against piper's `de_DE-thorsten` voice, 0.00% failed to resolve.

Each bundle's Phonetisaurus model is trained on that bundle's lexicon, so its output uses the same symbol set. Holdout scores are recorded per bundle in `lexicons.json` (German: 93.6% exact, 1.4% phoneme error rate). The separately published cmudict WFST is not used because it outputs ARPABET, which would not match the IPA lexicons.

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

## Language codes

Bundles are keyed on BCP-47 codes (`de`, `en-US`, ...). The fetcher accepts exact matches and language-prefix matches, so a voice labelled `de-DE` or `pt-BR` resolves to the nearest bundle.

## Building locally

```console
make all          # download sources, build every bundle + manifest
make build-lang LANG=de
cargo test        # library tests, offline
```

You need python3, curl, and `cargo install --git https://github.com/AACTools/floravox --tag v0.6.0 floravox-g2p --bin floravox-fst-compile`. `docs/build.md` describes the pipeline step by step.

## Docs

| Doc | What it covers |
|---|---|
| [docs/build.md](docs/build.md) | the build pipeline, end to end |
| [docs/distill-audit.md](docs/distill-audit.md) | distillation quality: per-language precision, the three-vote filter, what got quarantined and why |
| [docs/dx-evaluation.md](docs/dx-evaluation.md) | measured cold start, latency, and memory against espeak-ng |
| [docs/roadmap-quality.md](docs/roadmap-quality.md) | quality roadmap |
| [docs/critical-evaluation-v2.md](docs/critical-evaluation-v2.md) | the evaluation that started the distillation work (historical) |

## License

The build code here is Apache-2.0 OR MIT. Each bundle carries its data source's license, recorded in `lexicons.json` and the NOTICE inside the bundle. No GPL data is included.
