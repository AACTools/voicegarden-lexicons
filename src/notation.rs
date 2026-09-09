//! Phonetic notation conversion: SAMPA (per-language), X-SAMPA, ARPABET,
//! CMU Arpabet, Kirshenbaum ↔ IPA.
//!
//! Everything normalizes **to IPA** (`floravox`'s lingua franca and the
//! alphabet PLS platforms expect) and, where the mapping is reversible,
//! **from IPA** back. `X-SAMPA`/`Praat`/`SIL`/`Branner` come from the
//! `ipa-translate` crate (already used by speechmarkdown-rust); the
//! per-language SAMPA tables and ARPABET are maintained here.
//!
//! SAMPA vs X-SAMPA: X-SAMPA is the complete language-independent
//! Unicode mapping; plain SAMPA is a family of language-specific subsets
//! with conflicting symbol assignments (e.g. `E` is open-mid front in
//! German SAMPA but epsilon in others, `J` is a nasal in Spanish SAMPA).
//! Converting plain SAMPA therefore **requires the language**; without
//! one, use `Notation::XSampa`.
//!
//! ```
//! use voicegarden_lexicons::notation::{convert, Notation};
//!
//! // X-SAMPA (language-independent)
//! assert_eq!(convert("pr@tIks", Notation::XSampa).unwrap(), "prətɪks");
//!
//! // German SAMPA: 9 = oe, E = epsilon
//! assert_eq!(convert("E:", Notation::Sampa("de")).unwrap(), "ɛː");
//!
//! // ARPABET (CMU): spaces + optional stress digits
//! assert_eq!(convert("K AE1 T", Notation::Arpabet).unwrap(), "kˈæt");
//! ```

use std::collections::HashMap;
use std::sync::OnceLock;

/// Source notation for [`convert`].
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Notation<'a> {
    /// X-SAMPA — the complete language-independent mapping.
    XSampa,
    /// Plain SAMPA for a specific language (BCP-47 or ISO 639-1 code).
    /// Supported: de, en, es, fr, hu, it, nl, pt, ru, sv (falls back to
    /// X-SAMPA for unknown languages).
    Sampa(&'a str),
    /// ARPABET as used by `CMUdict`: space-separated symbols with
    /// optional trailing stress digits (0/1/2).
    Arpabet,
    /// Kirshenbaum (the conlang/Usenet ASCII IPA).
    Kirshenbaum,
    /// Praat (via `ipa-translate`).
    Praat,
    /// SIL (via `ipa-translate`).
    Sil,
    /// Branner (via `ipa-translate`).
    Branner,
}

/// Convert `input` in the given notation to IPA.
///
/// Spaces between symbols are preserved; word stress marks are mapped
/// to IPA primary/secondary stress where the source notation marks it.
///
/// # Errors
///
/// Only on internal table failures that cannot occur in practice.
pub fn convert(input: &str, notation: Notation) -> Result<String, String> {
    let ipa = match notation {
        Notation::XSampa => ipa_translate::xsampa_to_ipa(input),
        Notation::Praat => ipa_translate::praat_to_ipa(input),
        Notation::Sil => ipa_translate::sil_to_ipa(input),
        Notation::Branner => ipa_translate::branner_to_ipa(input),
        Notation::Kirshenbaum => kirshenbaum_to_ipa(input),
        Notation::Arpabet => arpabet_to_ipa(input),
        Notation::Sampa(lang) => {
            let table = sampa_table(lang);
            if table.is_empty() {
                // Unknown language: X-SAMPA is the closest superset.
                ipa_translate::xsampa_to_ipa(input)
            } else {
                symbols_to_ipa(input, table)
            }
        }
    };
    Ok(ipa)
}

/// Convert IPA back to the notation, where reversible.
///
/// X-SAMPA and ARPABET round-trip; per-language SAMPA maps via its
/// table reversed. Praat/SIL/Branner reverse via `ipa-translate`.
///
/// # Errors
///
/// When the direction or table is unavailable.
pub fn convert_from_ipa(ipa: &str, notation: Notation) -> Result<String, String> {
    let out = match notation {
        Notation::XSampa => ipa_translate::ipa_to_xsampa(ipa),
        Notation::Praat => ipa_translate::ipa_to_praat(ipa),
        Notation::Sil => ipa_translate::ipa_to_sil(ipa),
        Notation::Branner => ipa_translate::ipa_to_branner(ipa),
        Notation::Kirshenbaum => ipa_to_kirshenbaum(ipa),
        Notation::Arpabet => ipa_to_arpabet(ipa),
        Notation::Sampa(lang) => {
            let table = sampa_table(lang);
            if table.is_empty() {
                ipa_translate::ipa_to_xsampa(ipa)
            } else {
                ipa_to_symbols(ipa, table)
            }
        }
    };
    Ok(out)
}

