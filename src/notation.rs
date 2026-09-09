//! Phonetic notation conversion: SAMPA (per-language), X-SAMPA, ARPABET,
//! CMU Arpabet, Kirshenbaum ↔ IPA.
//!
//! Everything normalizes **to IPA** and, where reversible, **from IPA**
//! back. X-SAMPA/Praat/SIL/Branner come from the `ipa-translate` crate;
//! the per-language SAMPA tables and ARPABET are maintained here.
//!
//! **SAMPA vs X-SAMPA**: plain SAMPA is a family of language-specific
//! subsets that are *mostly* identical to X-SAMPA — the tables here only
//! list symbols that genuinely DIFFER from X-SAMPA for that language,
//! verified against Wells's charts (phon.ucl.ac.uk/home/sampa/).
//! Languages without verified tables fall through to X-SAMPA.
//!
//! ```
//! use voicegarden_lexicons::notation::{convert, Notation};
//!
//! // X-SAMPA (language-independent)
//! assert_eq!(convert("pr@tIks", Notation::XSampa).unwrap(), "prətɪks");
//!
//! // Spanish SAMPA: r = tap, rr = trill
//! assert_eq!(convert("pero", Notation::Sampa("es")).unwrap(), "peɾo");
//! assert_eq!(convert("perro", Notation::Sampa("es")).unwrap(), "pero");
//!
//! // ARPABET (CMUdict): spaces + optional stress digits
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
    /// Verified against Wells's charts: en, es, sv, nl, pt, ru (with
    /// language-specific entries); de, fr, it (verified as X-SAMPA
    /// identical — empty tables). Others fall back to X-SAMPA.
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
/// # Errors
///
/// Never in practice (kept for API stability).
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
// ONLY symbols that DIFFER from X-SAMPA, verified against Wells's
// charts at phon.ucl.ac.uk/home/sampa/<lang>.htm. Empty tables mean
// X-SAMPA handles that language correctly.

