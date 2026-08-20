//! # voicegarden-lexicons
//!
//! Fetch permissively-licensed pronunciation lexicons for TTS — the
//! espeak-ng replacement, without the GPL. Bundles are published by the
//! [voicegarden-lexicons archive](https://github.com/AACTools/voicegarden-lexicons):
//! MIT gruut lexicons (ca, cs, de, en, es, fa, fr, it, nl, pt, ru, sv,
//! sw), `CMUDict` English, and Phonetisaurus OOV WFSTs, keyed by language.
//!
//! Bundles are downloaded once into a cache dir (`~/.voicegarden/lexicons`,
//! override with `VOICEGARDEN_LEXICON_DIR`), verified against the
//! manifest's SHA-256, and unpacked into floravox FST lexicons.
//!
//! ```no_run
//! use voicegarden_lexicons::LexiconArchive;
//!
//! # fn main() -> anyhow::Result<()> {
//! let archive = LexiconArchive::default_archive()?;
//! let bundle = archive.fetch("de")?;              // cached after first call
//! let mut g2p = bundle.phonemizer()?;
//! use floravox_g2p::TokenPhonemizer as _;
//! assert!(!g2p.phonemize_token("guten").is_empty());
//! # Ok(())
//! # }
//! ```
//!
//! The returned phonemizer is a `LexiconPhonemizer` (lexicon → bundled
//! Phonetisaurus when present → letter-name spelling), ready to hand to
//! `floravox_core::synth::Synthesizer`.

use anyhow::{anyhow, Context};
use flate2::read::GzDecoder;
use serde::Deserialize;
use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::time::Duration;

/// Default manifest + bundle base (GitHub releases of the archive repo).
pub const DEFAULT_BASE: &str =
    "https://github.com/AACTools/voicegarden-lexicons/releases/latest/download";

/// Holdout evaluation of a bundled Phonetisaurus model (trained on the
/// other 95% of the lexicon, decoded through the shipped file).
#[derive(Debug, Clone, Deserialize)]
pub struct PhonetisaurusEval {
    /// Fraction of held-out words phonemized exactly right.
    pub exact_match: f64,
    /// Mean phoneme error rate over decoded words.
    pub per: f64,
    /// Fraction of held-out words that decoded at all.
    pub coverage: f64,
    /// N-gram order of the model.
    pub order: u8,
}

/// One language entry from the archive manifest.
#[derive(Debug, Clone, Deserialize)]
pub struct LanguageEntry {
    /// Bundle id (e.g. `de`, `en`, `en-cmudict`).
    pub lang: String,
    /// Display name.
    pub name: String,
    /// Primary BCP-47 tag — the join key for voice model registries.
    pub bcp47: String,
    /// Lexicon entry count.
    pub entries: u64,
    /// Data license (travels with the bundle).
    pub license: String,
    /// Provenance string (e.g. `PyPI:gruut-lang-de`).
    pub source: String,
    /// The bundled Phonetisaurus OOV model and its holdout evaluation.
    pub phonetisaurus: Option<PhonetisaurusEval>,
    /// Bundle file name within the release.
    pub file: String,
    /// SHA-256 of the bundle tarball.
    pub sha256: String,
}

/// The parsed `lexicons.json` manifest.
#[derive(Debug, Clone, Deserialize)]
pub struct Manifest {
    /// Archive version.
    pub version: String,
    /// Available languages.
    pub languages: Vec<LanguageEntry>,
}

/// Archive client: manifest + bundle cache.
pub struct LexiconArchive {
    base: String,
    cache: PathBuf,
    manifest: Manifest,
}

impl LexiconArchive {
    /// Archive at the default base with the default cache dir.
    /// # Errors
    ///
    /// Network or manifest-parse failures.
    pub fn default_archive() -> anyhow::Result<Self> {
        Self::new(DEFAULT_BASE, default_cache_dir())
    }