// --- SAMPA per-language tables ------------------------------------------
//
// Only symbols that DIFFER from X-SAMPA need entries: the lookup falls
// through to X-SAMPA for anything not in the language table. Sources:
// the SAMPA affiliation pages per language (Wells).

#[allow(clippy::too_many_lines)]
fn sampa_table(lang: &str) -> &'static HashMap<&'static str, &'static str> {
    static DE: OnceLock<HashMap<&'static str, &'static str>> = OnceLock::new();
    static EN: OnceLock<HashMap<&'static str, &'static str>> = OnceLock::new();
    static ES: OnceLock<HashMap<&'static str, &'static str>> = OnceLock::new();
    static FR: OnceLock<HashMap<&'static str, &'static str>> = OnceLock::new();
    static HU: OnceLock<HashMap<&'static str, &'static str>> = OnceLock::new();
    static IT: OnceLock<HashMap<&'static str, &'static str>> = OnceLock::new();
    static NL: OnceLock<HashMap<&'static str, &'static str>> = OnceLock::new();
    static PT: OnceLock<HashMap<&'static str, &'static str>> = OnceLock::new();
    static RU: OnceLock<HashMap<&'static str, &'static str>> = OnceLock::new();
    static SV: OnceLock<HashMap<&'static str, &'static str>> = OnceLock::new();

    let (code,) = (lang.split(['-', '_']).next().unwrap_or(""),);
    match code {
        "de" => Some(DE.get_or_init(|| {
            table(&[
                ("9", "œ"),
                ("9:", "øː"),
                ("2", "ø"),
                ("2:", "øː"),
                ("E", "ɛ"),
                ("E:", "ɛː"),
                ("a", "a"),
                ("a:", "aː"),
                ("N", "ŋ"),
                ("x", "x"),
                ("C", "ç"),
                ("?\"", "ʔ"),
                ("R", "ʁ"),
                ("6", "ɐ"),
            ])
        })),
        "en" => Some(EN.get_or_init(|| {
            table(&[
                ("e", "e"),
                ("@\"", "ə"),
                ("@", "ə"),
                ("I", "ɪ"),
                ("V", "ʌ"),
                ("u", "ʊ"),
                ("U", "ʊ"),
                ("E", "e"),
                ("O", "ɔː"),
                ("3:", "ɜː"),
                ("eI", "eɪ"),
                ("aI", "aɪ"),
                ("OI", "ɔɪ"),
                ("aU", "aʊ"),
                ("@U", "əʊ"),
                ("I@", "ɪə"),
                ("e@", "eə"),
                ("U@", "ʊə"),
                ("N", "ŋ"),
                ("dZ", "dʒ"),
                ("tS", "tʃ"),
                ("D", "ð"),
                ("T", "θ"),
                ("Z", "ʒ"),
                ("Q", "ɒ"),
            ])
        })),
        "es" => Some(ES.get_or_init(|| {
            table(&[
                ("E", "e"),
                ("O", "o"),
                ("x", "x"),
                ("B", "β"),
                ("D", "ð"),
                ("G", "ɣ"),
                ("J", "ɲ"),
                ("j\\", "ʝ"),
                ("rr", "r"),
                ("r", "ɾ"),
                ("ts", "t͡s"),
                ("tS", "t͡ʃ"),
            ])
        })),
        "fr" => Some(FR.get_or_init(|| {
            table(&[
                ("9", "œ"),
                ("2", "ø"),
                ("@", "ə"),
                ("A", "a"),
                ("E", "ɛ"),
                ("O", "ɔ"),
                ("e", "e"),
                ("o", "o"),
                ("x", "χ"),
                ("R", "ʁ"),
                ("H", "ɥ"),
                ("j", "j"),
                ("8", "u"),
                ("u", "y"),
                ("9~", "œ̃"),
                ("a~", "ɑ̃"),
                ("E~", "ɛ̃"),
                ("O~", "ɔ̃"),
                ("N", "ŋ"),
            ])
        })),
        "hu" => Some(HU.get_or_init(|| {
            table(&[
                ("E", "ɛ"),
                ("o", "o"),
                ("O", "ɔ"),
                ("y", "y"),
                ("Y", "y"),
                (":", "ː"),
                ("r\\", "r"),
                ("r", "r"),
                ("s\\", "ʃ"),
                ("s", "ʃ"),
                ("S", "ʃ"),
                ("z\\", "ʒ"),
                ("Z", "ʒ"),
                ("z", "z"),
                ("c", "c"),
                ("J", "j"),
                ("n_j", "ɲ"),
                ("J\\", "ɲ"),
                ("dZ", "dʒ"),
                ("tS", "tʃ"),
            ])
        })),
        "it" => Some(IT.get_or_init(|| {
            table(&[
                ("E", "ɛ"),
                ("O", "ɔ"),
                ("e", "e"),
                ("o", "o"),
                ("s", "s"),
                ("s\\", "z"),
                ("z", "dz"),
                ("ts", "t͡s"),
                ("tS", "t͡ʃ"),
                ("dZ", "d͡ʒ"),
                ("tS", "t͡ʃ"),
                ("N", "ŋ"),
                ("J", "ɲ"),
                ("L", "ʎ"),
            ])
        })),
        "nl" => Some(NL.get_or_init(|| {
            table(&[
                ("E", "ɛ"),
                ("9", "œ"),
                ("Y", "ʏ"),
                ("I", "ɪ"),
                ("u", "u"),
                ("y", "y"),
                ("A", "aː"),
                ("O", "ɔ"),
                ("x", "x"),
                ("G", "ɣ"),
                ("N", "ŋ"),
                ("r\\", "r"),
                ("r", "r"),
                ("@U", "ʌu"),
                ("eI", "ɛi"),
                ("Oi", "ɔi"),
                ("y:", "yː"),
                ("u:", "uː"),
            ])
        })),
        "pt" => Some(PT.get_or_init(|| {
            table(&[
                ("E", "ɛ"),
                ("O", "ɔ"),
                ("e", "e"),
                ("o", "o"),
                ("i", "i"),
                ("u", "u"),
                ("a", "a"),
                ("6", "ɐ"),
                ("R", "ʁ"),
                ("rr", "ʁ"),
                ("r", "ɾ"),
                ("x", "ʃ"),
                ("S", "ʃ"),
                ("Z", "ʒ"),
                ("s", "s"),
                ("z", "z"),
                ("J", "ɲ"),
                ("N", "ŋ"),
                ("L", "ʎ"),
                ("dZ", "dʒ"),
                ("tS", "tʃ"),
                ("j", "j"),
                ("w", "w"),
                ("~", "̃"),
            ])
        })),
        "ru" => Some(RU.get_or_init(|| {
            table(&[
                ("A", "a"),
                ("I", "ɪ"),
                ("U", "u"),
                ("E", "e"),
                ("O", "o"),
                ("1", "ɨ"),
                ("s\\", "ʂ"),
                ("z\\", "ʐ"),
                ("S", "ʂ"),
                ("Z", "ʐ"),
                ("ts\\", "t͡sʲ"),
                ("tS", "t͡ɕ"),
                ("dZ", "d͡ʑ"),
                ("z", "zʲ"),
                ("s", "sʲ"),
                ("j", "j"),
                ("x", "x"),
                ("r\\", "r"),
                ("r", "r"),
                ("p_j", "pʲ"),
            ])
        })),
        "sv" => Some(SV.get_or_init(|| {
            table(&[
                ("E", "ɛ"),
                ("E:", "ɛː"),
                ("2", "ø"),
                ("2:", "øː"),
                ("9", "ɵ"),
                ("u", "ɵ"),
                ("8", "ʉ"),
                ("}", "ɵ"),
                ("y", "y"),
                ("y:", "yː"),
                ("u0", "ʉ"),
                ("0", "ʉ"),
                ("A", "ɑ"),
                ("a", "ɑ"),
                ("O", "ɔ"),
                ("o", "ɔ"),
                ("e", "e"),
                ("e:", "eː"),
                ("i:", "iː"),
                ("u:", "ʉː"),
                (":", "ː"),
                ("x", "ɧ"),
                ("S", "ɧ"),
                ("s\\", "ɕ"),
                ("z\\", "ɕ"),
                ("rs", "ɾɕ"),
                ("rt", "ʈ"),
                ("rn", "ɳ"),
                ("rl", "ɭ"),
                ("N", "ŋ"),
                ("J", "ɲ"),
            ])
        })),
        _ => None,
    }
    .unwrap_or_else(|| {
        static EMPTY: OnceLock<HashMap<&'static str, &'static str>> = OnceLock::new();
        EMPTY.get_or_init(HashMap::new)
    })
}

