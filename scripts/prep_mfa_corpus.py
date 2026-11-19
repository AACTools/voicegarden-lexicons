#!/usr/bin/env python3
"""Prepare a Common Voice release for MFA alignment (lv pilot).

Input: an extracted cv-corpus locale directory (validated.tsv + clips/).
Output: an MFA corpus tree — one speaker directory per client_id, each
utterance a symlinked clip + a `.lab` transcript — and an alignment
dictionary word→phones built from a seed lexicon (the bundle's staged
kaikki/wikipron TSV) with an Epitran fallback for out-of-seed words
(the cvu/VoxCommunis bootstrap recipe: G2P covers the vocabulary, the
audio sets the timing, the attestation gate in
scripts/harvest_voxcommunis.py decides what ships).

Usage: scripts/prep_mfa_corpus.py --cv-dir <extracted>/lv --seed staging/lav/kaikki.folded.tsv \
       --out runs-cv-scope/lv-corpus --dict-out runs-cv-scope/lv-align-dict.tsv \
       [--max-clips N] [--epitran lav_Latn]
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

NONWORD = re.compile(r"[^\w\s'’-]", re.UNICODE)


def read_validated(tsv: Path):
    with tsv.open(encoding="utf-8") as f:
        header = f.readline().rstrip("\n").split("\t")
        idx = {name: i for i, name in enumerate(header)}
        name_col = next(c for c in ("path", "filename") if c in idx)
        text_col = next(c for c in ("sentence", "text") if c in idx)
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < len(header):
                continue
            yield (parts[idx["client_id"]], parts[idx[name_col]],
                   parts[idx[text_col]])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cv-dir", required=True, type=Path)
    ap.add_argument("--seed", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--max-clips", type=int, default=None)
    ap.add_argument("--dict-out", default=None,
                    help="optional: also write a word->phones dict. With "
                    "MFA's own G2P (--g2p_model_path on `mfa align`) OOV "
                    "words are generated at align time and this is unneeded")
    ap.add_argument("--epitran", default="none",
                    help="epitran map for OOV words; 'none' (default) — "
                    "Epitran lav-Latn disagrees with the kaikki seed's "
                    "conventions and voicing; MFA G2P is preferred")
    args = ap.parse_args()

    validated = args.cv_dir / "validated.tsv"
    clips = args.cv_dir / "clips"
    if not validated.exists() or not clips.exists():
        print(f"!! {args.cv_dir} is not a cv-corpus locale dir "
              "(need validated.tsv + clips/)", file=sys.stderr)
        return 1

    seed: dict[str, str] = {}
    for line in args.seed.read_text(encoding="utf-8").splitlines():
        if "\t" in line:
            w, _, pron = line.partition("\t")
            seed[w.strip()] = pron.strip()

    epi = None
    if args.epitran != "none":
        try:
            import epitran
            epi = epitran.Epitran(args.epitran)
        except Exception as e:  # noqa: BLE001
            print(f"warning: epitran {args.epitran} unavailable ({e}); "
                  "OOV words left to MFA's g2p pipeline or must be added "
                  "to the seed", file=sys.stderr)

    vocab: Counter = Counter()
    rows = []
    for client, fname, text in read_validated(validated):
        text = " ".join(unicodedata.normalize("NFC", text).split())
        clean = NONWORD.sub("", text).strip()
        if not clean or fname in {r[1] for r in rows[:0]}:
            continue
        rows.append((client, fname, clean))
        vocab.update(clean.split())
        if args.max_clips and len(rows) >= args.max_clips:
            break

    n_written = 0
    for client, fname, clean in rows:
        utt = args.out / client[:8] / Path(fname).stem
        utt.parent.mkdir(parents=True, exist_ok=True)
        src = (clips / fname).resolve()
        if not src.exists():
            continue
        link = utt.with_suffix(".mp3")
        if not link.exists():
            link.symlink_to(src)
        utt.with_suffix(".lab").write_text(clean + "\n", encoding="utf-8")
        n_written += 1

    print(f"corpus: {n_written:,} utterances under {args.out} "
          f"({len({c for c, _, _ in rows}):,} speakers)")

    if args.dict_out:
        dict_rows: list[tuple[str, str]] = []
        from_seed = from_epi = 0
        for word, count in vocab.most_common():
            if word in seed:
                dict_rows.append((word, seed[word]))
                from_seed += 1
            elif epi is not None:
                try:
                    pron = epi.transliterate(word)
                except Exception:  # noqa: BLE001
                    continue
                if pron:
                    dict_rows.append((word, pron))
                    from_epi += 1
        args.dict_out.parent.mkdir(parents=True, exist_ok=True)
        with args.dict_out.open("w", encoding="utf-8") as f:
            for w, p in dict_rows:
                f.write(f"{w}\t{p}\n")
        print(f"dict {len(dict_rows):,} rows "
              f"(seed {from_seed:,}, epitran {from_epi:,})")

    print(f"vocabulary: {len(vocab):,} types "
          f"(seed-covered {sum(1 for w in vocab if w in seed):,})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
