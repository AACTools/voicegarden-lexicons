//! W3C Pronunciation Lexicon Specification (PLS) import/export.
//!
//! PLS is the interchange format for word→pronunciation data: the format
//! Amazon Polly references via `<lexicon uri=…>` and `ElevenLabs` accepts
//! natively for workspace dictionaries. Every `<lexeme>` declares its
//! `alphabet`; the platforms that ingest PLS expect `alphabet="ipa"`, so
//! non-IPA notations must be converted before export (see the
//! speechmarkdown / floravox notation tooling).
//!
//! This module converts between PLS XML and the plain `word<TAB>phonemes`
//! rows used throughout this crate (`lexicon.txt`, the TSV sources).
//!
//! ```no_run
//! # fn main() -> anyhow::Result<()> {
//! // Export: rows → PLS
//! let rows = vec![
//!     ("claughton".to_string(), "ˈklɒftən".to_string()),
//!     ("un".to_string(), "ˌjuːˈɛn".to_string()),
//! ];
//! let xml = voicegarden_lexicons::pls::rows_to_pls(&rows, Some("en"))?;
//! assert!(xml.contains("<grapheme>claughton</grapheme>"));
//!
//! // Import: PLS → rows (aliases fold in as their substitution text;
//! // use pls_to_lexemes + phoneme_rows for phonemes only)
//! let back = voicegarden_lexicons::pls::pls_to_rows(&xml)?;
//! assert_eq!(back, rows);
//! # Ok(())
//! # }
//! ```

use std::fmt::Write as _;

/// A PLS lexeme: the written form plus its pronunciation.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct Lexeme {
    /// `<grapheme>` — the written form as it appears in text.
    pub grapheme: String,
    /// `<phoneme>` — the pronunciation in the declared alphabet
    /// (PLS platforms expect IPA).
    pub phoneme: String,
    /// `<alias>` — a whole-word spoken substitution ("UN" → "United
    /// Nations"), when the lexeme substitutes rather than pronounces.
    pub alias: Option<String>,
}

/// Serialize `(word, phonemes)` rows as a PLS 1.0 document.
///
/// `lang` sets the required `xml:lang` on `<lexicon>` (e.g. `"en"`,
/// `"de"`); `None` defaults to `"und"` (undetermined), which PLS permits
/// but some platforms reject — prefer a real tag.
///
/// Rows are emitted in insertion order; callers sorting rows first get
/// deterministic output.
///
/// # Errors
///
/// Never in practice (content is escaped automatically).
pub fn rows_to_pls(rows: &[(String, String)], lang: Option<&str>) -> anyhow::Result<String> {
    let lexemes: Vec<Lexeme> = rows
        .iter()
        .map(|(g, p)| Lexeme {
            grapheme: g.clone(),
            phoneme: p.clone(),
            alias: None,
        })
        .collect();
    lexemes_to_pls(&lexemes, lang)
}

