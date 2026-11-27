#!/usr/bin/env python3
"""P2G round-trip harness: does G2P(P2G(ipa)) give back the same IPA?

The respeller tier (rust-tts-wrapper #109) turns a phoneme string into a
spelling an engine can read. Its quality gate is the round trip: take a
held-out (word, IPA) pair, respell the IPA with the P2G model, re-pronounce
the respelling with the matching G2P model, and check whether the
pronunciation survived. Per language, over a sample of the training
corpus's test split (corpus/p2g.test.tsv: lang, IPA, word):

- p2g_exact  the respelling equals the original spelling (orthographic
             round trip — stricter than needed: any homophone respelling
             is fine for TTS, this measures fidelity to the corpus)
- rt_exact   G2P(respelling) == the original IPA  (the #109 gate)
- rt_per     phone error rate of G2P(respelling) against the original
             IPA (how far the misses land)
- rt_lenient round-trip equality ignoring stress marks and syllable
             boundaries (separates prosody-notation noise — e.g. a
             swapped ˈ/ˌ — from actual sound changes)
- respell_in_charset  fraction of respellings spelled only with letters
             attested in that language's own corpus spellings: a
             respelling must be readable by an ordinary orthographic
             engine, not a phoneme string in disguise that only our own
             G2P could map back
- broken     the gate: the respelling is neither the original word (a
             safe no-op an engine pronounces natively) nor a verified
             homophone — i.e. the respeller changed the pronunciation

Spellings compare case-insensitively (many test rows are capitalised
proper nouns).

Sibling leakage: the training corpus is split into alphabetical word
families (families sharing their first letters stay together), yet about
44% of test words still have an edit-distance-1 neighbour in TRAIN —
about what the old alphabetical head slice had (40%), against 74% for a
per-word random split. In a 100k-word dictionary most words have SOME
one-letter neighbour whatever the split, so this is not mostly
cat/cats, but such words are easier than isolated ones. With
--train-split (default: corpus/p2g.train.tsv) every language is scored
twice — on all its test rows and on those without a train neighbour —
and both are reported.

Split history: the v2 models' published baseline (results/p2g-roundtrip-
*.json of 2026-11-26) was measured on the ORIGINAL split, an
alphabetical head slice per language (97-100% of English/German test
words began with "a", Hungarian's were suffix entries only). That split
is no longer in corpus/; the v2 numbers are not comparable with runs on
the family split, and v2 itself must not be re-scored on it — v2 trained
on those rows.

Rows for bound morphemes (spelling starts or ends with "-", e.g.
Hungarian "-edzik") are excluded: they are not words a respeller handles.
All comparisons are NFC-normalised.

Inference follows scripts/train_byt5/onnx_reference.py's conventions
(byte+3 ids, EOS appended to the encoder input, "<lang>:" tag, the
length-2 decoder bootstrap under mask [1, 0]); --selftest proves the
batched decoder here against that single-sequence reference before any
number is reported.

Models: HF willwade/byt5-{p2g,g2p}-multilingual[-tiny], `onnx/` dirs
(fp32 = the v2 models; onnx-int8 is the v1 quantisation):

  for m in p2g-multilingual g2p-multilingual; do
    hf download willwade/byt5-$m --include 'onnx/*.onnx' --local-dir onnx-models/$m
  done

Usage:
  scripts/p2g_roundtrip.py --models onnx-models --sizes tiny,small --sample 200
  scripts/p2g_roundtrip.py --selftest 20 --sizes tiny      # decoder parity only
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import sys
import unicodedata
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import onnxruntime as ort

REPO = Path(__file__).resolve().parent.parent
EOS = 1
PAD = 0
MAX_INPUT = 127  # leave room for EOS
MAX_GEN = 64
SUFFIX = {"small": "", "tiny": "-tiny"}
# try a few known spellings per language in the self-test
SELFTEST = {
    "eng": "w ɜː l d", "deu": "v ɛː l t", "fra": "b ɔ̃ ʒ u ʁ",
    "spa": "ɡ a t o", "cmn": "n ɪ˧˥ x a ʊ˥˩", "cym": "ɪ ɐ ɡ ɔ r",
}


class Byt5:
    """Batched greedy inference over an exported ONNX dir (see module
    docstring for the conventions)."""

    def __init__(self, dirname: Path, threads: int, provider: str = "cpu") -> None:
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        so.inter_op_num_threads = 1
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        if provider == "cuda":
            prov = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        else:
            prov = ["CPUExecutionProvider"]
        self.enc = ort.InferenceSession(str(dirname / "encoder_model.onnx"), so, providers=prov)
        self.dec = ort.InferenceSession(str(dirname / "decoder_model.onnx"), so, providers=prov)
        names = {i.name for i in self.dec.get_inputs()}
        self.key = "input_ids" if "input_ids" in names else "decoder_input_ids"
        self.names = names

    def encode(self, texts: list[str]):
        seqs = [[b + 3 for b in t.encode("utf-8")][:MAX_INPUT] + [EOS] for t in texts]
        width = max(len(s) for s in seqs)
        ids = np.full((len(seqs), width), PAD, dtype=np.int64)
        mask = np.zeros((len(seqs), width), dtype=np.int64)
        for i, s in enumerate(seqs):
            ids[i, : len(s)] = s
            mask[i, : len(s)] = 1
        return self.enc.run(None, {"input_ids": ids, "attention_mask": mask})[0], ids, mask

    def decode_step(self, dec_ids, dec_mask, hidden, enc_mask):
        feeds = {self.key: dec_ids}
        if "attention_mask" in self.names:
            feeds["attention_mask"] = dec_mask
        if "encoder_hidden_states" in self.names:
            feeds["encoder_hidden_states"] = hidden
        if "encoder_attention_mask" in self.names:
            feeds["encoder_attention_mask"] = enc_mask
        return self.dec.run(None, feeds)[0]

    def generate(self, texts: list[str]) -> list[str]:
        if not texts:
            return []
        hidden, _ids, mask = self.encode(texts)
        n = len(texts)
        # length-2 bootstrap under mask [1, 0]: the true first decoder step
        dec_ids = np.zeros((n, 2), dtype=np.int64)
        dec_mask = np.array([[1, 0]] * n, dtype=np.int64)
        out = [bytearray() for _ in range(n)]
        done = np.zeros(n, dtype=bool)
        for _ in range(MAX_GEN):
            logits = self.decode_step(dec_ids, dec_mask, hidden, mask)
            nxt = logits[:, -1, :].argmax(axis=-1)
            for i in range(n):
                if not done[i]:
                    tok = int(nxt[i])
                    if tok == EOS:
                        done[i] = True
                    else:
                        out[i].append(tok - 3)
            if done.all():
                break
            # finished rows keep receiving (masked-out) pad: rows are
            # independent, so nothing leaks into unfinished ones
            step = np.where(done, PAD, nxt).reshape(n, 1).astype(np.int64)
            dec_ids = np.concatenate([dec_ids, step], axis=1)
            dec_mask = np.concatenate(
                [dec_mask, (~done).reshape(n, 1).astype(np.int64)], axis=1)
        return [o.decode("utf-8", "replace") for o in out]

    def reference(self, text: str) -> str:
        """The single-sequence path from onnx_reference.py, verbatim in
        spirit — the oracle for --selftest."""
        ids = [b + 3 for b in text.encode("utf-8")][:MAX_INPUT] + [EOS]
        inp = np.array([ids], dtype=np.int64)
        mask = np.ones_like(inp)
        hidden = self.enc.run(None, {"input_ids": inp, "attention_mask": mask})[0]
        dec_ids = np.zeros((1, 2), dtype=np.int64)
        dec_mask = np.array([[1, 0]], dtype=np.int64)
        out = bytearray()
        for _ in range(MAX_GEN):
            logits = self.decode_step(dec_ids, dec_mask, hidden, mask)
            nxt = int(np.argmax(logits[0, -1]))
            if nxt == EOS:
                break
            out.append(nxt - 3)
            dec_ids = np.concatenate(
                [dec_ids, np.array([[nxt]], dtype=np.int64)], axis=1)
            dec_mask = np.concatenate(
                [dec_mask, np.ones((1, 1), dtype=np.int64)], axis=1)
        return out.decode("utf-8", "replace")


def edit_distance(a: list[str], b: list[str]) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[-1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


PROSODY = set("\u02c8\u02cc.\u2016")  # ˈ ˌ . ‖


def lenient(phones: str) -> list[str]:
    return [t for t in (unicodedata.normalize("NFC", x) for x in phones.split())
            if t.strip("".join(PROSODY))]


def strict(phones: str) -> list[str]:
    return [unicodedata.normalize("NFC", x) for x in phones.split()]


def letters(text: str) -> set[str]:
    return {c for c in unicodedata.normalize("NFC", text)
            if unicodedata.category(c).startswith("L")}


def same_word(a: str, b: str) -> bool:
    return " ".join(unicodedata.normalize("NFC", a).casefold().split()) == \
        " ".join(unicodedata.normalize("NFC", b).casefold().split())


def load_charsets() -> dict[str, set[str]]:
    """Letters attested in each language's spellings across the whole
    TRAIN split (the test split's alphabetical head slice is far too
    narrow to define an orthography). Cached in corpus/charsets.json."""
    cache = REPO / "corpus" / "charsets.json"
    if cache.exists():
        return {k: set(v) for k, v in json.loads(cache.read_text()).items()}
    train = REPO / "corpus" / "p2g.train.tsv"
    out: dict[str, set[str]] = defaultdict(set)
    if train.exists():
        with train.open(encoding="utf-8") as f:
            for line in f:
                lang, _ipa, word = line.rstrip("\n").split("\t")[:3]
                out[lang] |= letters(word)
        cache.write_text(json.dumps({k: sorted(v) for k, v in out.items()}),
                         encoding="utf-8")
    return out


def has_train_sibling(word: str, train: set[str], alphabet: frozenset[str]) -> bool:
    """True if an edit-distance-1 variant of `word` is in `train`."""
    if len(word) > 1 and any(word[:i] + word[i + 1:] in train for i in range(len(word))):
        return True
    for i in range(len(word) + 1):
        pre, suf = word[:i], word[i:]
        if i < len(word) and any(pre + c + suf[1:] in train for c in alphabet):
            return True
        if any(pre + c + suf in train for c in alphabet):
            return True
    return False


def load_train_words(path: Path) -> dict[str, tuple[set[str], frozenset[str]]]:
    """lang -> (train word set, letter alphabet) for the leak check."""
    words: dict[str, set[str]] = defaultdict(set)
    with path.open(encoding="utf-8") as f:
        for line in f:
            lang, _ipa, word = line.rstrip("\n").split("\t")[:3]
            words[lang].add(unicodedata.normalize("NFC", word).casefold())
    return {k: (v, frozenset(c for w in v for c in w if unicodedata.category(c)[0] == "L"))
            for k, v in words.items()}


def load_split(path: Path) -> dict[str, list[tuple[str, str]]]:
    """lang -> [(word, ipa), ...] from the corpus test split."""
    by_lang: dict[str, list[tuple[str, str]]] = defaultdict(list)
    with path.open(encoding="utf-8") as f:
        for line in f:
            lang, ipa, word = line.rstrip("\n").split("\t")[:3]
            if word.startswith("-") or word.endswith("-"):
                continue  # bound morpheme, not a word
            by_lang[lang].append((word, ipa))
    return by_lang


def model_dir(models: Path, task: str, size: str) -> Path:
    return models / f"{task}-multilingual{SUFFIX[size]}" / "onnx"


def selftest(models: Path, size: str, n: int, threads: int, provider: str) -> int:
    """Batched decoder must agree with the single-sequence reference."""
    p2g = Byt5(model_dir(models, "p2g", size), threads, provider)
    g2p = Byt5(model_dir(models, "g2p", size), threads, provider)
    split = load_split(REPO / "corpus" / "p2g.test.tsv")
    rng = random.Random(13)
    cases: list[str] = []
    for lang, phones in SELFTEST.items():
        cases.append(f"<{lang}>: {phones}")
    pool = [(l, w) for l, rows in split.items() for w, _ in rng.sample(rows, min(3, len(rows)))]
    for lang, word in rng.sample(pool, min(n, len(pool))):
        cases.append(f"<{lang}>: {word}")
    bad = 0
    for model, tag in ((p2g, "p2g"), (g2p, "g2p")):
        batched = model.generate(cases)
        for text, got in zip(cases, batched):
            want = model.reference(text)
            if got != want:
                bad += 1
                print(f"MISMATCH {tag} {text!r}: batched={got!r} reference={want!r}",
                      file=sys.stderr)
    if bad:
        print(f"selftest FAILED: {bad} mismatches", file=sys.stderr)
        return 1
    print(f"selftest OK: {len(cases)} inputs x 2 models agree with onnx_reference")
    return 0


MIN_N = 100  # below this, a per-language number is too noisy to gate on


def summarise(lang: str, n: int, same: list[bool], rt: list[bool], lenient_ok: list[bool],
              charset_ok: list[bool], per: list[float], source: str | None = None) -> dict:
    homophone = sum(r and not s_ for r, s_ in zip(rt, same))
    broken = sum(not r and not s_ for r, s_ in zip(rt, same))
    res = {
        "lang": lang, "n": n,
        "same_word": round(sum(same) / n, 4),
        "rt_exact": round(sum(rt) / n, 4),             # G2P(P2G(ipa)) == ipa
        "homophone_ok": round(homophone / n, 4),       # a different spelling, verified
        "broken": round(broken / n, 4),                # neither the word nor a homophone
        "rt_lenient": round(sum(lenient_ok) / n, 4),
        "rt_per": round(sum(per) / n, 4),
        "respell_in_charset": round(sum(charset_ok) / n, 4),
    }
    if source:
        res["source"] = source
    return res


def score(lang: str, rows: list[tuple[str, str]], charset: set[str],
          run, p2g: Byt5, g2p: Byt5, train: tuple[set[str], frozenset[str]] | None = None,
          source: str | None = None) -> dict:
    resp = [r.strip() for r in run(p2g, [f"<{lang}>: {ipa}" for _w, ipa in rows])]
    back = run(g2p, [f"<{lang}>: {r}" for r in resp])
    same, rt, len_ok, cs_ok, per = [], [], [], [], []
    for (word, ipa), r, b in zip(rows, resp, back):
        is_same = same_word(r, word)
        round_trips = strict(b) == strict(ipa)
        same.append(is_same)
        rt.append(round_trips)
        len_ok.append(lenient(ipa) == lenient(b))
        cs_ok.append(letters(r) <= charset)
        per.append(0.0 if round_trips else
                   edit_distance(strict(b), strict(ipa)) / max(len(strict(ipa)), 1))
    n = len(rows)
    res = summarise(lang, n, same, rt, len_ok, cs_ok, per, source)
    label = f"post-v2 {lang}" if source else lang
    line = (f"  {label:<12} n={n:<4} same {res['same_word']:6.1%}  homophone "
            f"{res['homophone_ok']:6.1%}  broken {res['broken']:6.1%}  "
            f"(rt_exact {res['rt_exact']:6.1%}, lenient {res['rt_lenient']:6.1%})  "
            f"PER {res['rt_per']:6.1%}  in-charset {res['respell_in_charset']:6.1%}")
    if train is not None:
        train_words, alphabet = train
        leak = [has_train_sibling(unicodedata.normalize("NFC", w).casefold(), train_words, alphabet)
                for w, _ipa in rows]
        keep = [i for i, leaked in enumerate(leak) if not leaked]
        res["train_sibling"] = round(sum(leak) / n, 4)
        if keep:
            sub = lambda col: [col[i] for i in keep]  # noqa: E731
            lf = summarise(lang, len(keep), sub(same), sub(rt), sub(len_ok), sub(cs_ok), sub(per))
            res["leak_free"] = {k: lf[k] for k in ("n", "same_word", "rt_exact", "homophone_ok",
                                                   "broken", "rt_lenient", "rt_per")}
            line += (f"  | train-sibling {res['train_sibling']:4.1%}, leak-free n={len(keep)} "
                     f"broken {lf['broken']:6.1%}")
    print(line, file=sys.stderr)
    return res


MIN_N = 100  # below this, a per-language number is too noisy to gate on


def evaluate(models: Path, size: str, langs: list[str] | None, sample: int,
             batch: int, threads: int, out: Path | None, provider: str,
             extra: dict[str, Path], train_split: str | None = None) -> int:
    p2g = Byt5(model_dir(models, "p2g", size), threads, provider)
    g2p = Byt5(model_dir(models, "g2p", size), threads, provider)
    split = load_split(REPO / "corpus" / "p2g.test.tsv")
    charsets = load_charsets()
    train_path = Path(train_split) if train_split else REPO / "corpus" / "p2g.train.tsv"
    train_words = load_train_words(train_path) if train_path.exists() else {}
    targets = sorted(set(langs) | set(extra) if langs else set(split) | set(extra))
    rng = random.Random(13)

    def run(model: Byt5, texts: list[str]) -> list[str]:
        got: list[str] = []
        for i in range(0, len(texts), batch):
            got += model.generate(texts[i:i + batch])
        return got

    results = []
    post_v2 = []
    t0 = time.time()
    n_rows = 0
    for lang in targets:
        all_rows = split.get(lang, [])
        charset: set[str] = set()
        for w, _ipa in all_rows:
            charset |= letters(w)
        if all_rows:
            rows = rng.sample(all_rows, min(sample, len(all_rows)))
            n_rows += len(rows)
            res = score(lang, rows, charset | charsets.get(lang, set()), run, p2g, g2p,
                        train_words.get(lang))
            res["low_n"] = len(all_rows) < MIN_N
            results.append(res)
        if lang in extra:
            # rows added to the bundles AFTER the v2 models were trained:
            # genuinely held out even though they are not in the test split
            held = []
            seen_test = {w for w, _ in all_rows}
            for line in extra[lang].read_text(encoding="utf-8").splitlines():
                w, _, phones = line.partition("\t")
                w, phones = w.strip(), phones.strip()
                if w and phones and " " not in w and w not in seen_test \
                        and not (w.startswith("-") or w.endswith("-")):
                    held.append((w, phones))
            if not held:
                continue
            for w, _p in held:
                charset |= letters(w)
            held = rng.sample(held, min(sample, len(held)))
            print("  [post-v2 rows]", file=sys.stderr)
            res = score(lang, held, charset | charsets.get(lang, set()), run, p2g, g2p,
                        train_words.get(lang), source=str(extra[lang]))
            post_v2.append(res)

    keys = ("same_word", "rt_exact", "homophone_ok", "broken", "rt_lenient",
            "rt_per", "respell_in_charset")

    def macro(key: str) -> float:
        return round(sum(r[key] for r in results) / len(results), 4) if results else 0.0

    def micro(key: str) -> float:
        return round(sum(r[key] * r["n"] for r in results) / n_rows, 4) if n_rows else 0.0

    summary = {
        "models": {t: f"willwade/byt5-{t}-multilingual{SUFFIX[size]} (onnx/, fp32 = v2)"
                   for t in ("p2g", "g2p")},
        "split": "corpus/p2g.test.tsv (alphabetical word families assigned at "
                 "random; bound morphemes excluded; spellings compared "
                 "case-insensitively; leak_free = test rows without an "
                 "edit-distance-1 sibling in the train split)",
        "train_split": str(train_path) if train_words else None,
        "sample_per_language": sample,
        "date": dt.date.today().isoformat(),
        "rows": n_rows,
        "seconds": round(time.time() - t0, 1),
        "macro": {k: macro(k) for k in keys},
        "micro": {k: micro(k) for k in keys},
        "per_language": sorted(results, key=lambda r: (r["rt_exact"], r["lang"])),
        "low_n_languages": sorted(r["lang"] for r in results if r.get("low_n")),
        "no_clean_test_rows": sorted(set(targets) - {r["lang"] for r in results}),
        "post_v2_rows": sorted(post_v2, key=lambda r: (r["rt_exact"], r["lang"])),
    }
    print(f"\n{size}: {len(results)} languages, {n_rows:,} rows, "
          f"{summary['seconds']} s")
    def line(agg: str, label: str) -> None:
        m = summary[agg]
        print(f"{label}: same_word {m['same_word']:.1%}  homophone_ok "
              f"{m['homophone_ok']:.1%}  broken {m['broken']:.1%}  "
              f"(rt_exact {m['rt_exact']:.1%}, lenient {m['rt_lenient']:.1%})  "
              f"PER {m['rt_per']:.1%}  in-charset {m['respell_in_charset']:.1%}")

    line("macro", "macro")
    line("micro", "micro")
    lf = [r["leak_free"] for r in results if r.get("leak_free")]
    if lf:
        print(f"leak-free macro over {len(lf)} languages: same_word "
              f"{sum(x['same_word'] for x in lf) / len(lf):.1%}  homophone_ok "
              f"{sum(x['homophone_ok'] for x in lf) / len(lf):.1%}  broken "
              f"{sum(x['broken'] for x in lf) / len(lf):.1%}  (rt_exact "
              f"{sum(x['rt_exact'] for x in lf) / len(lf):.1%})")
    for r in summary["post_v2_rows"]:
        print(f"post-v2 {r['lang']:<8} n={r['n']:<4} same {r['same_word']:6.1%}  "
              f"homophone {r['homophone_ok']:6.1%}  broken {r['broken']:6.1%}  "
              f"in-charset {r['respell_in_charset']:6.1%}")
    if summary["no_clean_test_rows"]:
        print(f"no clean held-out rows: {', '.join(summary['no_clean_test_rows'])}")
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n",
                       encoding="utf-8")
        print(f"wrote {out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", type=Path, default=REPO / "onnx-models")
    ap.add_argument("--sizes", default="small",
                    help="comma-separated: small, tiny")
    ap.add_argument("--sample", type=int, default=200,
                    help="rows per language (capped by availability)")
    ap.add_argument("--langs", help="comma-separated corpus language tags")
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--threads", type=int, default=0,
                    help="onnxruntime intra-op threads (0 = all cores)")
    ap.add_argument("--extra", action="append", default=[], metavar="LANG=TSV",
                    help="extra held-out rows (word<TAB>phones) for LANG, e.g. "
                         "bundle rows added after the v2 models were trained; "
                         "repeatable")
    ap.add_argument("--train-split", help="train split for the sibling-leak check "
                    "(default corpus/p2g.train.tsv; pass an empty string to skip)")
    ap.add_argument("--provider", default="cpu", choices=("cpu", "cuda"),
                    help="cuda = CUDAExecutionProvider (rented GPU); the selftest "
                         "guards the batched decoder either way")
    ap.add_argument("--out", help="JSON path (default results/p2g-roundtrip-<size>.json)")
    ap.add_argument("--selftest", type=int, default=8, metavar="N",
                    help="check N sampled inputs against the reference decoder "
                         "before measuring (0 disables)")
    args = ap.parse_args()
    threads = args.threads  # 0 = onnxruntime default (all cores)
    sizes = [s.strip() for s in args.sizes.split(",") if s.strip()]
    langs = [s.strip() for s in args.langs.split(",")] if args.langs else None
    extra = {}
    for item in args.extra:
        tag, _, path = item.partition("=")
        extra[tag.strip()] = Path(path)

    rc = 0
    for size in sizes:
        if args.selftest:
            rc |= selftest(args.models, size, args.selftest, threads, args.provider)
    if rc or not sizes:
        return rc
    for size in sizes:
        out = Path(args.out) if args.out else REPO / f"results/p2g-roundtrip-{size}.json"
        rc |= evaluate(args.models, size, langs, args.sample, args.batch, threads,
                        out, args.provider, extra, args.train_split or None)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
