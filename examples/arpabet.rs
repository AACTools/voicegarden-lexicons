//! ARPABET → IPA converter for the build pipeline (stdin/stdout).
//!
//! `build.py` uses this for the `en-cmudict` bundle's `lexicon.txt`:
//! sherpa-onnx's lexicon format needs tab-separated word→phones with
//! spaced IPA, but `CMUdict` rows are `word PH1 PH2 ...`. Conversion goes
//! through the crate's own `notation` module (the same table the
//! doctests pin), so there is one source of truth.
//!
//! Input lines:  `word ARPABET SYMBOLS ...`
//! Output lines: `word<TAB>ipa phones spaced` (stress mark as its own
//! token, matching the gruut en corpus convention, e.g. `w ˈ ɚ l d`)
//!
//! Usage: cargo run --release --quiet --example arpabet < in.tsv > out.tsv

use std::io::{BufRead, Write};

fn main() {
    let stdin = std::io::stdin();
    let stdout = std::io::stdout();
    let mut out = std::io::BufWriter::new(stdout.lock());
    for line in stdin.lock().lines().map_while(Result::ok) {
        let mut it = line.split_whitespace();
        let Some(word) = it.next() else { continue };
        let mut phones: Vec<String> = Vec::new();
        for sym in it {
            // split trailing stress digit: AE1 -> ˈ + AE
            let (stress, base) = match sym.as_bytes() {
                [.., d] if (*d as char).is_ascii_digit() => {
                    let d = *d as char;
                    let base = &sym[..sym.len() - 1];
                    let mark = match d {
                        '1' => "ˈ",
                        '2' => "ˌ",
                        _ => "",
                    };
                    (mark, base)
                }
                _ => ("", sym),
            };
            if !stress.is_empty() {
                phones.push(stress.to_string());
            }
            match voicegarden_lexicons::notation::convert(base, voicegarden_lexicons::notation::Notation::Arpabet) {
                Ok(ipa) if !ipa.is_empty() => phones.push(ipa),
                _ => {}
            }
        }
        if !phones.is_empty() {
            let _ = writeln!(out, "{}\t{}", word, phones.join(" "));
        }
    }
}
