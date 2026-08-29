use voicegarden_lexicons::LexiconArchive;
use floravox_g2p::TokenPhonemizer as _;

fn main() -> anyhow::Result<()> {
    let base = "/home/willwade/GitHub/AACTools/voicegarden-lexicons/dist";
    let archive = LexiconArchive::new_expanded(base, "/tmp/opencode/e2e-cache")?;
    println!("manifest languages: {}", archive.manifest().languages.len());
    for lang in ["eng-US", "spa-LatAm", "deu", "tur"] {
        let b = archive.fetch(lang)?;
        let mut g2p = b.phonemizer().expect("phonemizer");
        let w = match lang {
            "eng-US" => "emoji",
            "spa-LatAm" => "personas",
            "deu" => "mente",
            _ => "denemekten",
        };
        let out = g2p.phonemize_token(w).join(" ");
        let wfst = b.phonetisaurus.as_ref()
            .map(|p| p.phonemize(w).map(|v| v.join(" ")).unwrap_or_default());
        println!("{lang:10} {w:12} lexicon: {out:30} wfst: {}", wfst.unwrap_or_default());
    }
    Ok(())
}
