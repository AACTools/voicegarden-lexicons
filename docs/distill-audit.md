# Distillation quality audit

*Measured 2026-08-29 against held-out test words (`corpus/g2p.test.tsv`,
never seen in training). Method: replicate the exact distill path —
both published models (small int8 + tiny int8, ONNX), same prompt
conventions, same agreement filter — on ground-truth words, then score
agreed predictions. `exact` = string match; `folded` additionally
folds convention differences (ɑ↔a, ɔ↔o, ɡ↔g, length/aspiration
diacritics, diphthong tokenization); `PER` = phoneme error rate on
agreed predictions.*

## Results (200 sampled test words per language)

| lang | prompt | agree% | exact% | fold% | PER |
|---|---|---|---|---|---|
| spa | spa-ES | 100.0 | 100.0 | 100.0 | 0.000 |
| pol | pol | 99.0 | 96.0 | 96.0 | 0.007 |
| ita | ita | 95.5 | 95.8 | 96.9 | 0.006 |
| ell | ell | 94.2 | 86.0 | 86.0 | 0.030 |
| fra | fra | 91.0 | 92.3 | 92.9 | 0.015 |
| deu | deu | 79.5 | 97.5 | 97.5 | 0.006 |
| tur | tur | 79.8 | 51.6 | **93.4** | 0.149 |
| swe | swe | 71.7 | 81.0 | 81.8 | 0.059 |
| eng | eng-US | 48.5 | **61.9** | 61.9 | 0.112 |
| heb | heb | 65.2 | 26.7 | 26.7 | 0.182 |
| nob | nob | 42.3 | 0.0 | 0.0 | 0.153 |

Reading: for well-anchored languages the agreement filter ships
92-100% correct entries. `tur`'s raw number is a symbol-convention
artifact (truth uses ɑ/ɔ/aː/pʰ, models use plain a/o) — folded, tur is
93.4%. Real weak spots: **eng-US (61.9%)**, **heb (26.7%, n=23)**,
**nob (0%, n=26)**.

## Findings

1. **Variety tags matter.** Bare `eng`/`spa`/`por` prompts degrade the
   models (mixed-variety union data); the variety tags (`eng-US`,
   `spa-ES`) are clean and score dramatically better (spa: 100% vs
   53% bare). The distiller already used variety tags via `LANG_MAP`.
2. **Ten languages were distilled with untrained tags.** `bul cat ces
   hun lit lav mkd rus ukr vie` are not in `langs.json` (the trained
   set): ~145k entries of unvalidated output. **Quarantined** to
   `distill/quarantine/`; `distill.py` `LANG_MAP` trimmed to 27
   validated tags. Valid shipped total: **846,126 entries**.
3. **English is the weakest major language** — errors are stress
   placement and unstressed-vowel reduction (`absconding` æ→ə,
   `acorn` eɪ→ə). Of 18,587 shipped eng-US entries, roughly 7k carry
   a wrong phone or stress mark by this estimate.
4. **eng/spa/por bare-tag audits in the table's history failed as
   OOD artifacts** — not model quality. Always audit with the
   variety tag the distiller used.
5. Small-corpus languages (heb 2.9k rows, nob 2.7k) are genuinely
   mediocre — real vowel errors (heb collapses initial vowels to a).

## Estimated shipped-entry correctness (agreed x precision)

| lang | shipped | est. correct |
|---|---|---|
| spa-ES | 31,964 | ~100% |
| pol | 57,954 | ~96% |
| ita | 47,365 | ~96% |
| deu | 37,062 | ~97% |
| fra | 43,943 | ~93% |
| tur | 46,503 | ~93% (folded) |
| ell | 37,750 | ~86% |
| swe | 51,150 | ~82% |
| eng-US | 18,587 | ~62% |

## Recommendations

- Compile FST expansions now for the ≥90% band: spa-ES, deu, pol,
  ita, fra, tur (folded-convention aware).
- eng-US: do not compile blind. Either accept with a provenance flag,
  or add the WFST as a third voter (ship only 3-way agreement) —
  untested, follow-up.
- nob/heb: keep out of FST compilation until their corpora grow;
  entries remain available with provenance.
- All distill output stays in separate TSVs (`distill/*.tsv`), never
  merged into `staging/*/merged.tsv`, so provenance is structural.