#[allow(clippy::too_many_lines)]
fn sampa_table(lang: &str) -> &'static HashMap<&'static str, &'static str> {
    static ES: OnceLock<HashMap<&'static str, &'static str>> = OnceLock::new();
    static SV: OnceLock<HashMap<&'static str, &'static str>> = OnceLock::new();
    static EN: OnceLock<HashMap<&'static str, &'static str>> = OnceLock::new();
    static NL: OnceLock<HashMap<&'static str, &'static str>> = OnceLock::new();
    static PT: OnceLock<HashMap<&'static str, &'static str>> = OnceLock::new();
    static RU: OnceLock<HashMap<&'static str, &'static str>> = OnceLock::new();
    static EMPTY: OnceLock<HashMap<&'static str, &'static str>> = OnceLock::new();

    let code = lang.split(['-', '_']).next().unwrap_or("");
    match code {
        // Spanish (Wells): r = tap [ɾ] (X-SAMPA gives [r] trill);
        // rr = trill [r]; jj = approximant [ʝ] (not X-SAMPA j+j).
        "es" => ES.get_or_init(|| {
            table(&[
                ("r", "ɾ"),
                ("rr", "r"),
                ("jj", "ʝ"),
                ("B", "β"), // = /b/ lenis, same as X-SAMPA but explicit
                ("D", "ð"), // = /d/ lenis
                ("G", "ɣ"), // = /g/ lenis
            ])
        }),
        // Swedish (Wells): u: = [ʉː] (NOT X-SAMPA [uː]); u0 = [ɵ] (not in
        // X-SAMPA); S = [ɧ] (the sj-sound, not X-SAMPA [ʃ]); C = [ɕ]
        // (the tj-sound, not X-SAMPA [ç]); retroflex clusters rt/rd/rn/rs/rl.
        "sv" => SV.get_or_init(|| {
            table(&[
                ("u:", "ʉː"),
                ("u0", "ɵ"),
                ("S", "ɧ"),
                ("C", "ɕ"),
                ("rt", "ʈ"),
                ("rd", "ɖ"),
                ("rn", "ɳ"),
                ("rs", "ʂ"),
                ("rl", "ɭ"),
            ])
        }),
        // English (Wells): E is "quite widely used in place of e" for the
        // DRESS vowel; X-SAMPA E = ɛ which is the wrong height.
        "en" => EN.get_or_init(|| table(&[("E", "e")])),
        // Italian (Wells): verified — all symbols map identically to
        // X-SAMPA (E=ɛ, O=ɔ, J=ɲ, L=ʎ, ts/dz/tS/dZ decompose correctly).
        // Falls through to the catch-all (X-SAMPA fallback).
        // Dutch (Wells): Au = [ʌu] (NOT X-SAMPA ɑ+u = ɑu — the Dutch
        // essential diphthong has a centralized first element).
        // Ei and 9y decompose correctly via X-SAMPA (ɛ+i, œ+y).
        "nl" => NL.get_or_init(|| table(&[("Au", "ʌu")])),
        // Portuguese (Wells): r = tap [ɾ] like Spanish; R = uvular.
        // 6=ɐ, E=ɛ, O=ɔ, J=ɲ, L=ʎ all match X-SAMPA.
        "pt" => PT.get_or_init(|| table(&[("r", "ɾ")])),
        // Russian (Wells): S=[ʂ] and Z=[ʐ] are retroflex sibilants (not
        // X-SAMPA ʃ/ʒ); tS=[t͡ɕ] is the Russian postalveolar affricate
        // (not X-SAMPA t͡ʃ). Palatalization uses ' after the consonant
        // (NOT X-SAMPA _j).
        "ru" => RU.get_or_init(|| {
            table(&[
                ("S", "ʂ"),
                ("Z", "ʐ"),
                ("tS", "t͡ɕ"),
                ("ts", "t͡s"),
                // Palatalized consonants: C' → Cʲ
                ("p'", "pʲ"),
                ("b'", "bʲ"),
                ("t'", "tʲ"),
                ("d'", "dʲ"),
                ("k'", "kʲ"),
                ("g'", "gʲ"),
                ("f'", "fʲ"),
                ("v'", "vʲ"),
                ("s'", "sʲ"),
                ("z'", "zʲ"),
                ("m'", "mʲ"),
                ("n'", "nʲ"),
                ("l'", "lʲ"),
                ("r'", "rʲ"),
                ("x'", "xʲ"),
            ])
        }),
        // German, French (verified — X-SAMPA handles them correctly).
        // Hungarian: no Wells chart exists; X-SAMPA fallback is the safe
        // default (better than invented mappings).
        _ => EMPTY.get_or_init(HashMap::new),
    }
}

fn table(pairs: &[(&'static str, &'static str)]) -> HashMap<&'static str, &'static str> {
    pairs.iter().copied().collect()
}

/// Longest-match symbol replacement using `table`, falling through to
/// X-SAMPA per symbol for anything the language table doesn't cover,
/// preserving spaces.
fn symbols_to_ipa(input: &str, lang_table: &HashMap<&'static str, &'static str>) -> String {
    let mut out = String::with_capacity(input.len() * 2);
    let mut sorted: Vec<&str> = lang_table.keys().copied().collect();
    sorted.sort_by_key(|k| std::cmp::Reverse(k.chars().count()));

    let mut chars = input.char_indices().peekable();
    while let Some((i, c)) = chars.next() {
        if c == ' ' {
            out.push(' ');
            continue;
        }
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
            // X-SAMPA fallback: transliterate this single character
            let one = c.to_string();
            let ipa = ipa_translate::xsampa_to_ipa(&one);
            out.push_str(&ipa);
        }
    }
    out
}

