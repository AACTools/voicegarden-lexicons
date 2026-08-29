# Quarantined 10 files

These languages were distilled with tags that are NOT in langs.json
(the trained tag set): the models never saw them, so the outputs are
unvalidated and must not be compiled into FST lexicons.

Correct fix: train these languages (staging data exists for some) or
map to a trained tag only after per-language validation.