/// Serialize lexemes (phoneme or alias variants) as a PLS 1.0 document.
///
/// # Errors
///
/// Only on XML-escaping failures that cannot occur for `str` inputs
/// (kept for API future-proofing).
pub fn lexemes_to_pls(lexemes: &[Lexeme], lang: Option<&str>) -> anyhow::Result<String> {
    let lang = lang.unwrap_or("und");
    let mut out = String::new();
    writeln!(out, r#"<?xml version="1.0" encoding="UTF-8"?>"#).ok();
    writeln!(
        out,
        r#"<lexicon version="1.0" xmlns="http://www.w3.org/2005/01/pronunciation-lexicon" xml:lang="{}">"#,
        escape(lang)
    )
    .ok();
    for lx in lexemes {
        writeln!(out, "  <lexeme>").ok();
        writeln!(out, "    <grapheme>{}</grapheme>", escape(&lx.grapheme)).ok();
        if let Some(alias) = &lx.alias {
            writeln!(out, "    <alias>{}</alias>", escape(alias)).ok();
        } else {
            writeln!(
                out,
                r#"    <phoneme alphabet="ipa">{}</phoneme>"#,
                escape(&lx.phoneme)
            )
            .ok();
        }
        writeln!(out, "  </lexeme>").ok();
    }
    writeln!(out, "</lexicon>").ok();
    Ok(out)
}

/// Parse a PLS 1.0 document into rows.
///
/// Alias lexemes are returned as `(grapheme, alias)` pairs. Multiple
/// `<phoneme>`/`<alias>` alternates and multiple `<grapheme>` forms each
/// fan out as separate rows (nothing spec-legal is dropped). Non-IPA
/// `alphabet` attributes are accepted and the
/// value passed through unchanged (conversion is the caller's job
/// before export, and after import if they declared something else).
///
/// # Errors
///
/// On malformed XML or a missing `<lexeme>` structure.
pub fn pls_to_rows(pls: &str) -> anyhow::Result<Vec<(String, String)>> {
    let lexemes = pls_to_lexemes(pls)?;
    Ok(lexemes
        .into_iter()
        .map(|lx| {
            let value = lx.alias.unwrap_or(lx.phoneme);
            (lx.grapheme, value)
        })
        .collect())
}

/// Parse a PLS document, keeping the phoneme/alias distinction.
///
/// # Errors
///
/// On malformed XML, or a `<lexeme>` with neither `<phoneme>` nor
/// `<alias>`.
pub fn pls_to_lexemes(pls: &str) -> anyhow::Result<Vec<Lexeme>> {
    let mut lexemes = Vec::new();
    // A lexeme may carry multiple <grapheme> elements (the W3C spec's
    // judgement/judgment example) and multiple <phoneme>/<alias>
    // alternates; every combination fans out as its own Lexeme so no
    // spec-legal pronunciation is silently dropped.
    let mut graphemes: Vec<String> = Vec::new();
    let mut phonemes: Vec<String> = Vec::new();
    let mut aliases: Vec<String> = Vec::new();
    let mut in_grapheme = false;
    let mut in_phoneme = false;
    let mut in_alias = false;
    let mut text = String::new();

    let mut reader = quick_xml::Reader::from_str(pls);
    reader.config_mut().trim_text(true);
    let mut buf = Vec::new();
    loop {
        use quick_xml::events::Event;
        match reader.read_event_into(&mut buf) {
            Ok(Event::Start(e)) => {
                let name = e.local_name();
                text.clear();
                match name.as_ref() {
                    b"lexeme" => {
                        graphemes.clear();
                        phonemes.clear();
                        aliases.clear();
                    }
                    b"grapheme" => in_grapheme = true,
                    b"phoneme" => in_phoneme = true,
                    b"alias" => in_alias = true,
                    _ => {}
                }
            }
            Ok(Event::Text(t)) => {
                if in_grapheme || in_phoneme || in_alias {
                    text.push_str(&t.unescape().map_err(|e| anyhow::anyhow!("PLS text: {e}"))?);
                }
            }
            Ok(Event::CData(c)) => {
                // CDATA is legal element content in PLS; treat it as text
                // so alternates wrapped in it are not silently dropped.
                if in_grapheme || in_phoneme || in_alias {
                    text.push_str(&String::from_utf8_lossy(c.as_ref()));
                }
            }
            Ok(Event::End(e)) => {
                let name = e.local_name();
                match name.as_ref() {
                    b"grapheme" => {
                        graphemes.push(std::mem::take(&mut text));
                        in_grapheme = false;
                    }
                    b"phoneme" => {
                        if !text.is_empty() {
                            phonemes.push(std::mem::take(&mut text));
                        }
                        in_phoneme = false;
                    }
                    b"alias" => {
                        if !text.is_empty() {
                            aliases.push(std::mem::take(&mut text));
                        }
                        in_alias = false;
                    }
                    b"lexeme" => {
                        let label = graphemes.first().map_or("?", String::as_str);
                        if phonemes.is_empty() && aliases.is_empty() {
                            anyhow::bail!(
                                "lexeme for {label:?} has neither a non-empty \
                                 <phoneme> nor <alias>"
                            );
                        }
                        if graphemes.is_empty() {
                            anyhow::bail!("<lexeme> without <grapheme>");
                        }
                        // Emit phoneme lexemes first (preserving alternate
                        // order), then alias lexemes.
                        let gs = std::mem::take(&mut graphemes);
                        for p in &phonemes {
                            for g in &gs {
                                lexemes.push(Lexeme {
                                    grapheme: g.clone(),
                                    phoneme: p.clone(),
                                    alias: None,
                                });
                            }
                        }
                        for a in &aliases {
                            for g in &gs {
                                lexemes.push(Lexeme {
                                    grapheme: g.clone(),
                                    phoneme: String::new(),
                                    alias: Some(a.clone()),
                                });
                            }
                        }
                    }
                    _ => {}
                }
            }
            Ok(Event::Eof) => break,
            Ok(_) => {}
            Err(e) => anyhow::bail!("PLS parse error: {e}"),
        }
        buf.clear();
    }
    Ok(lexemes)
}

/// Lexeme rows with alias substitutions dropped — the subset that maps
/// grapheme→IPA rather than grapheme→word-substitution.
#[must_use]
pub fn phoneme_rows(lexemes: &[Lexeme]) -> Vec<(String, String)> {
    lexemes
        .iter()
        .filter(|lx| lx.alias.is_none())
        .map(|lx| (lx.grapheme.clone(), lx.phoneme.clone()))
        .collect()
}

fn escape(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trip_phonemes() {
        let rows = vec![
            ("claughton".to_string(), "ˈklɒftən".to_string()),
            ("quixotic".to_string(), "kwɪkˈsɒtɪk".to_string()),
        ];
        let xml = rows_to_pls(&rows, Some("en")).unwrap();
        assert!(xml.contains(r#"xml:lang="en""#));
        assert!(xml.contains(r#"<phoneme alphabet="ipa">ˈklɒftən</phoneme>"#));
        let back = pls_to_rows(&xml).unwrap();
        assert_eq!(back, rows);
    }

    #[test]
    fn alias_lexemes_round_trip() {
        let lexemes = vec![
            Lexeme {
                grapheme: "UN".into(),
                phoneme: String::new(),
                alias: Some("United Nations".into()),
            },
            Lexeme {
                grapheme: "claughton".into(),
                phoneme: "ˈklɒftən".into(),
                alias: None,
            },
        ];
        let xml = lexemes_to_pls(&lexemes, Some("en")).unwrap();
        assert!(xml.contains("<alias>United Nations</alias>"));
        let back = pls_to_lexemes(&xml).unwrap();
        assert_eq!(back, lexemes);
        // pls_to_rows folds the alias in as the value.
        let rows = pls_to_rows(&xml).unwrap();
        assert_eq!(rows[0], ("UN".to_string(), "United Nations".to_string()));
    }

    #[test]
    fn xml_specials_escape_and_round_trip() {
        let rows = vec![("a<b&c".to_string(), "x<y&z".to_string())];
        let xml = rows_to_pls(&rows, None).unwrap();
        assert!(xml.contains("a&lt;b&amp;c"));
        let back = pls_to_rows(&xml).unwrap();
        assert_eq!(back, rows);
    }

    #[test]
    fn und_lang_when_none() {
        let xml = rows_to_pls(&[], None).unwrap();
        assert!(xml.contains(r#"xml:lang="und""#));
    }

    #[test]
    fn rejects_lexeme_without_pronunciation() {
        let xml = r#"<lexicon version="1.0" xmlns="http://www.w3.org/2005/01/pronunciation-lexicon"><lexeme><grapheme>x</grapheme></lexeme></lexicon>"#;
        assert!(pls_to_rows(xml).is_err());
    }

    #[test]
    fn parses_w3c_spec_example_shape() {
        // Shape from the W3C PLS 1.0 spec (structure, invented values).
        let xml = r#"<?xml version="1.0" encoding="UTF-8"?>
<lexicon version="1.0" xmlns="http://www.w3.org/2005/01/pronunciation-lexicon"
      xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
      xsi:schemaLocation="http://www.w3.org/2005/01/pronunciation-lexicon
        http://www.w3.org/TR/2007/CR-pronunciation-lexicon-20071212/pls.xsd"
      alphabet="ipa" xml:lang="en-US">
  <lexeme>
    <grapheme>judgment</grapheme>
    <grapheme>judgement</grapheme>
    <phoneme>ˈdʒʌdʒ.mənt</phoneme>
  </lexeme>
</lexicon>"#;
        let rows = pls_to_rows(xml).unwrap();
        // Multiple graphemes for one pronunciation: each becomes a row.
        assert_eq!(
            rows,
            vec![
                ("judgment".to_string(), "ˈdʒʌdʒ.mənt".to_string()),
                ("judgement".to_string(), "ˈdʒʌdʒ.mənt".to_string()),
            ]
        );
    }

    #[test]
    fn multiple_phoneme_alternates_fan_out() {
        let xml = r#"<lexicon version="1.0" xmlns="http://www.w3.org/2005/01/pronunciation-lexicon" xml:lang="en">
  <lexeme><grapheme>read</grapheme><phoneme>riːd</phoneme><phoneme>red</phoneme></lexeme>
</lexicon>"#;
        let rows = pls_to_rows(xml).unwrap();
        assert_eq!(
            rows,
            vec![
                ("read".to_string(), "riːd".to_string()),
                ("read".to_string(), "red".to_string()),
            ]
        );
    }

    #[test]
    fn phoneme_and_alias_lexeme_keeps_both() {
        let xml = r#"<lexicon version="1.0" xmlns="http://www.w3.org/2005/01/pronunciation-lexicon" xml:lang="en">
  <lexeme><grapheme>read</grapheme><phoneme>riːd</phoneme><alias>peruse</alias></lexeme>
</lexicon>"#;
        let lexemes = pls_to_lexemes(xml).unwrap();
        assert_eq!(lexemes.len(), 2);
        assert_eq!(lexemes[0].phoneme, "riːd");
        assert!(lexemes[0].alias.is_none());
        assert_eq!(lexemes[1].alias.as_deref(), Some("peruse"));
        // phoneme_rows keeps only the pronunciation lexeme.
        let rows = phoneme_rows(&lexemes);
        assert_eq!(rows, vec![("read".to_string(), "riːd".to_string())]);
    }

    #[test]
    fn cdata_content_is_collected_not_dropped() {
        let xml = r#"<lexicon version="1.0" xmlns="http://www.w3.org/2005/01/pronunciation-lexicon" xml:lang="en">
  <lexeme><grapheme>UN</grapheme><alias><![CDATA[United Nations]]></alias></lexeme>
</lexicon>"#;
        let rows = pls_to_rows(xml).unwrap();
        assert_eq!(rows, vec![("UN".to_string(), "United Nations".to_string())]);
    }

    #[test]
    fn mixed_lexeme_keeps_cdata_alias_alongside_phoneme() {
        let xml = r#"<lexicon version="1.0" xmlns="http://www.w3.org/2005/01/pronunciation-lexicon" xml:lang="en">
  <lexeme><grapheme>read</grapheme><phoneme>riːd</phoneme><alias><![CDATA[peruse]]></alias></lexeme>
</lexicon>"#;
        let lexemes = pls_to_lexemes(xml).unwrap();
        assert_eq!(lexemes.len(), 2);
        assert_eq!(lexemes[1].alias.as_deref(), Some("peruse"));
    }

    #[test]
    fn empty_phoneme_or_alias_is_rejected() {
        let xml = r#"<lexicon version="1.0" xmlns="http://www.w3.org/2005/01/pronunciation-lexicon" xml:lang="en">
  <lexeme><grapheme>x</grapheme><alias></alias></lexeme>
</lexicon>"#;
        assert!(pls_to_rows(xml).is_err());
    }

    #[test]
    fn multiple_graphemes_round_trip_as_separate_rows() {
        let rows = vec![
            ("judgment".to_string(), "ˈdʒʌdʒ.mənt".to_string()),
            ("judgement".to_string(), "ˈdʒʌdʒ.mənt".to_string()),
        ];
        let xml = rows_to_pls(&rows, Some("en-US")).unwrap();
        let back = pls_to_rows(&xml).unwrap();
        assert_eq!(back, rows);
    }
}
