#!/usr/bin/env python3
"""Release the P2P convention pair tables for sherpa-onnx 2.x.

Repackages the existing `en` and `eng-US` bundles with `p2p-misaki.tsv`
and `p2p-espeak.tsv` added beside `lexicon.txt`, updates both manifests
(`lexicons.json`, `expanded.json`) with new hashes/versions, and stages
every asset needed for a complete GitHub release (all bundles must be
re-uploaded: the client downloads `{base}/{file}` from the LATEST
release, so a partial upload breaks the other languages).

Run AFTER `build_p2p_pairs.py` has produced staging/p2p-*.tsv.

Usage:
  release_p2p_pairs.py --out dist-v0.3.1 --version v0.3.1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
RELEASE_BASE = "https://github.com/AACTools/voicegarden-lexicons/releases/download"
OLD_TAG = "v0.2.1"      # 13 gruut languages + en + eng-US
ENGB_TAG = "v0.3.0"     # en-GB + lexicons.json

PAIRS_NOTICE = """
P2P convention pairs (sherpa-onnx 2.x espeak-orphaned models)
p2p-misaki.tsv: gruut eng-US (MIT) aligned with the kokoro multi-lang
  bundled lexicon-us-en.txt (Apache-2.0). Misaki convention (kokoro-en,
  kitten): uppercase diphthongs A I O W Y, ligature affricates, split
  rhotics. Built by scripts/build_p2p_pairs.py misaki.
p2p-espeak.tsv: gruut eng-US (MIT) aligned with CMUDict
  (BSD-2-Clause-like) converted ARPABET→IPA in the piper/espeak
  convention: decomposed diphthongs, ɚ/ˈɜɹ rhotic split, function-word
  destressing. Built by scripts/build_p2p_pairs.py espeak.