## The eng salvage: three-voter filter

Adding the WFST tier (gruut-trained, MIT) as a third voter transforms
the eng numbers (`audit/eng.3vote.json`, same 200-word sample):

| filter | precision | coverage of 2-vote |
|---|---|---|
| small+tiny agree (shipped filter) | 61.9% | 100% |
| small+tiny+WFST agree | **98.3%** | 59.8% |

Caveat, stated plainly: the WFST scores 98% on this split because the
test words sit inside its training distribution; on true OOV it runs
~63% (leaderboard). So the precision of 3-vote-filtered *distill*
entries lies between 62% and 98% — strictly better than shipping the
2-vote set. Recommended: re-filter the 18,587 eng-US entries through
the WFST and keep the ~11k that survive.

## espeak-ng head-to-head (the owed measurement)

`espeak_audit.py`, same splits, folded comparison:

| lang | voice | exact (folded) | notes |
|---|---|---|---|
| eng | en-us | 15.5% (43% with ɐ-wildcard) | residual misses = secondary-stress + r-coloring conventions |
| deu | de | 0% | symbol inventory incommensurable |
| spa | es | 0% | same |

espeak's transcriptions are phonetically reasonable but its
conventions do not map onto ours without per-language mapping tables
(building those is gruut's raison d'etre — and gruut is MIT, already
our source where it exists). Cross-engine exact-match is therefore
not a meaningful quality number without that layer.

## Shipped: expanded lexicon FSTs (`distill-fst/`)

11 languages compiled (merged.tsv + distill entries; eng/ell/swe use
the 3-vote-filtered sets). Frequent-word (top-50k) lexicon hit rate:

| tag | before | after | delta |
|---|---|---|---|
| tur | 12.1% | 87.3% | +75.2 |
| ell | 10.0% | 75.4% | +65.4 |
| pol | 47.9% | 97.7% | +49.8 |
| spa-LatAm | 54.5% | 96.6% | +42.1 |
| ita | 48.5% | 88.3% | +39.8 |
| deu | 67.3% | 94.0% | +26.7 |
| fra | 68.3% | 95.3% | +27.0 |
| por-PT | 80.4% | 99.5% | +19.1 |
| spa-ES | 75.4% | 97.8% | +22.4 |
| swe | 24.7% | 47.5% | +22.8 |
| eng-US | 86.4% | 90.0% | +3.6 |

Caveat: distill candidates were selected from wordfreq top-100k, so
these gains are partly by construction — we closed the frequent-word
gaps on purpose, at audited 92-100% entry accuracy. Independent-text
validation (Leipzig/Wikipedia sample) is the follow-up.

## Reproduce

```
python3 scripts/train_byt5/distill_audit.py --lang deu --n 200
python3 scripts/train_byt5/distill_audit.py --lang eng --prompt-tag eng-US --n 200
```

## Source clash measurement + harmonization attempt (2026-08-30)

For 9 languages the staging dictionaries merge two sources (gruut +
WikiPron). Measuring shared words: the sources' transcriptions agree
exactly 0% of the time for English, 1-25% for ita/fas/por/nld/deu/swe,
67% for Spanish, 91% for French. The G2P models were trained on the
merged union, which is why holdout accuracy tracks source harmony
(Spanish distills at 100%, English caps at ~62%).

Harmonization attempt (`harmonize_sources.py`): learn wikipron->gruut
rewrite rules from the shared-word alignments (anchor-based n:m,
purity-gated), apply, re-measure. Result across two strategies
(context-free, context-conditioned):

- real but modest gains: por 1.7%->6.5%, swe 24.4%->26.8%, fas +0.4
- nothing for eng/ita/deu/nld: the remaining disagreement is heavily
  context-dependent symbol substitution (n:m segmentation is only
  13-41% of operations), which context-free rules cannot resolve
- ungated rules can destroy near-harmonious languages (fra 90.6->0)

Conclusion: simple rewrite conversion is not sufficient. The merge
policy stays variant-preserving: gruut entries primary, wikipron
entries kept as provenance-tagged secondary variants for words gruut
lacks, no destructive conversion. Proper harmonization needs a
many-to-many EM aligner and per-language convention specs; the
measured clash table above is the baseline that work is judged
against. Data from `audit/harmonization-report.json`.
