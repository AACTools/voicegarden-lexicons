#!/usr/bin/env python3
"""Package the v2 expanded (distilled) lexicon bundles.

Sources (v2, all local):
  staging/<tag>/merged.tsv          base dictionary
  distill-v2/<tag>.tsv              v2 distilled entries
  distill-fst-v2/<tag>.fst + .pho   compiled expanded lexicon
  expanded-v2/<tag>.wfst.fst         Phonetisaurus model
  expanded-v2/<tag>.metrics.json     Phonetisaurus metrics

Usage: python3 build_expanded_v2.py --out dist/expanded-v2
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import tarfile
import tempfile
from pathlib import Path

REPO = Path("/home/willwade/GitHub/AACTools/voicegarden-lexicons")

# v2 audit data: (agreement_rate, three_vote_filtered)
# audit_exact is None for now (needs distill_audit.py run)
# Agreement rates from distill-v2/summary.json
AUDIT = {
    "ara": (0.555, False),
    "ben-Rarh": (0.415, False),
    "dan": (0.531, False),
    "deu": (0.711, False),
    "ell": (0.888, True),
    "eng-US": (0.593, True),
    "fas": (0.614, False),
    "fin": (0.873, False),
    "fra": (0.822, False),
    "heb": (0.358, False),
    "hin": (0.161, False),
    "ind": (0.768, False),
    "isl": (0.743, False),
    "ita": (0.743, False),
    "nld": (0.714, False),
    "nob": (0.371, False),
    "pol": (0.958, False),
    "por-BR": (0.811, False),
    "por-PT": (0.976, False),
    "ron": (0.897, False),
    "slk": (0.906, False),
    "slv": (0.359, False),
    "spa-ES": (0.909, False),
    "spa-LatAm": (0.920, False),
    "swe": (0.545, True),
    "tam": (0.366, False),
    "tur": (0.873, False),
    "urd": (0.668, False),
}

BCP47 = {
    "ara": "ar", "ben-Rarh": "bn", "dan": "da", "deu": "de",
    "ell": "el", "eng-US": "en-US", "fas": "fa", "fin": "fi",
    "fra": "fr", "heb": "he", "hin": "hi", "ind": "id",
    "isl": "is", "ita": "it", "nld": "nl", "nob": "nb",
    "pol": "pl", "por-BR": "pt-BR", "por-PT": "pt-PT",
    "ron": "ro", "slk": "sk", "slv": "sl", "spa-ES": "es-ES",
    "spa-LatAm": "es-419", "swe": "sv", "tam": "ta", "tur": "tr",
    "urd": "ur",
}

NAMES = {
    "ara": "Arabic", "ben-Rarh": "Bengali (Rarh)", "dan": "Danish",
    "deu": "German", "ell": "Greek", "eng-US": "English (US)",
    "fas": "Persian", "fin": "Finnish", "fra": "French",
    "heb": "Hebrew", "hin": "Hindi", "ind": "Indonesian",
    "isl": "Icelandic", "ita": "Italian", "nld": "Dutch",
    "nob": "Norwegian Bokmal", "pol": "Polish",
    "por-BR": "Portuguese (Brazil)", "por-PT": "Portuguese (Portugal)",
    "ron": "Romanian", "slk": "Slovak", "slv": "Slovenian",
    "spa-ES": "Spanish (Castilian)", "spa-LatAm": "Spanish (Latin America)",
    "swe": "Swedish", "tam": "Tamil", "tur": "Turkish", "urd": "Urdu",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(tag: str, out: Path) -> dict | None:
    merged = REPO / f"staging/{tag}/merged.tsv"
    suffix = ".3vote.tsv" if AUDIT[tag][1] else ".tsv"
    distill = REPO / f"distill-v2/{tag}{suffix}"
    fst = REPO / f"distill-fst-v2/{tag}.fst"
    pho = REPO / f"distill-fst-v2/{tag}.pho"
    wfst = REPO / f"expanded-v2/{tag}.wfst.fst"
    metrics_p = REPO / f"expanded-v2/{tag}.metrics.json"
    for p in (merged, distill, fst, pho, wfst, metrics_p):
        if not p.exists():
            print(f"  !! {tag}: missing {p.name}")
            return None

    n_base = sum(1 for _ in merged.open(encoding="utf-8"))
    n_distill = sum(1 for _ in distill.open(encoding="utf-8"))
    metrics = json.loads(metrics_p.read_text())
    agreement, three_vote = AUDIT[tag]

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        lexicon_txt = td / "lexicon.txt"
        with lexicon_txt.open("w", encoding="utf-8") as out_f:
            for src in (merged, distill):
                for line in src.open(encoding="utf-8"):
                    out_f.write(line)

        bundle = [(fst, fst.name), (pho, pho.name),
                  (lexicon_txt, lexicon_txt.name),
                  (wfst, "phonetisaurus.fst")]
        source = ("dictionary: voicegarden-lexicons staging (gruut/"
                  "wikipron, MIT / CC BY-SA 4.0); "
                  "added entries distilled from willwade/"
                  "byt5-g2p-multilingual v2 (small+tiny agreement)")
        notice = (f"voicegarden-lexicons {tag} (expanded v2)\n"
                  f"source: {source}\n"
                  f"license: MIT; distilled entries inherit training-data "
                  f"licenses (WikiPron CC BY-SA 4.0)\n")
        tar_path = out / f"{tag}.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tar:
            for f, arcname in bundle:
                tar.add(f, arcname=arcname)
            info = tarfile.TarInfo("NOTICE")
            data = notice.encode()
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

    return {
        "lang": tag,
        "name": NAMES[tag],
        "bcp47": BCP47[tag],
        "entries": n_base + n_distill,
        "entries_base": n_base,
        "entries_distilled": n_distill,
        "distill_agreement": agreement,
        "audit_exact": None,  # needs distill_audit.py run
        "three_vote_filtered": three_vote,
        "license": "MIT",
        "source": source,
        "phonetisaurus": metrics,
        "file": f"{tag}.tar.gz",
        "sha256": sha256(tar_path),
        "size_bytes": tar_path.stat().st_size,
        "format": "floravox-fst-lexicon/1",
        "version": "expanded-v2",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="dist/expanded-v2")
    args = ap.parse_args()
    out = REPO / args.out
    out.mkdir(parents=True, exist_ok=True)

    manifest = {"version": "expanded-v2",
                "format": "voicegarden-lexicons-expanded/1",
                "languages": []}
    for tag in sorted(AUDIT):
        print(f"== {tag}")
        entry = build(tag, out)
        if entry:
            manifest["languages"].append(entry)
            print(f"  {entry['entries']:,} entries "
                  f"({entry['entries_distilled']:,} distilled), "
                  f"{entry['size_bytes']:,} bytes")
    (out / "expanded.json").write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nmanifest: {out / 'expanded.json'} ({len(manifest['languages'])} languages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())