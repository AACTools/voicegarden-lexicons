# voicegarden-lexicons

Pronunciation dictionaries for text to speech, published under permissive licenses. Part of the [VoiceGarden](https://github.com/AACTools) group.

To speak a word out loud, a speech engine first needs to know how to pronounce it. The usual way is a lookup table: the word on one side, its sounds written as phonemes on the other. The tool most projects reach for, espeak-ng, generates those sounds with rules, but it is GPL licensed, so projects that ship Apache-2.0 or MIT code cannot include it. sherpa-onnx is removing it for that reason ([k2-fsa/sherpa-onnx#3731](https://github.com/k2-fsa/sherpa-onnx/issues/3731)). This archive publishes MIT and BSD pronunciation dictionaries you can ship instead, one bundle per language.

## What is in a bundle

Each bundle is a `<lang>.tar.gz` with five files:

| File | What it is |
|---|---|
| `<lang>.fst` + `<lang>.pho` | the dictionary itself: each word mapped to its phonemes, in floravox's fast-lookup format |
| `phonetisaurus.fst` | a model that guesses pronunciations for words the dictionary does not contain |
| `lexicon.txt` | the same dictionary as plain text (`word<TAB>phonemes`), in the format sherpa-onnx reads, so Python, C, C++, and Node programs can use it directly |
| `NOTICE` | where the data came from and its license |

`lexicons.json` lists every bundle with its download URL, SHA-256, size, entry count, and license. Fourteen languages are published:

| Bundle | Entries | | Bundle | Entries |
|---|---|---|---|---|
| de | 277,912 | | ru | 545,315 |
| en | 124,384 | | es | 595,857 |
| en-cmudict | 135,166 | | pt | 81,219 |
| fr | 90,114 | | + ca, cs, fa, it, nl, sv, sw | |

## Expanded bundles: filling in the missing words

Every dictionary has gaps. The words it lacks are often ordinary ones, and each missing word means the speech engine has to guess the pronunciation at runtime, which is slower and more error-prone than a lookup.

For 11 languages we filled those gaps ahead of time. The process had three steps:

1. We took frequency lists of the most common words in each language and picked out the ones missing from the dictionary.
2. We asked two neural networks (the published [ByT5 G2P models](https://huggingface.co/willwade/byt5-g2p-multilingual), a [small](https://huggingface.co/willwade/byt5-g2p-multilingual) and a [tiny](https://huggingface.co/willwade/byt5-g2p-multilingual-tiny) version, trained independently) to pronounce each missing word. We kept a word only when both networks produced the same pronunciation.
3. We tested the kept pronunciations against dictionary words the networks had never seen, to measure how often an agreed answer is actually right.

Here is what that produced. "Added entries" is how many new words each dictionary gained. "Measured accuracy" is the share of added pronunciations that were exactly right in that test. "Text coverage" is the share of the 50,000 most common words the dictionary can now look up, before and after.

| Bundle | Added entries | Measured accuracy | Text coverage |
|---|---|---|---|
| spa-ES | 31,964 | 100% | 75% to 98% |
| por-PT | 43,491 | 98% (estimate below) | 80% to 99% |
| deu | 37,062 | 97% | 67% to 94% |
| pol | 57,954 | 96% | 48% to 98% |
| ita | 47,365 | 96% | 49% to 88% |
| fra | 43,943 | 93% | 68% to 95% |
| tur | 46,503 | 93% | 12% to 87% |
| spa-LatAm | 51,528 | 92% (estimate below) | 55% to 97% |
| ell | 30,266 | 86% | 10% to 75% |
| swe | 22,900 | 82% | 25% to 48% |
| eng-US | 9,253 | 98% (see note) | 86% to 90% |

Three of these need an explanation:

- English scored only 62% at step 3, so we kept just the words where the Phonetisaurus guesser also agreed with the networks. That brought the measured accuracy of what ships to 98%, at the cost of keeping fewer words.
- Greek and Swedish use the same double-check.
- For por-PT and spa-LatAm we had no held-out test data, so the number shown is the agreement rate from step 2 instead of a measured accuracy. Treat those two as good but not verified.

The bundles live in `dist/expanded/` and use the same file layout as the base bundles. `expanded.json` records, for every language, how many entries came from a dictionary and how many were generated.

One honest caveat: we picked the candidate words from frequency lists, so the coverage gains partly measure our own selection. The full method, per-language test results, and the ten languages we threw away (the networks were not trained on them) are in [docs/distill-audit.md](docs/distill-audit.md).

## Quality and speed, honestly

The engine people compare against is espeak-ng, the GPL rules engine. We measured it on the same machine against the floravox tier chain:

| tier | cold start | per word | resident memory |
|---|---|---|---|
| espeak-ng rules | 10-65 ms | 9 ms | ~5 MB |
| our expanded dictionary (memory-mapped) | <5 ms | <0.1 ms | ~0 |
| our Phonetisaurus guesser | ~650 ms* | ~1 ms | ~70 MB |
| ByT5 tiny neural model (int8 ONNX) | 410 ms | 64 ms | ~122 MB |

*unstripped debug binary, worst case. A warm process pays none of that.

Where espeak-ng still wins: raw speed on a stream of unknown words (9 ms each, no lookup needed), and it never refuses a word. Its rules produce a pronunciation for any input in any of its ~135 languages.

Where this archive wins: for the words people actually write. On random Wikipedia articles, the dictionary tier now answers 38% to 87% of words (depending on language; English 85%, Spanish 87%) in under a millionth of the time espeak needs, and the entries we added carry a measured 92-100% accuracy rate in the symbol conventions piper-family voices were trained with. The remainder falls through to the guesser and neural tiers. Two structural differences stand regardless of numbers: the data is MIT and BSD licensed, so Apache/MIT projects can ship it, and the phoneme symbols match what gruut-based voices expect, which espeak's output does not. This archive also does the reverse direction (phonemes to spelling), which espeak does not.

What we have not done: a fair accuracy comparison against espeak on the same test words. Its transcriptions use a different symbol system, so scoring it against our dictionaries measures symbol mismatch as much as quality. Doing that comparison properly needs a per-language mapping table; until then, we claim the license, the conventions, and the measured dictionary quality, not a knockout.

## Where the data comes from

| Source | License | Languages |
|---|---|---|
| [gruut](https://pypi.org/project/gruut/) | MIT | ca, cs, de, en, es, fa, fr, it, nl, pt, ru, sv, sw |
| [CMUDict](https://github.com/cmusphinx/cmudict) | BSD-style | en (alternate `en-cmudict` bundle) |

gruut is the phonemizer piper's non-English voices were trained with, so its symbol choices match what those voices expect. As a check, we sampled 236,000 symbols from the German lexicon against piper's `de_DE-thorsten` voice: none failed to resolve.

Each bundle's guesser model is trained on that bundle's own dictionary, so its output uses the same symbols. Holdout scores are recorded per bundle in `lexicons.json` (German: 93.6% of held-out words pronounced exactly right, 1.4% phoneme error rate). We do not ship the separately published CMUDict guesser model because it outputs ARPABET, which does not match these IPA dictionaries.

## Three ways to use it

1. From Rust:

```console
cargo add voicegarden-lexicons
```

```rust
use voicegarden_lexicons::LexiconArchive;

let archive = LexiconArchive::default_archive()?;   // reads the manifest
let bundle = archive.fetch("de")?;                  // downloads once, then caches
let mut g2p = bundle.phonemizer()?;                 // dictionary + spelling fallback
```

Expanded bundles work the same way through `LexiconArchive::default_expanded()`. Bundles are cached under `~/.voicegarden/lexicons`. Set `VOICEGARDEN_LEXICON_DIR` to move the cache or `VOICEGARDEN_LEXICON_URL` to use a mirror.

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
| [docs/distill-audit.md](docs/distill-audit.md) | how the expanded bundles were tested: per-language accuracy, the double-check filter, and the ten languages we rejected |
| [docs/byt5-training-evaluation.md](docs/byt5-training-evaluation.md) | how the ByT5 models were trained and how well it worked |

## License

The build code here is Apache-2.0 OR MIT. Each bundle carries its data source's license, recorded in `lexicons.json` and the NOTICE inside the bundle. No GPL data is included.
