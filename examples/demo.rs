use floravox_g2p::TokenPhonemizer as _;
use voicegarden_lexicons::LexiconArchive;

fn main() -> anyhow::Result<()> {
    let archive = LexiconArchive::default_archive()?;
    println!("archive v{}: {} languages", archive.manifest().version, archive.manifest().languages.len());
    let bundle = archive.fetch("fr")?;
    println!("fr: {} entries ({}, {})", bundle.entry.entries, bundle.entry.license, bundle.entry.source);
    let mut g2p = bundle.phonemizer()?;
    for w in ["bonjour", "monde", "fromage"] {
        println!("  {w} -> {}", g2p.phonemize_token(w).join(" "));
    }
    Ok(())
}