/// Reverse: IPA → language-specific symbols where the table covers it,
/// X-SAMPA otherwise.
fn ipa_to_symbols(ipa: &str, lang_table: &HashMap<&'static str, &'static str>) -> String {
    let reverse: HashMap<&str, &str> = lang_table.iter().map(|(k, v)| (*v, *k)).collect();
    let mut sorted: Vec<&str> = reverse.keys().copied().collect();
    sorted.sort_by_key(|k| std::cmp::Reverse(k.chars().count()));

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
            let one = c.to_string();
            out.push_str(&ipa_translate::ipa_to_xsampa(&one));
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

/// ARPABET → IPA. Stress digits (1=primary, 2=secondary) place the
/// stress mark at the start of the token they follow; IPA convention
/// places stress at the syllable onset, but for the vowel-carried
/// stress of ARPABET this approximation (stress before the vowel) is
/// the standard practical approach.
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
        let Some(ipa) = map.get(sym_upper.as_str()) else {
            continue; // unknown token: skip
        };
        match stress {
            "1" => out.push('ˈ'),
            "2" => out.push('ˌ'),
            _ => {}
        }
        out.push_str(ipa);
    }
    out
}

/// IPA → ARPABET. Stress marks (ˈ/ˌ) apply to the NEXT symbol,
/// matching the vowel-nucleus convention of the forward direction.
fn ipa_to_arpabet(ipa: &str) -> String {
    let map: HashMap<&str, &str> = arpabet_map().iter().map(|(k, v)| (*v, *k)).collect();
    let mut sorted: Vec<&str> = map.keys().copied().collect();
    sorted.sort_by_key(|k| std::cmp::Reverse(k.chars().count()));

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
                let mut matched = false;
                for key in &sorted {
                    if rest.starts_with(key) {
                        out.push_str(map[key]);
                        out.push_str(stress);
                        out.push(' ');
                        stress = "";
                        for _ in 1..key.chars().count() {
                            chars.next();
                        }
                        matched = true;
                        break;
                    }
                }
                let _ = matched;
                // no match: skip unknown char
            }
        }
    }
    out.trim_end().to_string()
}

// --- Kirshenbaum (per the spec at kirshenbaum.github.io) -------------------

