//! Local pre-release consumer smoke test — no network.
//!
//! Points the real fetcher API at the locally built `dist/` tree and
//! exercises the same path a downstream consumer uses: manifest load,
//! locale resolution for every sherpa piper voice code, bundle fetch
//! (sha-verified), dictionary-tier phonemization through `phonemizer()`,
//! and WFST-tier fallback for an OOV word.
//!
//! Run after `build.py` (base) and `build_expanded_v2.py` (expanded):
//!   cargo run --release --example `consumer_smoke`
//!
//! Exits non-zero on any failure. This replaces the bundle-build and
//! smoke steps CI used to run (see `scripts/validate_release.py` too).

use floravox_g2p::TokenPhonemizer as _;
use voicegarden_lexicons::LexiconArchive;

/// (voice locale as the wrapper passes it, bundle we expect, one word
/// that must be in the dictionary, one OOV word for the WFST tier).
/// Every locale the sherpa piper/coqui/mimic3 families ship, minus the
/// documented blocked set (ku, tn — no lexical data anywhere; see
/// docs/sherpa-coverage.md).
const CASES: &[(&str, &str, &str, &str)] = &[
    ("de_DE", "de", "guten", "floravoxisches"),
    ("en_US", "en", "world", "zipzapper"),
    ("en_GB", "en-GB", "water", "boopbeep"),
    ("fr_FR", "fr", "bonjour", "charabiaise"),
    ("es_ES", "es", "hola", "chirimollo"),
    ("it_IT", "it", "ciao", "straordinariamente"),
    ("pt_BR", "pt", "olá", "construtivismo"),
    ("ru_RU", "ru", "привет", "конструктивизма"),
    ("ca_ES", "ca", "hola", "construccions"),
    ("cs_CZ", "cs", "ahoj", "konstruktivismus"),
    ("fa_IR", "fa", "سلام", "بی‌سیم‌شخصی"),
    ("nl_NL", "nl", "hallo", "constructiewetenschap"),
    ("sv_SE", "sv", "hej", "konstruktionsunderlag"),
    ("sw_CD", "sw", "habari", "ujenziwakala"),
    // 2026-11 wave 1 (v0.5.0)
    ("af_ZA", "af", "goeie", "konstruksieleer"),
    ("cy_GB", "cy", "helo", "adeiladwaith"),
    ("et", "et", "tere", "ehitusteaduslik"),
    ("eu_ES", "eu", "kaixo", "eraikuntzalarritza"),
    ("ga", "ga", "dia", "tógálacht"),
    ("gu_IN", "gu", "નમસ્તે", "બિલ્ડિંગ"),
    ("hr", "hr", "zdravo", "konstruktivizmu"),
    ("sr_RS", "sr", "здраво", "конструктивизма"),
    ("kk_KZ", "kk", "сәлем", "құрылыс"),
    ("lb_LU", "lb", "moien", "bauchimensionéiert"),
    ("lt", "lt", "labas", "konstruktyvizmo"),
    ("ml_IN", "ml", "നമസ്കാരം", "നിർമ്മാണം"),
    ("mt", "mt", "bonġu", "kostruzzjoniżmu"),
    ("no_NO", "no", "hei", "konstruktivisme"),
    ("sq_AL", "sq", "përshëndetje", "ndërtimthani"),
    ("yue", "yue", "你好", "建設"),
    // 2026-11 wave 2 (v0.5.1)
    ("hu_HU", "hu", "helló", "konstruktivizmusok"),
    ("ka_GE", "ka", "გამარჯობა", "კონსტრუქცია"),
    ("zh_CN", "zh", "你好", "建设"),
    ("ko_KO", "ko", "안녕", "건설"),
    ("uk_UA", "uk", "привіт", "конструктивізму"),
    ("vi_VN", "vi", "xin chào", "kiến thiết vậy"),
    ("ne_NP", "ne", "नमस्ते", "निर्माण"),
    ("lv_LV", "lv", "sveiki", "konstruktīvisms"),
    ("fi_FI", "fin", "terve", "kiitos"),
    ("sv_SE", "swe", "hej", "konstruktivismen"),
    ("nb_NO", "nob", "hei", "konstruktivisme"),
    // expanded tier (dictionary + distilled)
    ("is_IS", "isl", "þrjátíu", "þrjátíuátta"),
    ("pl_PL", "pol", "dzień", "konstruktiwizmem"),
];

