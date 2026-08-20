use floravox_g2p::TokenPhonemizer as _;
use voicegarden_lexicons::LexiconArchive;

fn main() -> anyhow::Result<()> {
    let archive = LexiconArchive::new("/tmp/opencode/vgl-de", "/tmp/opencode/vgl-de-cache")?;
    let bundle = archive.fetch("de")?;
    let ev = bundle.entry.phonetisaurus.as_ref().unwrap();
    println!("de: {} entries, WFST exact {:.1}% PER {:.1}%",
        bundle.entry.entries, ev.exact_match * 100.0, ev.per * 100.0);
    assert!(bundle.phonetisaurus.is_some());
    let mut g2p = bundle.phonemizer()?;
    for w in ["guten", "haus"] {
        println!("  in-lexicon {w} -> {}", g2p.phonemize_token(w).join(" "));
    }
    for w in ["schmetterlingxyz", "kraftfahrzeughaftpflicht"] {
        println!("  OOV       {w} -> {}", g2p.phonemize_token(w).join(" "));
    }
    Ok(())
}
