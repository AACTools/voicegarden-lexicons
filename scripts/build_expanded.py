#!/usr/bin/env python3
"""Package the expanded (distilled) lexicon bundles.

Per language, a bundle contains the same files as the base bundles:
the compiled lexicon FST, its phoneme inventory, lexicon.txt, a
Phonetisaurus model trained on the EXPANDED lexicon (so the OOV
alphabet matches by construction), and a NOTICE distinguishing
dictionary data from distilled data. The manifest records both
counts plus the audit numbers from docs/distill-audit.md.

Sources (all local):
  staging/<tag>/merged.tsv        the base dictionary lexicon
  distill/<tag>.tsv               distilled entries (audited)
  distill/<tag>.3vote.tsv         3-vote-filtered entries (eng, ell, swe)
  distill-fst/<tag>.fst + .pho    compiled expanded lexicon
  /tmp/opencode/<tag>-new.fst     Phonetisaurus trained on the combined TSV
  /tmp/opencode/<tag>-metrics.json

Usage: python3 build_expanded.py [--out dist/expanded]
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import tarfile
import tempfile
from pathlib import Path

REPO = Path("/home/willwade/GitHub/AACTools/voicegarden-lexicons")
TRAIN_DIR = Path("/tmp/opencode")

# tag -> (audit exact precision, 3-vote filtered?, agreement rate)
AUDIT = {
    "spa-ES": (1.00, False, 1.00),
    "deu": (0.975, False, 0.795),
    "pol": (0.96, False, 0.99),
    "ita": (0.958, False, 0.955),
    "fra": (0.929, False, 0.91),
    "tur": (0.934, False, 0.798),
    "spa-LatAm": (None, False, 0.916),
    "por-PT": (None, False, 0.976),
    "eng-US": (0.983, True, 0.485),
    "ell": (0.86, True, 0.942),
    "swe": (0.818, True, 0.717),
}


BCP47 = {"spa-ES": "es-ES", "spa-LatAm": "es-419", "por-PT": "pt-PT",
         "deu": "de", "pol": "pl", "ita": "it", "fra": "fr", "tur": "tr",
         "eng-US": "en-US", "ell": "el", "swe": "sv"}
NAMES = {"spa-ES": "Spanish (Castilian)", "spa-LatAm": "Spanish (Latin America)",
         "por-PT": "Portuguese (Portugal)", "deu": "German", "pol": "Polish",
         "ita": "Italian", "fra": "French", "tur": "Turkish",
         "eng-US": "English (US)", "ell": "Greek", "swe": "Swedish"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(tag: str, out: Path) -> dict | None:
    merged = REPO / f"staging/{tag}/merged.tsv"
    suffix = ".3vote.tsv" if AUDIT[tag][1] else ".tsv"
    distill = REPO / f"distill/{tag}{suffix}"
    fst = REPO / f"distill-fst/{tag}.fst"
    pho = REPO / f"distill-fst/{tag}.pho"
    wfst = TRAIN_DIR / f"{tag}-new.fst"
    metrics_p = TRAIN_DIR / f"{tag}-metrics.json"
    for p in (merged, distill, fst, pho, wfst, metrics_p):
        if not p.exists():
            print(f"  !! {tag}: missing {p.name}")
            return None

    n_base = sum(1 for _ in merged.open(encoding="utf-8"))
    n_distill = sum(1 for _ in distill.open(encoding="utf-8"))
    metrics = json.loads(metrics_p.read_text())
    exact, three_vote, agreement = AUDIT[tag]

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
                  "byt5-g2p-multilingual (small+tiny agreement)")
        notice = (f"voicegarden-lexicons {tag} (expanded)\n"
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
        "audit_exact": exact,
        "three_vote_filtered": three_vote,
        "license": "MIT",
        "source": source,
        "phonetisaurus": metrics,
        "file": f"{tag}.tar.gz",
        "sha256": sha256(tar_path),
        "size_bytes": tar_path.stat().st_size,
        "format": "floravox-fst-lexicon/1",
        "version": "expanded-v1",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="dist/expanded")
    args = ap.parse_args()
    out = REPO / args.out
    out.mkdir(parents=True, exist_ok=True)

    manifest = {"version": "expanded-v1",
                "format": "voicegarden-lexicons-expanded/1",
                "languages": []}
    for tag in AUDIT:
        print(f"== {tag}")
        entry = build(tag, out)
        if entry:
            manifest["languages"].append(entry)
            print(f"  {entry['entries']:,} entries "
                  f"({entry['entries_distilled']:,} distilled), "
                  f"{entry['size_bytes']:,} bytes")
    (out / "expanded.json").write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"manifest: {out / 'expanded.json'} ({len(manifest['languages'])} languages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