Format: gruut|ph1|ph2<TAB>target ph ph (first occurrence wins on
duplicate sequences). Consumed by rust-tts-wrapper's sherpa engine
(auto lexicon generation for espeak-orphaned models, tracking issue
AACTools/rust-tts-wrapper#66).
Validated: whisper-small round-trip word-identical to the espeak
reference on piper-en_US-amy-low; 99.1% of table lookups byte-identical
to the kokoro bundled lexicon on overlap words.
"""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path) -> None:
    print(f"  download {url}")
    with urllib.request.urlopen(url, timeout=120) as r, dest.open("wb") as f:
        shutil.copyfileobj(r, f)


def validate_bundle(path: Path) -> None:
    """A downloaded bundle must open as a tar and carry a lexicon.txt
    before its sha is blessed into the manifest — a truncated download
    would otherwise pass the client's checksum and fail at extraction."""
    with tarfile.open(path, "r:gz") as tar:
        names = tar.getnames()
    if "lexicon.txt" not in names:
        raise SystemExit(f"{path.name}: no lexicon.txt — corrupt download?")


def repackage(tar_path: Path, out: Path, pairs: list[Path]) -> dict:
    """Extract bundle, add pairs + NOTICE section, re-tar with the same
    layout (files at the archive root).

    Deterministic output: zeroed mtimes in both the tar members and the
    gzip header, so re-running the script reproduces identical bytes
    (the stale-sha mess in the old manifests traces back to
    non-reproducible tars).
    """
    import gzip
    import io
    import time

    with tempfile.TemporaryDirectory() as td:  # noqa: SIM115
        td = Path(td)
        with tarfile.open(tar_path, "r:gz") as tar:
            tar.extractall(td, filter="data")
        for p in pairs:
            shutil.copyfile(p, td / p.name)
        notice = td / "NOTICE"
        notice.write_text(notice.read_text() + PAIRS_NOTICE, encoding="utf-8")
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            for f in sorted(td.iterdir()):
                info = tar.gettarinfo(str(f), arcname=f.name)
                info.mtime = 0
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                with f.open("rb") as fh:
                    tar.addfile(info, fh)
        with gzip.GzipFile(filename="", mode="wb", fileobj=out.open("wb"),
                           mtime=0) as gz:
            gz.write(buf.getvalue())
    return {"sha256": sha256(out), "size_bytes": out.stat().st_size}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    pairs = [ROOT / "staging" / "p2p-misaki.tsv", ROOT / "staging" / "p2p-espeak.tsv"]
    for p in pairs:
        if not p.is_file():
            raise SystemExit(f"missing {p} — run build_p2p_pairs.py first")

    # ── repackage en + eng-US with the pairs ──
    updated: dict[str, dict] = {}
    downloads = tempfile.mkdtemp(prefix="vgl-release-")
    for lang in ("en", "eng-US"):
        print(f"== {lang}")
        old = Path(downloads) / f"{lang}.tar.gz"
        download(f"{RELEASE_BASE}/{OLD_TAG}/{lang}.tar.gz", old)
        validate_bundle(old)
        new = out / f"{lang}.tar.gz"
        meta = repackage(old, new, pairs)
        updated[lang] = meta
        print(f"  {new.name}: {meta['size_bytes']} bytes sha {meta['sha256'][:16]}…")

    # ── fetch the manifests and update the two entries ──
    print("== manifests")
    lex = out / "lexicons.json"
    download(f"{RELEASE_BASE}/{ENGB_TAG}/lexicons.json", lex)
    manifest = json.loads(lex.read_text())
    manifest["version"] = args.version
    for e in manifest["languages"]:
        if e["lang"] == "en":
            e.update(updated["en"], version=args.version)
            e["source"] = "PyPI:gruut + CMUDict/kokoro P2P pairs"
            e["license"] = ("MIT; pairs: MIT (gruut) + Apache-2.0 (kokoro) "
                            "+ BSD-2-Clause (CMUDict)")

    exp = out / "expanded.json"
    download(f"{RELEASE_BASE}/{OLD_TAG}/expanded.json", exp)
    manifest2 = json.loads(exp.read_text())
    manifest2["version"] = f"expanded-v3-{args.version}"
    for e in manifest2["languages"]:
        if e["lang"] == "eng-US":
            e.update(updated["eng-US"], version=args.version)
            e["source"] = "gruut/wikipron expanded + CMUDict/kokoro P2P pairs"
            e["license"] = ("MIT/CC-BY-SA-4.0; pairs: MIT (gruut) + "
                            "Apache-2.0 (kokoro) + BSD-2-Clause (CMUDict)")

    # ── fetch every unchanged bundle so the release is complete ──
    # NOTE: the v0.2.1/v0.3.0 manifests' sha256 values do not match the
    # downloadable bytes for several bundles — the client's fetch()
    # checksum would fail for those languages today. This release
    # rewrites every entry's sha to the ACTUAL bytes uploaded here,
    # making the manifest self-consistent.
    print("== unchanged bundles (release must be complete)")
    for entry in manifest["languages"]:
        if entry["lang"] == "en":
            continue  # repackaged above
        dest = out / entry["file"]
        if not dest.exists():
            tag = ENGB_TAG if entry["lang"] == "en-GB" else OLD_TAG
            download(f"{RELEASE_BASE}/{tag}/{entry['file']}", dest)
        validate_bundle(dest)
        actual = sha256(dest)
        if actual != entry["sha256"]:
            print(f"  {entry['lang']}: sha corrected (stale in old manifest)")
            entry["sha256"] = actual
            entry["size_bytes"] = dest.stat().st_size
    for entry in manifest2["languages"]:
        if entry["lang"] == "eng-US":
            continue  # repackaged above
        dest = out / entry["file"]
        if not dest.exists():
            download(f"{RELEASE_BASE}/{OLD_TAG}/{entry['file']}", dest)
        validate_bundle(dest)
        actual = sha256(dest)
        if actual != entry["sha256"]:
            print(f"  {entry['lang']}: sha corrected (stale in old manifest)")
            entry["sha256"] = actual
            entry["size_bytes"] = dest.stat().st_size

    # manifests were updated in memory — write after all corrections
    lex.write_text(json.dumps(manifest, indent=2) + "\n")
    exp.write_text(json.dumps(manifest2, indent=2) + "\n")

    shutil.rmtree(downloads, ignore_errors=True)
    n = len(list(out.glob("*.tar.gz"))) + len(list(out.glob("*.json")))
    print(f"\nstaged {n} release assets in {out}")
    print(f"next: gh release create {args.version} {out}/* --title ... -R AACTools/voicegarden-lexicons")


if __name__ == "__main__":
    main()
