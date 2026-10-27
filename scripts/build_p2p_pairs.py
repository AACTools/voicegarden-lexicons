#!/usr/bin/env python3
"""Build P2P convention-conversion pair tables for sherpa-onnx 2.x.

sherpa-onnx 2.0 removed the espeak-ng phonemizer; espeak-orphaned
English models (piper, matcha-en, kokoro-en, kitten) need a lexicon in
their own phoneme convention. rust-tts-wrapper generates one from the
gruut lexicon via a per-convention pair table (gruut phoneme sequence
→ target-convention sequence); this script builds those tables by
aligning the gruut lexicon against a reference lexicon in each target
convention.

Tables produced:
  p2p-misaki.tsv  — reference: the kokoro multi-lang bundled
                    lexicon-us-en.txt (Apache-2.0, misaki convention:
                    uppercase diphthongs A I O W Y, ligature affricates,
                    split rhotics). Used for kokoro-en / kitten models.
  p2p-espeak.tsv  — reference: CMUDict (BSD-2-Clause-like) converted
                    ARPABET→IPA in the piper/espeak convention
                    (decomposed diphthongs e ɪ / o ʊ / ..., split
                    stressed rhotics ˈɝ → ˈ ɜ ɹ, ə/ʌ stress split).
                    Used for piper / matcha-en models.

Output format (one line per word): `gruut|ph1|ph2\ttgt1 tgt2 tgt3`
(pipe-separated source, space-separated target). Duplicate gruut
sequences keep the first occurrence (stable homograph choice).

Usage:
  build_p2p_pairs.py misaki --gruut LEXICON.TXT --kokoro KOKORO-LEX.TXT \
      --out p2p-misaki.tsv
  build_p2p_pairs.py espeak --gruut LEXICON.TXT [--cmudict cmudict.dict] \
      --out p2p-espeak.tsv
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

CMUDICT_URL = (
    "https://raw.githubusercontent.com/cmusphinx/cmudict/master/cmudict.dict"
)

# ARPABET → IPA, single symbols only. Diphthongs and the AH/ER stress
# splits are handled separately in convert_arpabet_line().
ARPA_SINGLE: dict[str, list[str]] = {
    "AA": ["ɑ"], "AE": ["æ"], "AO": ["ɔ"], "B": ["b"], "CH": ["t", "ʃ"],
    "D": ["d"], "DH": ["ð"], "EH": ["ɛ"], "F": ["f"], "G": ["ɡ"],
    "HH": ["h"], "IH": ["ɪ"], "IY": ["i"], "JH": ["d", "ʒ"], "K": ["k"],
    "L": ["l"], "M": ["m"], "N": ["n"], "NG": ["ŋ"], "P": ["p"],
    "R": ["ɹ"], "S": ["s"], "SH": ["ʃ"], "T": ["t"], "TH": ["θ"],
    "UH": ["ʊ"], "UW": ["u"], "V": ["v"], "W": ["w"], "Y": ["j"],
    "Z": ["z"], "ZH": ["ʒ"],
}

# Diphthongs decompose into component IPA characters (the piper/espeak
# phoneme stream emits them separately — piper's tokens.txt has no
# combined diphthong symbols).
ARPA_DIPH: dict[str, list[str]] = {
    "AW": ["a", "ʊ"], "AY": ["a", "ɪ"], "EY": ["e", "ɪ"],
    "OW": ["o", "ʊ"], "OY": ["ɔ", "ɪ"],
}


# English function words that espeak leaves unstressed in connected
# speech. CMUDICT marks every monosyllable with stress 1 (including
# "this", "is", "a"); espeak — and therefore piper training data — does
# not stress these. The list is standard English grammar (the same set
# the misaki destressing analysis produced from the kokoro lexicon).
DESTRESS_WORDS: set[str] = {
    "the", "be", "to", "of", "a", "in", "that", "have", "it", "for",
    "on", "with", "he", "as", "you", "at", "this", "but", "his", "by",
    "from", "they", "we", "she", "or", "an", "will", "would", "could",
    "should", "was", "were", "been", "has", "had", "them", "then",
    "these", "its", "us", "are", "is", "do", "does", "did", "not",
    "and", "if", "so", "up", "out", "who", "what", "when", "where",
    "why", "how", "than", "there", "here", "now", "him", "her", "me",
    "my", "your", "our", "their", "s", "t", "ll", "ve", "re", "d", "m",
}


def convert_arpabet_line(phones: list[str], word: str | None = None) -> list[str] | None:
    """One CMUDICT pronunciation → piper/espeak-convention IPA tokens.

    Stress: 1 → ˈ, 2 → ˌ before the vowel (or the first diphthong
    component). AH0 → ə vs AH1 → ˈʌ; ER0 → ɚ vs ER1 → ˈ ɜ ɹ (piper's
    vocabulary has ɚ and ɜ but not ɝ — stressed rhotics split).
    Function words carry no stress marks (espeak behaviour; CMUDICT
    marks every monosyllable, which mismatches the training data).
    """
    destress = word is not None and word in DESTRESS_WORDS
    out: list[str] = []
    for phone in phones:
        base, stress = phone, None
        if phone and phone[-1] in "012":
            base, stress = phone[:-1], int(phone[-1])
        if destress:
            stress = 0 if stress is not None else None
        if base == "AH":
            if stress == 0 or stress is None:
                out.append("ə")
            else:
                out.append("ˈ" if stress == 1 else "ˌ")
                out.append("ʌ")
        elif base == "ER":
            if stress == 0 or stress is None:
                out.append("ɚ")
            else:
                out.append("ˈ" if stress == 1 else "ˌ")
                out.append("ɜ")
                out.append("ɹ")
        elif base in ARPA_DIPH:
            parts = ARPA_DIPH[base]
            if stress in (1, 2):
                out.append("ˈ" if stress == 1 else "ˌ")
            out.extend(parts)
        elif base in ARPA_SINGLE:
            if stress in (1, 2):
                out.append("ˈ" if stress == 1 else "ˌ")
            out.extend(ARPA_SINGLE[base])
        else:
            return None  # unmapped symbol — drop this pronunciation
    return out


def load_cmudict_ipa(path: Path) -> dict[str, list[str]]:
    """CMUDict → {word: [IPA tokens]}, first pronunciation per word.

    Variant suffixes `word(2)` collapse onto `word`; the first (most
    frequent) pronunciation wins. Words are lowercased to match gruut.
    """
    result: dict[str, list[str]] = {}
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or line.startswith(";"):
                continue
            parts = line.split()
            word = parts[0]
            if word.endswith(")") and "(" in word:
                word = word[: word.rindex("(")]
            word = word.lower()
            if word in result:
                continue  # first pronunciation wins
            ipa = convert_arpabet_line(parts[1:], word)
            if ipa:
                result[word] = ipa
    return result


def load_lexicon(path: Path) -> dict[str, list[str]]:
    """`word<TAB or space>ph1 ph2...` → {word: [phonemes]}, first wins."""
    result: dict[str, list[str]] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 2 and parts[0] not in result:
                result[parts[0]] = parts[1:]
    return result


def align(source: dict[str, list[str]], target: dict[str, list[str]],
          out_path: Path) -> dict[str, int]:
    """Write the pair table for every word in both lexicons."""
    overlap = sorted(set(source) & set(target))
    stats = {"source": len(source), "target": len(target),
             "overlap": len(overlap), "written": 0}
    with out_path.open("w", encoding="utf-8") as out:
        for word in overlap:
            src, tgt = source[word], target[word]
            if not src or not tgt:
                continue
            out.write(f"{'|'.join(src)}\t{' '.join(tgt)}\n")
            stats["written"] += 1
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)

    p_misaki = sub.add_parser(
        "misaki", help="align gruut against the kokoro bundled lexicon")
    p_misaki.add_argument("--gruut", type=Path, required=True)
    p_misaki.add_argument("--kokoro", type=Path, required=True,
                          help="path to kokoro multi-lang lexicon-us-en.txt")
    p_misaki.add_argument("--out", type=Path, required=True)

    p_espeak = sub.add_parser(
        "espeak", help="align gruut against CMUDict (converted to IPA)")
    p_espeak.add_argument("--gruut", type=Path, required=True)
    p_espeak.add_argument("--cmudict", type=Path, default=None,
                          help=f"cmudict.dict path (default: download {CMUDICT_URL})")
    p_espeak.add_argument("--out", type=Path, required=True)

    args = parser.parse_args()
    gruut = load_lexicon(args.gruut)

    if args.mode == "misaki":
        reference = load_lexicon(args.kokoro)
        ref_name = str(args.kokoro)
    else:
        cmudict = args.cmudict
        if cmudict is None:
            cmudict = Path("/tmp/cmudict.dict")
            if not cmudict.exists():
                print(f"downloading {CMUDICT_URL}")
                data = urllib.request.urlopen(CMUDICT_URL).read()
                cmudict.write_bytes(data)
        reference = load_cmudict_ipa(cmudict)
        ref_name = f"cmudict:{cmudict}"

    stats = align(gruut, reference, args.out)
    print(f"gruut:       {stats['source']} words  ({args.gruut})")
    print(f"reference:   {stats['target']} words  ({ref_name})")
    print(f"overlap:     {stats['overlap']} words")
    print(f"pairs:       {stats['written']} → {args.out}")


if __name__ == "__main__":
    main()
