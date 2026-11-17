#!/usr/bin/env python3
"""Feature-based phonological process inventory for the fuzzy decoder.

Each process is a rewrite over phone sequences, defined on panphon
distinctive features where articulatory (clinical processes: Stoel-
Gammon & Dunn; Grunwell; Dodd) or on perceptual confusion data
(Miller & Nicely 1955; Wang & Bilger 1973 — loaded as data, not
rules). Processes are pure functions over phone sequences returning
rewrites or None; weighting and stochastic application live in
corruptor.py.

Conventions: phones are space-separated IPA tokens, optionally
stress-marked (ˈ / ˌ as separate tokens — the eng/nld corpus
convention). Processes that need prosody (weak-syllable deletion,
vowel neutralisation) no-op gracefully on unmarked input.

v0 scope: single-language (English) validation; the feature machinery
is language-independent by construction.
"""

from __future__ import annotations

import panphon

ft = panphon.FeatureTable()
SEG = ft.seg_dict  # segment string -> Segment with numeric attrs (+1/-1/0)

STRESS = {"ˈ", "ˌ"}

NEEDS_STRESS = {"weak_syllable_deletion", "vowel_neutralisation"}


def _seg(ph: str):
    base = ph.strip("ˈˌː")
    if base in SEG:
        return SEG[base]
    if base and base[0] in SEG:
        return SEG[base[0]]
    return None


def is_vowel(ph: str) -> bool:
    if ph in STRESS or ph == "ː":
        return False
    s = _seg(ph)
    return s is not None and s.get("syl") == 1


def sonority(ph: str) -> int:
    if is_vowel(ph):
        return 10
    s = _seg(ph)
    if s is None:
        return 5
    rank = 1
    if s.get("voi") == 1:
        rank += 1
    if s.get("cont") == 1:
        rank += 2
    if s.get("nas") == 1:
        rank += 4
    return rank


def _feats(ph: str) -> dict | None:
    s = _seg(ph)
    if s is None:
        return None
    return dict(s.items())


STOPS = ["p", "t", "k", "b", "d", "ɡ"]
OBSTRUENTS = STOPS + ["f", "v", "s", "z", "ʃ", "ʒ", "θ", "ð"]
ALVEOLARS = ["t", "d", "n", "s", "z", "l", "ɹ"]


def _closest(target: dict, candidates: list[str], keep: list[str]) -> str | None:
    """Candidate matching `target` on `keep` features, fewest total diffs."""
    best, best_d = None, 99
    for c in candidates:
        f = _feats(c)
        if f is None:
            continue
        if any(f.get(k) != target.get(k) for k in keep):
            continue
        d = sum(1 for k in f if f.get(k) != target.get(k))
        if d < best_d:
            best, best_d = c, d
    return best


# --- single-phone processes ---------------------------------------------


def stopping(ph: str) -> str | None:
    """Fricative -> homorganic stop (s->t, f->p, v->b, z->d ...)."""
    f = _feats(ph)
    if not f:
        return None
    if f["syl"] == -1 and f["cont"] == 1 and f["son"] == -1:
        return _closest(f, STOPS, keep=["ant", "cor", "lab"])
    return None


def fronting(ph: str) -> str | None:
    """Velar -> alveolar place shift (k->t, ɡ->d, ŋ->n)."""
    f = _feats(ph)
    if not f or f["syl"] == 1 or f["cor"] == 1:
        return None
    if f.get("back") == 1 and f.get("hi") == 1:
        return _closest(f, ALVEOLARS, keep=["voi", "nas"])
    return None


def gliding(ph: str) -> str | None:
    """Liquid -> glide (l/ɹ/ɫ/ɭ -> w)."""
    if ph in ("l", "ɹ", "ɫ", "ɭ"):
        return "w"
    return None


def voicing_flip(ph: str) -> str | None:
    """Feature flip shared by final devoicing / prevocalic voicing."""
    f = _feats(ph)
    if not f or f["syl"] == 1:
        return None
    flipped = dict(f)
    flipped["voi"] = -f["voi"] if f["voi"] in (1, -1) else f["voi"]
    out = _closest(flipped, OBSTRUENTS, keep=["ant", "cor", "lab"])
    return out if out != ph else None