    /// Custom base — an `http(s)://` URL (mirror) or a local directory
    /// (offline use, tests) — plus a cache directory.
    /// # Errors
    ///
    /// Network/IO or manifest-parse failures.
    pub fn new(base: impl Into<String>, cache: impl Into<PathBuf>) -> anyhow::Result<Self> {
        let base = base.into();
        let cache = cache.into();
        fs::create_dir_all(&cache).with_context(|| format!("creating {}", cache.display()))?;
        let manifest = Self::fetch_manifest(&base, &cache)?;
        Ok(Self {
            base,
            cache,
            manifest,
        })
    }

    /// The loaded manifest.
    #[must_use]
    pub fn manifest(&self) -> &Manifest {
        &self.manifest
    }

    /// Resolve a language code (or BCP-47 prefix) to its entry.
    #[must_use]
    pub fn entry(&self, lang: &str) -> Option<&LanguageEntry> {
        let want = lang.to_ascii_lowercase();
        let short = want.split(['-', '_']).next().unwrap_or(&want);
        self.manifest
            .languages
            .iter()
            .find(|e| {
                e.lang.eq_ignore_ascii_case(&want)
                    || e.bcp47.eq_ignore_ascii_case(&want)
                    || e.bcp47
                        .split('-')
                        .next()
                        .is_some_and(|p| p.eq_ignore_ascii_case(short) && e.lang == short)
            })
            .or_else(|| {
                // "de-DE" -> bundle "de"; prefer the plain gruut bundle
                self.manifest.languages.iter().find(|e| {
                    e.bcp47
                        .split('-')
                        .next()
                        .is_some_and(|p| p.eq_ignore_ascii_case(short))
                })
            })
    }

    /// Fetch (or reuse from cache) a language bundle, verified by
    /// SHA-256, and unpacked under the cache dir.
    /// # Errors
    ///
    /// Unknown language, network, checksum, or unpack failures.
    pub fn fetch(&self, lang: &str) -> anyhow::Result<LexiconBundle> {
        let entry = self.entry(lang).ok_or_else(|| {
            anyhow!(
                "no lexicon bundle for {lang:?} (available: {})",
                self.manifest
                    .languages
                    .iter()
                    .map(|e| e.lang.as_str())
                    .collect::<Vec<_>>()
                    .join(", ")
            )
        })?;
        let dir = self.cache.join(&entry.lang);
        let stamp = dir.join(".sha256");
        let fst = dir.join(format!("{}.fst", entry.lang));
        let pho = dir.join(format!("{}.pho", entry.lang));
        if stamp.exists()
            && fs::read_to_string(&stamp).ok().as_deref() == Some(entry.sha256.as_str())
            && fst.exists()
            && pho.exists()
        {
            return Self::bundle_from(&dir, entry);
        }

        let url = format!("{}/{}", self.base.trim_end_matches('/'), entry.file);
        let bytes =
            get_bytes(&self.base, &entry.file).with_context(|| format!("downloading {url}"))?;
        let got = hash_hex(&bytes);
        if got != entry.sha256 {
            return Err(anyhow!(
                "checksum mismatch for {}: manifest {}, got {got}",
                entry.file,
                entry.sha256
            ));
        }
        fs::create_dir_all(&dir)?;
        unpack(&bytes, &dir).with_context(|| format!("unpacking {}", entry.file))?;
        fs::write(&stamp, &entry.sha256)?;
        Self::bundle_from(&dir, entry)
    }

    fn bundle_from(dir: &Path, entry: &LanguageEntry) -> anyhow::Result<LexiconBundle> {
        let lexicon = floravox_g2p::MmapLexicon::open(dir.join(format!("{}.fst", entry.lang)))
            .map_err(|e| anyhow!("opening lexicon: {e}"))?;
        let phonetisaurus = dir
            .join("phonetisaurus.fst")
            .exists()
            .then(|| floravox_g2p::PhonetisaurusG2p::open(dir.join("phonetisaurus.fst")))
            .transpose()
            .map_err(|e| anyhow!("opening phonetisaurus: {e}"))?;
        Ok(LexiconBundle {
            entry: entry.clone(),
            dir: dir.to_path_buf(),
            lexicon,
            phonetisaurus,
        })
    }

