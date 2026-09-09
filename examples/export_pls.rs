//! Export a fetched lexicon bundle (or a plain TSV) as W3C PLS 1.0.
//!
//! ```text
//! cargo run --example export_pls -- --lang en --out en.pls
//! cargo run --example export_pls -- --tsv my.tsv --lang en --out custom.pls
//! ```
//!
//! The output is `alphabet="ipa"` throughout — convert other notations
//! before export.

use std::io::Write as _;

fn main() -> anyhow::Result<()> {
    let mut lang = String::new();
    let mut tsv = Option::<String>::None;
    let mut out = String::from("out.pls");
    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--lang" => lang = args.next().expect("--lang needs a value"),
            "--tsv" => tsv = Some(args.next().expect("--tsv needs a path")),
            "--out" => out = args.next().expect("--out needs a path"),
            other => anyhow::bail!("unknown argument {other:?}"),
        }
    }
    if lang.is_empty() {
        anyhow::bail!("--lang is required (BCP-47 or ISO code, e.g. en, de, pt-BR)");
    }

    let rows: Vec<(String, String)> = if let Some(path) = tsv {
        std::fs::read_to_string(&path)?
            .lines()
            .filter_map(|l| {
                let l = l.trim_end();
                if l.is_empty() {
                    return None;
                }
                let (w, p) = l.split_once('\t')?;
                Some((w.to_string(), p.to_string()))
            })
            .collect()
    } else {
        // Fetch the published bundle for the language and read its
        // lexicon.txt (the plain-text twin of the FST).
        let archive = voicegarden_lexicons::LexiconArchive::default_expanded()?;
        let bundle = archive.fetch(&lang)?;
        let path = bundle.dir.join("lexicon.txt");
        std::fs::read_to_string(&path)?
            .lines()
            .filter_map(|l| {
                let l = l.trim_end();
                if l.is_empty() {
                    return None;
                }
                let (w, p) = l.split_once('\t')?;
                Some((w.to_string(), p.to_string()))
            })
            .collect()
    };

    if rows.is_empty() {
        anyhow::bail!("no rows found — is the language tag right?");
    }
    let mut sorted = rows;
    sorted.sort_by(|a, b| a.0.cmp(&b.0));
    let xml = voicegarden_lexicons::pls::rows_to_pls(&sorted, Some(&lang))?;
    let mut f = std::fs::File::create(&out)?;
    f.write_all(xml.as_bytes())?;
    eprintln!("wrote {} lexemes to {out}", sorted.len());
    Ok(())
}