/// Heuristic: a 2-char sequence is an X-SAMPA symbol when the second
/// char is a recognized modifier (backslash, digits as tone, equals,
/// tilde, caret) or when transliterating both chars together differs from
/// transliterating them separately (indicating a multi-char mapping).
fn is_xsampa_symbol(s: &str) -> bool {
    let mut cs = s.chars();
    let (Some(first), Some(second)) = (cs.next(), cs.next()) else {
        return false;
    };
    if second == '\\'
        || second == '='
        || second == '"'
        || second == '`'
        || second == '~'
        || second == '^'
    {
        return true;
    }
    if second.is_ascii_digit() && first.is_ascii_alphabetic() {
        return false; // tone digit applies after, not a combined symbol
    }
    let together = ipa_translate::xsampa_to_ipa(s);
    let sep = format!(
        "{}{}",
        ipa_translate::xsampa_to_ipa(&first.to_string()),
        ipa_translate::xsampa_to_ipa(&second.to_string())
    );
    together != sep
}

fn table(pairs: &[(&'static str, &'static str)]) -> HashMap<&'static str, &'static str> {
    pairs.iter().copied().collect()
}

/// Longest-match symbol replacement using `table`, falling through to
/// X-SAMPA per symbol for anything the language table doesn't cover,
/// and preserving spaces.
fn symbols_to_ipa(input: &str, lang_table: &HashMap<&'static str, &'static str>) -> String {
    let mut out = String::with_capacity(input.len() * 2);
    let mut sorted: Vec<&'static str> = lang_table.keys().copied().collect();
    sorted.sort_by_key(|k| std::cmp::Reverse(k.len()));

    let mut chars = input.char_indices().peekable();
    while let Some((i, c)) = chars.next() {
        if c == ' ' {
            out.push(' ');
            continue;
        }
        // Language table longest match
        let rest = &input[i..];
        let mut matched = false;
        for key in &sorted {
            if rest.starts_with(key) {
                out.push_str(lang_table[key]);
                for _ in 1..key.chars().count() {
                    chars.next();
                }
                matched = true;
                break;
            }
        }
        if !matched {
            // Fall through to X-SAMPA: consume the next single symbol.
            // X-SAMPA symbols are 1-2 chars (letter + optional modifier
            // like \, =, _…), and ipa_translate processes the whole
            // string at once — so find the longest X-SAMPA prefix by
            // transliterating character by character.
            let consumed;
            let rest_chars: Vec<char> = rest.chars().collect();
            // Try 2-char, then 1-char
            let (_chunk, ipa): (String, String) = if rest_chars.len() >= 2 {
                let two: String = rest_chars[..2].iter().collect();
                let t = ipa_translate::xsampa_to_ipa(&two);
                if !t.is_empty() && is_xsampa_symbol(&two) {
                    consumed = 2;
                    (two, t)
                } else {
                    let one: String = rest_chars[0].to_string();
                    consumed = 1;
                    let t = ipa_translate::xsampa_to_ipa(&one);
                    (one, t)
                }
            } else {
                let one: String = rest_chars[0].to_string();
                consumed = 1;
                let t = ipa_translate::xsampa_to_ipa(&one);
                (one, t)
            };
            out.push_str(&ipa);
            for _ in 1..consumed {
                chars.next();
            }
        }
    }
    out
}

