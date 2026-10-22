# Instructions for coding agents

This folder is a self-contained tool. `quote_context.py` adds bracketed
editorial context to quotes that lack it. Read `README.md` first.

When asked to run it on a new dataset:

1. Map the user's data onto the two inputs. Quotes go in a CSV with `doc_id`
   and `direct_quote` (optional: `quote_id`, `speaker`, `organisation`, `date`).
   Documents go in JSONL or CSV with `doc_id`, `title` and `text`. Write a small
   conversion script rather than editing `quote_context.py` to read a new
   format.
2. If the quotes are not official policy statements, adapt the example lists
   in `TRIAGE_SYSTEM` and `RESOLVE_SYSTEM` to the domain. When you do, bump the
   matching `*_PROMPT_VERSION`.
3. Do not loosen `build_quote_in_context`. Its checks are what make the output
   trustworthy:
   - the anchor occurs exactly once in the quote
   - the evidence is verbatim in the document
   - the round-trip leaves `direct_quote` unchanged
   - insertions are limited to 12 words each and 3 per quote

   If many rows fail one check, report the counts and examples. Do not relax the
   check.
4. Run `python -m unittest test_quote_context.py` after any change.
5. Run on a sample of about 50 quotes first. Report the `final_status` counts
   and show some `resolved` rows, alongside their evidence, for a human to
   check before the full run.

Never write to `direct_quote`. Never let the model rewrite a quote. All output
goes in `quote_in_context`.