const KIRSHENBAUM: &[(&str, &str)] = &[
    // Vowels
    ("i", "i"),
    ("I", "ɪ"),
    ("e", "e"),
    ("E", "ɛ"),
    ("&", "æ"),
    ("a", "a"),
    ("A", "ɑ"),
    ("O", "ɔ"),
    ("o", "o"),
    ("U", "ʊ"),
    ("u", "u"),
    ("U", "ʊ"),
    ("@", "ə"),
    ("3", "ɜ"),
    ("Y", "ʏ"),
    ("y", "y"),
    ("W", "ɯ"),
    ("V", "ʌ"),
    ("^", "ʌ"),
    ("}", "ʉ"),
    // Consonants — uppercase = voiced/voiceless pairs per spec
    ("p", "p"),
    ("b", "b"),
    ("t", "t"),
    ("d", "d"),
    ("k", "k"),
    ("g", "ɡ"),
    ("f", "f"),
    ("v", "v"),
    ("T", "θ"),
    ("D", "ð"),
    ("s", "s"),
    ("z", "z"),
    ("S", "ʃ"),
    ("Z", "ʒ"),
    ("h", "h"),
    ("m", "m"),
    ("n", "n"),
    ("N", "ŋ"),
    ("l", "l"),
    ("L", "ʎ"),
    ("r", "ɹ"),
    ("R", "ʁ"),
    ("w", "w"),
    ("j", "j"),
    ("y", "j"),
    // Kirshenbaum-specific: C=ç, x=x, X=x, G=ɢ, q=ʔ, Q=ɣ
    ("C", "ç"),
    ("x", "x"),
    ("X", "x"),
    ("G", "ɢ"),
    ("q", "ʔ"),
    ("Q", "ɣ"),
    ("B", "ʙ"),
    ("F", "ɱ"),
    // Diacritics
    (":", "ː"),
    ("'", "ˈ"),
    (",", "ˌ"),
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
    sorted.sort_by_key(|k| std::cmp::Reverse(k.chars().count()));
    let mut out = String::new();
    let mut chars = ipa.char_indices().peekable();
    while let Some((i, c)) = chars.next() {
        match c {
            'ː' => {
                out.push(':');
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

    // --- X-SAMPA (via ipa-translate, well-tested upstream) ---

    #[test]
    fn xsampa_basic() {
        assert_eq!(convert("pr@tIks", Notation::XSampa).unwrap(), "prətɪks");
    }

    // --- SAMPA: Spanish (verified against Wells's chart) ---

    #[test]
    fn spanish_r_is_tap_rr_is_trill() {
        // Wells: pero "peɾo" (r = tap ɾ)
        assert_eq!(convert("pero", Notation::Sampa("es")).unwrap(), "peɾo");
        // Wells: perro "pero" (rr = trill r)
        assert_eq!(convert("perro", Notation::Sampa("es")).unwrap(), "pero");
        // Wells: hielo "jjelo" (jj = ʝ)
        assert_eq!(convert("jjelo", Notation::Sampa("es")).unwrap(), "ʝelo");
    }

    #[test]
    fn spanish_other_symbols_fall_through() {
        // Wells: mucho "mutSo" (tS falls through X-SAMPA)
        assert_eq!(convert("mutSo", Notation::Sampa("es")).unwrap(), "mutʃo");
    }

    // --- SAMPA: Swedish (verified against Wells's chart) ---

    #[test]
    fn swedish_retroflex_clusters() {
        // Wells: hjort "jUrt" (rt = ʈ)
        assert_eq!(convert("rt", Notation::Sampa("sv")).unwrap(), "ʈ");
        // Wells: bord "bu:rd" (rd = ɖ)
        assert_eq!(convert("rd", Notation::Sampa("sv")).unwrap(), "ɖ");
        // Wells: fors "fOrs" (rs = ʂ, NOT ɾ+ɕ)
        assert_eq!(convert("rs", Notation::Sampa("sv")).unwrap(), "ʂ");
    }

    #[test]
    fn swedish_vowel_differences() {
        // Wells: sol "su:l" (u: = ʉː, NOT X-SAMPA uː)
        assert_eq!(convert("u:", Notation::Sampa("sv")).unwrap(), "ʉː");
        // Wells: buss "bu0s" (u0 = ɵ, not in X-SAMPA)
        assert_eq!(convert("u0", Notation::Sampa("sv")).unwrap(), "ɵ");
        // Wells: sjuk "S}:k" (S = ɧ, not X-SAMPA ʃ)
        assert_eq!(convert("S", Notation::Sampa("sv")).unwrap(), "ɧ");
    }

    // --- SAMPA: English (verified against Wells's chart) ---

    #[test]
    fn english_e_variant() {
        // Wells notes: E is "quite widely used in place of e" for DRESS
        assert_eq!(convert("E", Notation::Sampa("en")).unwrap(), "e");
        // But other symbols fall through to X-SAMPA correctly
        assert_eq!(convert("pIt", Notation::Sampa("en")).unwrap(), "pɪt");
    }

    // --- SAMPA: German/French (X-SAMPA handles them) ---

    #[test]
    fn german_falls_through_to_xsampa() {
        // Wells: Bächle "bEC@l@" — all X-SAMPA defaults
        assert_eq!(convert("bEC@l@", Notation::Sampa("de")).unwrap(), "bɛçələ");
        // Wells: schön "f2:n"
        assert_eq!(convert("f2:n", Notation::Sampa("de")).unwrap(), "føːn");
    }

    #[test]
    fn french_falls_through_to_xsampa() {
        // Wells: pâte "pAt" (A = ɑ, same as X-SAMPA)
        assert_eq!(convert("pAt", Notation::Sampa("fr")).unwrap(), "pɑt");
        // Wells: patte "pat" (a = a)
        assert_eq!(convert("pat", Notation::Sampa("fr")).unwrap(), "pat");
        // Wells: du "dy" (y = y, NOT the wrong u→y of the old table)
        assert_eq!(convert("dy", Notation::Sampa("fr")).unwrap(), "dy");
    }

    // --- SAMPA: unknown language falls back to X-SAMPA ---

    // --- SAMPA: Italian (verified — X-SAMPA handles everything) ---

    #[test]
    fn italian_falls_through_to_xsampa() {
        // Wells: cena "tSena" — tS decomposes to t͡ʃ via X-SAMPA
        assert_eq!(convert("tSena", Notation::Sampa("it")).unwrap(), "tʃena");
        // Wells: zitto "tsitto"
        assert_eq!(convert("tsitto", Notation::Sampa("it")).unwrap(), "tsitto");
    }

    // --- SAMPA: Dutch (verified against Wells) ---

    #[test]
    fn dutch_diphthong_au() {
        // Wells: goud "xAut" (Au = ʌu, NOT X-SAMPA ɑu)
        assert_eq!(convert("Au", Notation::Sampa("nl")).unwrap(), "ʌu");
        // Wells: fijn "fEin" (Ei = ɛi via X-SAMPA decomposition)
        assert_eq!(convert("Ei", Notation::Sampa("nl")).unwrap(), "ɛi");
    }

    // --- SAMPA: Portuguese (verified against Wells) ---

    #[test]
    fn portuguese_r_is_tap() {
        // Wells: caro "karu" (r = tap ɾ)
        assert_eq!(convert("karu", Notation::Sampa("pt")).unwrap(), "kaɾu");
    }

    // --- SAMPA: Russian (verified against Wells) ---

    #[test]
    fn russian_retroflex_sibilants() {
        // Wells: šar "S"ar" (S = ʂ retroflex, not ʃ)
        assert_eq!(convert("S", Notation::Sampa("ru")).unwrap(), "ʂ");
        // Wells: žir "Z"1r" (Z = ʐ retroflex, not ʒ)
        assert_eq!(convert("Z", Notation::Sampa("ru")).unwrap(), "ʐ");
        // Wells: čaj "tS'"aj" (tS = t͡ɕ)
        assert_eq!(convert("tS", Notation::Sampa("ru")).unwrap(), "t͡ɕ");
    }

    #[test]
    fn russian_palatalization() {
        // Wells: pit' "p'"it'" (p' = pʲ)
        assert_eq!(convert("p'", Notation::Sampa("ru")).unwrap(), "pʲ");
        assert_eq!(convert("s'", Notation::Sampa("ru")).unwrap(), "sʲ");
        // Wells: den' "d'"en'" (d' = dʲ)
        assert_eq!(convert("d'", Notation::Sampa("ru")).unwrap(), "dʲ");
    }

    #[test]
    fn sampa_unknown_lang_falls_back() {
        assert_eq!(
            convert("pr@tIks", Notation::Sampa("xx")).unwrap(),
            "prətɪks"
        );
    }

    // --- ARPABET ---

    #[test]
    fn arpabet_basic() {
        assert_eq!(convert("K AE1 T", Notation::Arpabet).unwrap(), "kˈæt");
        assert_eq!(convert("K AE T", Notation::Arpabet).unwrap(), "kæt");
    }

    #[test]
    fn arpabet_stress_variants() {
        assert_eq!(
            convert("P ER0 M IH1 T", Notation::Arpabet).unwrap(),
            "pɚmˈɪt"
        );
        assert_eq!(
            convert("HH EH2 L OW0", Notation::Arpabet).unwrap(),
            "hˌɛloʊ"
        );
    }

    #[test]
    fn arpabet_unknown_token_skipped() {
        assert_eq!(convert("K ZZ AE T", Notation::Arpabet).unwrap(), "kæt");
    }

    // --- Kirshenbaum ---

    #[test]
    fn kirshenbaum_basic() {
        // Spec: k=k, Q=ɒ(→actually Q=ɣ per newer spec tables; use verified pairs)
        assert_eq!(convert("kAt", Notation::Kirshenbaum).unwrap(), "kɑt");
        assert_eq!(convert("Sip", Notation::Kirshenbaum).unwrap(), "ʃip");
    }

    // --- Reverse direction ---

    #[test]
    fn xsampa_reverse() {
        let ipa = convert("pr@tIks", Notation::XSampa).unwrap();
        let back = convert_from_ipa(&ipa, Notation::XSampa).unwrap();
        assert_eq!(back, "pr@tIks");
    }

    #[test]
    fn spanish_reverse() {
        let back = convert_from_ipa("peɾo", Notation::Sampa("es")).unwrap();
        assert!(back.contains('r'), "got {back}");
    }
}