/// Reverse: IPA → language-specific symbols where the table covers it,
/// X-SAMPA otherwise.
fn ipa_to_symbols(ipa: &str, lang_table: &HashMap<&'static str, &'static str>) -> String {
    let reverse: HashMap<&str, &str> = lang_table.iter().map(|(k, v)| (*v, *k)).collect();
    let mut sorted: Vec<&str> = reverse.keys().copied().collect();
    sorted.sort_by_key(|k: &&str| std::cmp::Reverse(k.chars().count()));

    let mut out = String::new();
    let mut chars = ipa.char_indices().peekable();
    while let Some((i, c)) = chars.next() {
        if c == ' ' {
            out.push(' ');
            continue;
        }
        let rest = &ipa[i..];
        let mut matched = false;
        for key in &sorted {
            if rest.starts_with(key) {
                out.push_str(reverse[key]);
                for _ in 1..key.chars().count() {
                    chars.next();
                }
                matched = true;
                break;
            }
        }
        if !matched {
            let sym: String = rest.chars().take_while(|ch| *ch != ' ').collect();
            out.push_str(&ipa_translate::ipa_to_xsampa(&sym));
            for _ in 1..sym.chars().count().saturating_sub(1) {
                chars.next();
            }
        }
    }
    out
}

// --- ARPABET (CMUdict) ----------------------------------------------------

