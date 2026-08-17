# Test fixtures

## `scoring_parity.json`

Golden scoring outputs captured from the production reading-bot **before** the
2.0.0 refactor, and the gate that refactor has to pass.

**Why it exists.** A scoring regression is invisible. Wrong points render exactly
like right points — no error, no crash, just a child's reading quietly worth more
or less than it was yesterday. Nothing else in the suite catches that.

**How it was produced.** Every logged reading session was replayed through the
frozen pre-refactor scorer and its output recorded verbatim. The recomputed
values matched the values stored in the database exactly, with zero drift, so
this is a true baseline rather than an approximation.

**What's in it.** 90 cases — 80 real sessions plus 10 synthetic. The synthetic
ones exist because real usage never exercised audiobooks (the ×0.25 rule),
`dense_middle_grade`, or `graphic_novel_telgemeier`. They're scored through the
same frozen code, so they're genuine parity cases rather than guesses at intent.
Between them the cases cover every Lexile tier, all four illustrated-format
bypasses, and the per-book `{reader}_ppp_override` path.

**Privacy.** The fixture is deliberately safe for a public repo. Reader keys are
mapped to the sample family (`alex`, `sam`) and session dates are dropped, so it
captures the whole scoring surface without publishing which child read what and
when. Per-book override keys are remapped to match.

**Each case embeds its own book record.** Parity deliberately does *not* look
books up in `books.json`. The catalog is expected to change — Lexile corrections,
reclassifications, bulk series imports — and a catalog edit must never turn the
scoring gate red on its own. The embedded snapshot carries only the fields that
influence a score. It also keeps the fixture self-contained: one case references
a book added at runtime via `/book`, which lives in the database and has never
been in `books.json`.

**Regenerating.** Use `gen_parity_fixture.py`, which lives with the private
config repo — it reads the production database and must never be added here.
Regenerate only when you intend to move the baseline, and say so explicitly:
silently re-recording it defeats the entire purpose.
