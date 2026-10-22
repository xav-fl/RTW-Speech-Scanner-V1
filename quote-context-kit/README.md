# quote-context-kit

Adds minimal bracketed context to quotes that can't be understood on their own,
using the source document each quote came from. Extracted from the EPS
(economic policy statements) pipeline's `context` stage, with the EPS-specific
plumbing removed.

```
before: Today's action not only reduces government bureaucracy, ...
after:  Today's action [standardizing grant and cooperative agreement requirements] not only reduces government bureaucracy, ...

before: That's why we stepped in to save British steel.
after:  [on the steel industry] That's why we stepped in to save British steel.
```

## How it works

1. **Triage** (model, batched, *no document*): flags quotes containing an
   unresolved reference ("this policy", "the program", a stray "it") or that
   open mid-argument ("That's why..."), and returns the exact phrases. The
   document and its title are withheld on purpose, so the model judges the quote
   as a reader will see it.
2. **Resolve** (model, one call per document): for each flagged quote, returns
   *insertions*, never a rewritten quote. Each one is an anchor phrase copied from
   the quote, the words to add (12 words max, 3 insertions max), and a verbatim
   evidence passage from the document.
3. **Assemble** (code only): checks that the anchor occurs exactly once in the
   quote, that the evidence is verbatim in the document or title, the length
   limits, and that anchors don't overlap. It then splices `[...]` in and checks
   that stripping the brackets gives back the original quote character for
   character. If any check fails, the row keeps its plain quote and
   `final_status` records the reason.

`direct_quote` is never modified. Every row comes out with exactly one
`final_status`: `resolved`, `not_needed_triage`, `not_needed_resolve`,
`unresolved`, `manual_review_existing_brackets`, or a `failed_*` reason.

## Run it

```bash
pip install anthropic   # or: pip install openai
```

```bash
python quote_context.py --quotes examples/quotes.csv --documents examples/documents.jsonl --out out.csv
```

Other options: `--provider openai --model <model>` uses OpenAI instead
(set `OPENAI_API_KEY`). `--cache-dir` sets where responses are cached
(default `.context_cache/`; unchanged re-runs make no API calls), and
`--no-cache` turns the cache off.

**Input: quotes CSV.** Required columns are `doc_id` and `direct_quote`.
`quote_id`, `speaker`, `organisation` and `date` are optional; triage sees the
last three. Any other columns pass through to the output unchanged.

**Input: documents.** JSONL or CSV with `doc_id`, `title` and `text`. Each
quote's `doc_id` must match a document. Documents over about 60k tokens are
refused rather than truncated.

**Output CSV.** The input columns, followed by `quote_in_context`,
`final_status`, `triage_expressions`, `insertions` (JSON, including the
evidence), `warnings`, `model_note`, and the prompt versions and model.

## Adapting to a new corpus

- The prompts (`TRIAGE_SYSTEM` and `RESOLVE_SYSTEM` in `quote_context.py`) are
  tuned to official policy statements. Edit the lists of typical cases and
  "does NOT need context" cases for the new domain. When you change a prompt,
  bump `TRIAGE_PROMPT_VERSION` or `RESOLVE_PROMPT_VERSION`.
- Leave the assembly checks alone. They are what make the output auditable
  without re-reading every document.
- Tests: `python -m unittest test_quote_context.py`. These run offline with a
  fake model.

## Track record in EPS

On the July 2026 US run, 39 quotes were resolved. Examples:

- `By entering into this agreement [the Cooperative Interstate Shipment (CIS) agreement], ...`
- `These investments [$80 million in guaranteed loans to businesses in Oregon and Nevada] will help ...`

The design notes in the code comments come from reviewing the trial runs. For
example, folding curly apostrophes fixed 8 of 14 false evidence failures, and
the title is withheld from triage because of what that review found.