/// CMU Arpabet symbol → IPA. Stress is handled separately (digits).
const ARPABET: &[(&str, &str)] = &[
    ("AA", "ɑ"),
    ("AE", "æ"),
    ("AH", "ʌ"),
    ("AO", "ɔ"),
    ("AW", "aʊ"),
    ("AY", "aɪ"),
    ("B", "b"),
    ("CH", "tʃ"),
    ("D", "d"),
    ("DH", "ð"),
    ("EH", "ɛ"),
    ("ER", "ɚ"),
    ("EY", "eɪ"),
    ("F", "f"),
    ("G", "ɡ"),
    ("HH", "h"),
    ("IH", "ɪ"),
    ("IY", "i"),
    ("JH", "dʒ"),
    ("K", "k"),
    ("L", "l"),
    ("M", "m"),
    ("N", "n"),
    ("NG", "ŋ"),
    ("OW", "oʊ"),
    ("OY", "ɔɪ"),
    ("P", "p"),
    ("R", "ɹ"),
    ("S", "s"),
    ("SH", "ʃ"),
    ("T", "t"),
    ("TH", "θ"),
    ("UH", "ʊ"),
    ("UW", "u"),
    ("V", "v"),
    ("W", "w"),
    ("Y", "j"),
    ("Z", "z"),
    ("ZH", "ʒ"),
];

fn arpabet_map() -> &'static HashMap<&'static str, &'static str> {
    static MAP: OnceLock<HashMap<&'static str, &'static str>> = OnceLock::new();
    MAP.get_or_init(|| ARPABET.iter().copied().collect())
}

fn arpabet_to_ipa(input: &str) -> String {
    let map = arpabet_map();
    let mut out = String::new();
    for tok in input.split_whitespace() {
        let (sym, stress) = match tok.as_bytes().last() {
            Some(b'0' | b'1' | b'2') if tok.len() > 1 => {
                (&tok[..tok.len() - 1], &tok[tok.len() - 1..])
            }
            _ => (tok, ""),
        };
        let sym_upper = sym.to_ascii_uppercase();
        let ipa = map.get(sym_upper.as_str()).copied().unwrap_or("");
        if ipa.is_empty() {
            continue; // unknown token: skip rather than corrupt
        }
        // Stress marks the syllable nucleus: in IPA it precedes the
        // vowel (which is this token — ARPABET vowels carry the digit).
        match stress {
            "1" => out.push('ˈ'),
            "2" => out.push('ˌ'),
            _ => {}
        }
        out.push_str(ipa);
    }
    out
}

#[allow(clippy::too_many_lines)]
fn ipa_to_arpabet(ipa: &str) -> String {
    let map: HashMap<&str, &str> = arpabet_map().iter().map(|(k, v)| (*v, *k)).collect();
    let mut sorted: Vec<&str> = map.keys().copied().collect();
    sorted.sort_by_key(|k: &&str| std::cmp::Reverse(k.chars().count()));

    // Clean implementation: walk IPA with longest-match, emit tokens
    let mut out = String::new();
    let mut stress = "";
    let mut chars = ipa.char_indices().peekable();
    while let Some((i, c)) = chars.next() {
        match c {
            'ˈ' => stress = "1",
            'ˌ' => stress = "2",
            ' ' | '-' => stress = "",
            _ => {
                let rest = &ipa[i..];
                for key in &sorted {
                    if rest.starts_with(key) {
                        out.push_str(map[key]);
                        out.push_str(stress);
                        out.push(' ');
                        stress = "";
                        for _ in 1..key.chars().count() {
                            chars.next();
                        }
                        break;
                    }
                }
                // else: no match — skip unknown char
            }
        }
    }
    out.trim_end().to_string()
}