# --- sequence-level processes -------------------------------------------


def final_consonant_deletion(phones: list[str]) -> tuple[list[str], str] | None:
    if len(phones) >= 2 and not is_vowel(phones[-1]) and phones[-1] not in STRESS:
        return phones[:-1], phones[-1]
    return None


def cluster_reduction(phones: list[str]) -> tuple[list[str], str] | None:
    """Obstruent cluster -> single member (keep the more sonorous)."""
    for i in range(len(phones) - 1):
        a, b = phones[i], phones[i + 1]
        if is_vowel(a) or is_vowel(b) or a in STRESS or b in STRESS:
            continue
        fa, fb = _feats(a), _feats(b)
        if not fa or not fb:
            continue
        if fa["son"] == -1 and fb["son"] == -1:
            keep = a if sonority(a) >= sonority(b) else b
            dropped = b if keep == a else a
            return phones[:i] + [keep] + phones[i + 2:], dropped
    return None


def regressive_place_assimilation(phones: list[str]) -> tuple[list[str], str] | None:
    """Coda consonant takes the next onset's place (t|k -> k|k — the
    'remote control' case)."""
    for i in range(len(phones) - 1):
        a, b = phones[i], phones[i + 1]
        if is_vowel(a) or is_vowel(b) or a in STRESS or b in STRESS:
            continue
        fa, fb = _feats(a), _feats(b)
        if not fa or not fb:
            continue
        # velar target: high+back obstruent/nasal (k, ɡ, ŋ)
        b_velar = fb.get("back") == 1 and fb.get("hi") == 1 and fb.get("syl") == -1
        a_coronal = fa.get("cor") == 1
        a_labial = fa.get("lab") == 1
        if b_velar and (a_coronal or a_labial) and fa.get("nas") == fb.get("nas"):
            return phones[:i] + [b] + phones[i + 1:], a
    return None


def _syllables(phones: list[str]) -> list[list[str]]:
    out: list[list[str]] = []
    cur: list[str] = []
    for ph in phones:
        if is_vowel(ph):
            cur.append(ph)
            out.append(cur)
            cur = []
        else:
            cur.append(ph)
    if cur:
        if out:
            out[-1].extend(cur)
        else:
            out.append(cur)
    return out


def weak_syllable_deletion(phones: list[str]) -> tuple[list[str], int] | None:
    """Drop one unstressed, non-final syllable (including pre-stress
    initial — 'remote control' -> 'mote control' class of deletions)."""
    if not any(p in STRESS for p in phones):
        return None
    syls = _syllables(phones)
    if len(syls) < 3:
        return None
    # pretonic-initial deletion is the dominant English child pattern
    # ('remote' -> 'mote', 'banana' -> 'nana'); fall back to other
    # unstressed non-final syllables
    order = [0] + list(range(1, len(syls) - 1))
    for idx in order:
        if not any(p in STRESS for p in syls[idx]):
            kept = [p for j, syl in enumerate(syls) if j != idx for p in syl]
            return kept, idx
    return None


def vowel_neutralisation(phones: list[str]) -> list[str] | None:
    """Unstressed vowel before the first stress -> ə (approximation)."""
    if not any(p in STRESS for p in phones):
        return None
    out: list[str] = []
    seen_stress = False
    for ph in phones:
        if ph in STRESS:
            seen_stress = True
            out.append(ph)
        elif is_vowel(ph) and not seen_stress and ph != "ə":
            out.append("ə")
        else:
            out.append(ph)
    return out if out != phones else None


# perceptual profile: Miller & Nicely (1955) top confusion pairs at low
# SNR, normalised — illustrative v0 excerpt; full matrices ship as data
# when the perceptual profile lands
MILLER_NICELY_TOP = {
    ("p", "t"): 0.18, ("t", "k"): 0.22, ("k", "p"): 0.12,
    ("f", "θ"): 0.30, ("s", "θ"): 0.26, ("v", "b"): 0.15,
    ("ð", "d"): 0.17, ("z", "d"): 0.14, ("ʃ", "t͡ʃ"): 0.11,
    ("m", "n"): 0.13, ("n", "ŋ"): 0.16, ("b", "ɡ"): 0.10,
}