    fn fetch_manifest(base: &str, cache: &Path) -> anyhow::Result<Manifest> {
        let cached = cache.join("lexicons.json");
        let url = format!("{}/lexicons.json", base.trim_end_matches('/'));
        let bytes = match get_bytes(base, "lexicons.json") {
            Ok(b) => {
                let _ = fs::write(&cached, &b);
                b
            }
            Err(e) => fs::read(&cached).map_err(|_| {
                e.context(format!(
                    "fetching {url} (and no cache at {})",
                    cached.display()
                ))
            })?,
        };
        serde_json::from_slice(&bytes).context("parsing lexicons.json")
    }
}

/// A fetched, unpacked bundle: the FST lexicon plus optional OOV WFST.
pub struct LexiconBundle {
    /// Manifest entry (license, provenance).
    pub entry: LanguageEntry,
    /// Where the bundle is unpacked.
    pub dir: PathBuf,
    /// The mmap'd lexicon.
    pub lexicon: floravox_g2p::MmapLexicon,
    /// The bundled Phonetisaurus model, when present.
    pub phonetisaurus: Option<floravox_g2p::PhonetisaurusG2p>,
}

impl LexiconBundle {
    /// Ready-to-use phonemizer: lexicon → Phonetisaurus (if bundled) →
    /// letter-name spelling. Wrap in `CachedPhonemizer` for repeated
    /// words.
    /// # Errors
    ///
    /// Never in practice (empty lexicon is pre-validated).
    pub fn phonemizer(
        &self,
    ) -> anyhow::Result<
        floravox_g2p::LexiconPhonemizer<memmap2::Mmap, Box<dyn floravox_g2p::OovFallback + Send>>,
    > {
        let mut fallback: Box<dyn floravox_g2p::OovFallback + Send> =
            Box::new(floravox_g2p::RuleFallback::default());
        if self.phonetisaurus.is_some() {
            fallback = Box::new(floravox_g2p::ChainedFallback(
                floravox_g2p::PhonetisaurusG2p::open(self.dir.join("phonetisaurus.fst"))
                    .map_err(|e| anyhow!("phonetisaurus: {e}"))?,
                fallback,
            ));
        }
        let lex =
            floravox_g2p::MmapLexicon::open(self.dir.join(format!("{}.fst", self.entry.lang)))
                .map_err(|e| anyhow!("lexicon: {e}"))?;
        Ok(floravox_g2p::LexiconPhonemizer::new(lex, fallback))
    }
}

/// `~/.voicegarden/lexicons` (or `VOICEGARDEN_LEXICON_DIR`).
#[must_use]
pub fn default_cache_dir() -> PathBuf {
    if let Some(dir) = std::env::var_os("VOICEGARDEN_LEXICON_DIR") {
        return PathBuf::from(dir);
    }
    match std::env::var_os("HOME") {
        Some(h) => PathBuf::from(h).join(".voicegarden").join("lexicons"),
        None => PathBuf::from(".voicegarden-lexicons"),
    }
}

/// Fetch `base/name`: plain file read when base is a local directory
/// (offline/mirror use), HTTP otherwise.
fn get_bytes(base: &str, name: &str) -> anyhow::Result<Vec<u8>> {
    let joined = format!("{}/{}", base.trim_end_matches('/'), name);
    if !base.contains("://") {
        return fs::read(Path::new(&joined)).with_context(|| format!("reading {joined}"));
    }
    let agent = ureq::AgentBuilder::new()
        .timeout_connect(Duration::from_secs(30))
        .build();
    let mut reader = agent.get(&joined).call()?.into_reader();
    let mut buf = Vec::new();
    reader.read_to_end(&mut buf)?;
    Ok(buf)
}

fn hash_hex(bytes: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    let mut h = Sha256::new();
    h.update(bytes);
    let out = h.finalize();
    let mut s = String::with_capacity(out.len() * 2);
    for b in out {
        use std::fmt::Write as _;
        let _ = write!(s, "{b:02x}");
    }
    s
}