// --- Kirshenbaum -----------------------------------------------------------

const KIRSHENBAUM: &[(&str, &str)] = &[
    ("A", "ɑ"),
    ("B", "b"),
    ("C", "ç"),
    ("D", "ð"),
    ("E", "e"),
    ("F", "f"),
    ("G", "ɡ"),
    ("H", "h"),
    ("I", "i"),
    ("J", "ɲ"),
    ("K", "k"),
    ("L", "l"),
    ("M", "m"),
    ("N", "n"),
    ("O", "o"),
    ("P", "p"),
    ("Q", "ɒ"),
    ("R", "ɹ"),
    ("S", "ʃ"),
    ("T", "θ"),
    ("U", "u"),
    ("V", "v"),
    ("W", "w"),
    ("X", "x"),
    ("Y", "ø"),
    ("Z", "ʒ"),
    ("a", "a"),
    ("b", "ʙ"),
    ("c", "c"),
    ("d", "d"),
    ("e", "ɤ"),
    ("f", "ɸ"),
    ("g", "ɢ"),
    ("h", "ɦ"),
    ("i", "i"),
    ("j", "j"),
    ("k", "k"),
    ("l", "ʟ"),
    ("m", "ɯ"),
    ("n", "n̥"),
    ("o", "ø"),
    ("p", "p"),
    ("q", "ʔ"),
    ("r", "ɹ"),
    ("s", "s"),
    ("t", "t"),
    ("u", "ɤ"),
    ("v", "ⱱ"),
    ("w", "ɰ"),
    ("x", "χ"),
    ("y", "y"),
    ("z", "z"),
];

fn kirshenbaum_map() -> &'static HashMap<&'static str, &'static str> {
    static MAP: OnceLock<HashMap<&'static str, &'static str>> = OnceLock::new();
    MAP.get_or_init(|| KIRSHENBAUM.iter().copied().collect())
}

fn kirshenbaum_to_ipa(input: &str) -> String {
    let map = kirshenbaum_map();
    let mut out = String::new();
    for c in input.chars() {
        if c == ' ' {
            out.push(' ');
            continue;
        }
        // Diacritics: double-quote after a symbol = length; single-quote
        // = primary stress
        if c == '"' {
            out.push('ː');
            continue;
        }
        if c == '\'' {
            out.push('ˈ');
            continue;
        }
        if c == ',' {
            out.push('ˌ');
            continue;
        }
        let one = c.to_string();
        if let Some(ipa) = map.get(one.as_str()) {
            out.push_str(ipa);
        } else {
            out.push(c);
        }
    }
    out
}