fn main() -> anyhow::Result<()> {
    let root = std::env::var("CARGO_MANIFEST_DIR").unwrap_or_else(|_| ".".into());
    let base = format!("{root}/dist");
    let expanded = format!("{root}/dist/expanded-v2");
    let cache = std::env::temp_dir().join("vg-consumer-smoke");
    let _ = std::fs::remove_dir_all(&cache);

    let archive = LexiconArchive::new(&base, &cache)?;
    let expanded_archive = LexiconArchive::new_expanded(&expanded, &cache)?;

    let mut failures = 0;
    for (voice, bundle_id, word, oov) in CASES {
        let arch = if matches!(*bundle_id, "isl" | "pol" | "nob" | "fin" | "swe") {
        &expanded_archive
    } else {
        &archive
    };
        let entry = arch.entry(voice).unwrap_or_else(|| {
            panic!("FAIL {voice}: no manifest entry (expected {bundle_id})");
        });
        if entry.lang != *bundle_id {
            println!("FAIL {voice}: resolved to {} (expected {bundle_id})", entry.lang);
            failures += 1;
            continue;
        }
        let b = match arch.fetch(voice) {
            Ok(b) => b,
            Err(e) => {
                println!("FAIL {voice}: fetch: {e:#}");
                failures += 1;
                continue;
            }
        };
        let mut g2p = match b.phonemizer() {
            Ok(p) => p,
            Err(e) => {
                println!("FAIL {voice}: phonemizer: {e:#}");
                failures += 1;
                continue;
            }
        };
        let dict = g2p.phonemize_token(word).join(" ");
        if dict.is_empty() {
            println!("FAIL {voice}: dictionary tier empty for {word:?}");
            failures += 1;
            continue;
        }
        // OOV tier = the consumer ladder: WFST where bundled (Han
        // models decode 68-95% of OOV within the runtime's search
        // budget — floravox-g2p caps its search at 65,536 pops), then
        // char-wise dictionary fallback (every Han char carries an
        // entry).
        let (oov_out, tier) = if let Some(p) = b.phonetisaurus.as_ref() {
            match p.phonemize(oov) {
                Some(v) if !v.is_empty() => (v.join(" "), "wfst"),
                _ => (char_fallback(&mut g2p, oov), "char-fallback"),
            }
        } else {
            (char_fallback(&mut g2p, oov), "char-fallback")
        };
        if oov_out.is_empty() {
            println!("FAIL {voice}: OOV ladder empty for {oov:?}");
            failures += 1;
            continue;
        }
        println!(
            "ok   {voice:8} -> {bundle_id:6} dict {word:?} = {dict:34} oov {oov:?} = {oov_out:28} [{tier}]"
        );
    }

    let n = CASES.len();
    if failures == 0 {
        println!("\nconsumer smoke: {n}/{n} cases passed");
        Ok(())
    } else {
        anyhow::bail!("consumer smoke: {failures}/{n} cases FAILED");
    }
}

fn char_fallback(
    g2p: &mut floravox_g2p::LexiconPhonemizer<memmap2::Mmap, Box<dyn floravox_g2p::OovFallback + Send>>,
    word: &str,
) -> String {
    use floravox_g2p::TokenPhonemizer as _;
    word.chars()
        .map(|c| g2p.phonemize_token(&c.to_string()).join(" "))
        .collect::<Vec<_>>()
        .join(" | ")
}