fn unpack(bytes: &[u8], dir: &Path) -> anyhow::Result<()> {
    let tar = GzDecoder::new(bytes);
    let mut archive = tar::Archive::new(tar);
    archive.unpack(dir)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use floravox_g2p::LexiconWriter;

    /// Build a tiny two-file bundle the way build.py does, serve it from
    /// a plain directory (file-path "base"), and exercise the whole
    /// client path offline.
    #[test]
    #[allow(clippy::items_after_statements)]
    fn offline_bundle_roundtrip() {
        let tmp = tempfile::tempdir().unwrap();
        let serve = tmp.path().join("serve");
        let cache = tmp.path().join("cache");
        fs::create_dir_all(&serve).unwrap();

        // build lexicon files
        let work = tmp.path().join("work");
        fs::create_dir_all(&work).unwrap();
        LexiconWriter::new(work.join("xx"))
            .write(vec![("guten".into(), "ɡ ʊ t ə n".into())])
            .unwrap();

        // tar.gz them
        let tar_path = serve.join("xx.tar.gz");
        {
            let file = fs::File::create(&tar_path).unwrap();
            let enc = flate2::write::GzEncoder::new(file, flate2::Compression::default());
            let mut tar = tar::Builder::new(enc);
            tar.append_path_with_name(work.join("xx.fst"), "xx.fst")
                .unwrap();
            tar.append_path_with_name(work.join("xx.pho"), "xx.pho")
                .unwrap();
            tar.into_inner().unwrap().finish().unwrap();
        }
        let bytes = fs::read(&tar_path).unwrap();
        let manifest = format!(
            "{{\"version\":\"test\",\"format\":\"voicegarden-lexicons/1\",\"languages\":[{{\
            \"lang\":\"xx\",\"name\":\"Test\",\"bcp47\":\"xx\",\"entries\":1,\
            \"license\":\"MIT\",\"source\":\"test\",\"phonetisaurus\":null,\
            \"file\":\"xx.tar.gz\",\"sha256\":\"{}\"}}]}}",
            hash_hex(&bytes)
        );
        fs::write(serve.join("lexicons.json"), manifest).unwrap();

        let archive = LexiconArchive::new(serve.display().to_string(), &cache).unwrap();
        assert_eq!(archive.manifest().languages.len(), 1);
        assert!(archive.entry("xx").is_some());
        assert!(archive.entry("xx-DE").is_some());
        // exact + bcp47-prefix resolution

        let bundle = archive.fetch("xx").unwrap();
        assert_eq!(bundle.entry.license, "MIT");
        assert!(bundle.phonetisaurus.is_none());

        use floravox_g2p::TokenPhonemizer as _;
        let mut g2p = bundle.phonemizer().unwrap();
        assert_eq!(g2p.phonemize_token("guten").len(), 5);
        assert!(!g2p.phonemize_token("zzzz").is_empty()); // spelling fallback

        // second fetch hits the cache (stamp matches)
        let again = archive.fetch("xx").unwrap();
        let mut g2p2 = again.phonemizer().unwrap();
        assert_eq!(g2p2.phonemize_token("guten").len(), 5);
    }

    #[test]
    fn checksum_mismatch_rejected() {
        let tmp = tempfile::tempdir().unwrap();
        let serve = tmp.path().join("serve");
        let cache = tmp.path().join("cache");
        fs::create_dir_all(&serve).unwrap();
        fs::write(serve.join("xx.tar.gz"), b"not really a tarball").unwrap();
        let manifest = r#"{"version":"t","format":"voicegarden-lexicons/1","languages":[
            {"lang":"xx","name":"T","bcp47":"xx","entries":1,"license":"MIT",
             "source":"t","phonetisaurus":null,"file":"xx.tar.gz",
             "sha256":"0000000000000000000000000000000000000000000000000000000000000000"}]}"#;
        fs::write(serve.join("lexicons.json"), manifest).unwrap();
        let archive = LexiconArchive::new(serve.display().to_string(), &cache).unwrap();
        let err = match archive.fetch("xx") {
            Err(e) => e.to_string(),
            Ok(_) => panic!("bad checksum accepted"),
        };
        assert!(err.contains("checksum mismatch"), "{err}");
    }
}