fn ipa_to_kirshenbaum(ipa: &str) -> String {
    let map: HashMap<&str, &str> = kirshenbaum_map().iter().map(|(k, v)| (*v, *k)).collect();
    let mut sorted: Vec<&str> = map.keys().copied().collect();
    sorted.sort_by_key(|k: &&str| std::cmp::Reverse(k.chars().count()));
    let mut out = String::new();
    let mut chars = ipa.char_indices().peekable();
    while let Some((i, c)) = chars.next() {
        match c {
            'ː' => {
                out.push('"');
                continue;
            }
            'ˈ' => {
                out.push('\'');
                continue;
            }
            'ˌ' => {
                out.push(',');
                continue;
            }
            ' ' => {
                out.push(' ');
                continue;
            }
            _ => {}
        }
        let rest = &ipa[i..];
        let mut matched = false;
        for key in &sorted {
            if rest.starts_with(key) {
                out.push_str(map[key]);
                for _ in 1..key.chars().count() {
                    chars.next();
                }
                matched = true;
                break;
            }
        }
        if !matched {
            out.push(c);
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn xsampa_round_trip() {
        let ipa = convert("pr@tIks", Notation::XSampa).unwrap();
        assert_eq!(ipa, "prətɪks");
        let back = convert_from_ipa(&ipa, Notation::XSampa).unwrap();
        assert_eq!(back, "pr@tIks");
    }

    #[test]
    fn german_sampa() {
        assert_eq!(convert("b9:t", Notation::Sampa("de")).unwrap(), "bøːt");
        assert_eq!(convert("b\"9t", Notation::Sampa("de")).unwrap(), "bˈœt");
        assert_eq!(convert("b\"2:n", Notation::Sampa("de")).unwrap(), "bˈøːn");
        assert_eq!(convert("E:", Notation::Sampa("de")).unwrap(), "ɛː");
        // falls through to X-SAMPA for uncovered symbols
        assert!(convert("mIn@n", Notation::Sampa("de"))
            .unwrap()
            .contains("ə"));
    }

    #[test]
    fn english_sampa_diphthongs() {
        assert_eq!(convert("beI", Notation::Sampa("en")).unwrap(), "beɪ");
        assert_eq!(convert("aU", Notation::Sampa("en")).unwrap(), "aʊ");
        assert_eq!(convert("tSeI", Notation::Sampa("en")).unwrap(), "tʃeɪ");
    }

    #[test]
    fn swedish_sampa_suprasegmentals() {
        assert_eq!(convert("E:", Notation::Sampa("sv")).unwrap(), "ɛː");
        assert_eq!(convert("x", Notation::Sampa("sv")).unwrap(), "ɧ");
        assert_eq!(convert("rt", Notation::Sampa("sv")).unwrap(), "ʈ");
    }

    #[test]
    fn spanish_sampa_nasal() {
        assert_eq!(convert("maJon", Notation::Sampa("es")).unwrap(), "maɲon");
    }

    #[test]
    fn french_sampa_nasal_vowels() {
        assert_eq!(convert("a~", Notation::Sampa("fr")).unwrap(), "ɑ̃");
        assert_eq!(convert("9", Notation::Sampa("fr")).unwrap(), "œ");
    }

    #[test]
    fn arpabet_with_stress() {
        assert_eq!(
            convert("P ER0 M IH1 T", Notation::Arpabet).unwrap(),
            "pɚmˈɪt"
        );
        assert_eq!(convert("K AE1 T", Notation::Arpabet).unwrap(), "kˈæt");
        assert_eq!(
            convert("HH EH2 L OW0", Notation::Arpabet).unwrap(),
            "hˌɛloʊ"
        );
    }

    #[test]
    fn arpabet_stressless() {
        assert_eq!(convert("K AE T", Notation::Arpabet).unwrap(), "kæt");
    }

    #[test]
    fn arpabet_round_trip() {
        let ipa = convert("P ER0 M IH1 T", Notation::Arpabet).unwrap();
        let back = convert_from_ipa(&ipa, Notation::Arpabet).unwrap();
        // Stress placement: ARPABET forward places stress before vowels,
        // reverse reads it back on the vowel it precedes. "pɚˈmɪt" has
        // ˈ before m; reverse attaches it to the preceding vowel nucleus.
        assert!(back.contains("ER"), "got {back}");
        assert!(back.contains("IH1"), "got {back}");
    }

    #[test]
    fn arpabet_unknown_token_skipped() {
        assert_eq!(convert("K ZZ AE T", Notation::Arpabet).unwrap(), "kæt");
    }

    #[test]
    fn kirshenbaum_basic() {
        // k=k, æ=æ(Q), t=t in the table
        assert_eq!(convert("kQt", Notation::Kirshenbaum).unwrap(), "kɒt");
        // S=ʃ is in the table
        assert_eq!(convert("Sip", Notation::Kirshenbaum).unwrap(), "ʃip");
    }

    #[test]
    fn sampa_unknown_lang_falls_back_to_xsampa() {
        assert_eq!(
            convert("pr@tIks", Notation::Sampa("xx")).unwrap(),
            "prətɪks"
        );
    }

    #[test]
    fn convert_from_ipa_german_sampa() {
        let back = convert_from_ipa("bøːt", Notation::Sampa("de")).unwrap();
        assert!(back.contains('9') || back.contains('2'), "got {back}");
    }
}
