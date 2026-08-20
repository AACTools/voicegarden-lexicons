use floravox_g2p::TokenPhonemizer as _;
use voicegarden_lexicons::LexiconArchive;

fn main() -> anyhow::Result<()> {
    let archive = LexiconArchive::new("/tmp/opencode/vgl-dist", "/tmp/opencode/vgl-cache")?;
    for lang in ["de", "en"] {
        let bundle = archive.fetch(lang)?;
        println!(
            "{lang}: {} entries ({}, {})",
            bundle.entry.entries, bundle.entry.license, bundle.entry.source
        );
        let mut g2p = bundle.phonemizer()?;
        let words = match lang {
            "de" => vec!["guten", "tag", "wunderbar"],
            _ => vec!["hello", "world", "floravox"],
        };
        for w in words {
            println!("  {w} -> {}", g2p.phonemize_token(w).join(" "));
        }
    }
    Ok(())
}
