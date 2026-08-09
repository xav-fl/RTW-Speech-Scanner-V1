# eps — economics policy statements pipeline

Builds the dataset described in the RA field guide: economics-relevant policy
statements made by heads of US federal agencies and UK ministerial departments,
with verbatim quotations and JEL topic labels.

**Just want to run it?** → **[RUNNING.md](RUNNING.md)** — install, commands,
troubleshooting.
**Ready to test it?** → **[TESTING.md](TESTING.md)** — four phases, first three
cost nothing.

## The design decision that matters

**The model never writes the quote.** It returns *unit IDs* — pointers into a
frozen, hashed copy of the source document — and the quote is reconstructed by
copying those character ranges out of the source.

```
model output:  {"unit_ids": ["D194a0297c6.P002.S001", "D194a0297c6.P002.S002"]}
quote:         doc.text[units[0].char_start : units[-1].char_end]
```

Quote fidelity is therefore a property of the code, not a metric to be measured
after the fact. There is no code path by which model-generated text reaches the
`direct_quote` column. The same principle governs JEL codes: the model selects
from the frozen taxonomy rather than recalling codes, so an invented code is
impossible rather than merely discouraged.

## Stages

`ingest` and `harvest` are alternative ways to build the corpus — run one or the
other, not both. Everything after that is identical either way.

| Stage | Touches | Needs an API key | Re-runnable offline |
|---|---|---|---|
| `ingest` *(or)* | local files only | no | yes |
| `harvest` *(or)* | network only | no | no |
| `extract` | a model, cached by input hash | **yes** | yes, from cache |
| `build` | neither | no | yes, free |

The corpus is frozen once `ingest` or `harvest` has run, and model responses are
cached after `extract`, so you can iterate on the validators indefinitely without
spending anything. This is also what makes the repo a replication package: a
third party replays the committed cache and gets byte-identical output.

## Usage

```bash
pip install -e ".[dev]"
eps fetch-jel                        # rebuild the taxonomy from the AEA page
```

### Supply your own documents (recommended)

Corpus construction is decoupled from extraction, so you can choose the
documents yourself. This is more reliable than scraping and works for sources
that cannot be reached programmatically.

```bash
eps ingest --dir docs/ --write-template manifest.csv --country UK
#   ...fill in institution, url, title, doc_type, date...
eps ingest --run-dir runs/dfe --manifest manifest.csv
```

Accepts `.txt`, `.md`, `.html`, `.pdf`, `.docx`. Metadata that a scraper would
read from page markup comes from the manifest instead — which is more reliable
than guessing, and gives you a citable record of exactly which documents entered
the dataset. The manifest is validated before anything runs: a missing date or a
bad `doc_type` fails loudly rather than producing a quietly wrong row. Use
`--lenient` to skip bad rows instead.

### Or harvest automatically

```bash
eps harvest --run-dir runs/dfe --country UK \
            --institution "Department for Education" \
            --start 2026-01-01 --end 2026-07-31 --limit 25
```

### Then, either way

```bash
export ANTHROPIC_API_KEY=sk-ant-...       # only `extract` needs this
eps extract --run-dir runs/dfe            # --identity-mode blind (default) | full
eps build   --run-dir runs/dfe            # --min-quote-chars N
```

## Switching providers

`extract` calls a *provider* — a small object with one method, `call()`. Which
company answers is a one-flag choice; nothing else in the pipeline (caching,
validation, quote reconstruction, JEL checking) knows or cares which provider
ran.

```bash
pip install -e ".[mistral]"
export MISTRAL_API_KEY=...
eps extract --run-dir runs/dfe --provider mistral
```

Every output row records `provider`, so a dataset built with one and re-checked
with another is never ambiguous. The cache key includes it too, so switching
providers on the same run directory never serves you the wrong company's
answer.

`--provider mistral` uses a placeholder default model name
(`mistral-large-latest` as of writing) — Mistral's catalogue moves quickly, so
confirm the current identifier on Mistral's own docs and override with
`--model` if it has changed.

Adding a third provider means writing one class in `src/eps/providers.py` with
a `call(system, user, max_tokens) -> str` method — nothing in `extract.py`,
`validate.py`, or `assemble.py` needs to change.

The key authenticates calls to the Anthropic API and is what gets billed. Get one
from console.anthropic.com. `export` sets it for the current shell session only;
put it in your shell profile to persist it. **Never commit it** — it is a
credential, and `.gitignore` does not cover your shell history.

`ingest` and `build` do not call a model, so you can run both without a key and
inspect segmentation, attribution and validation before spending anything.

Output in `runs/dfe/out/`:

- `dataset.csv` — the Section 6 release table
- `observations_internal.csv` — the same rows plus JEL at all three levels, hashes, provenance
- `screening_log.csv` — one row per document screened, so a genuine zero is distinguishable from an agency that was never reached
- `rejected.csv` — every candidate the validators dropped, with the rule that dropped it
- `summary.json` — counts by institution and by reject reason

## Sources (`harvest` only)

Skip this section if you are supplying documents yourself via `ingest`.

**UK.** Two public GOV.UK APIs, no authentication. The Search API
(`/api/search.json`) enumerates documents by organisation, document type and
publication date; the Content API (`/api/content/<path>`) returns each document
as structured JSON with a pre-rendered HTML body, giving stable fields for
title, date, type and associated people rather than scraped page furniture.

**US.** No federal equivalent, so agencies are declared as data in
`src/eps/reference/us_sources.yaml` — listing URL, link selector, body selector.
Adding an agency is a few lines of YAML, not new code. Verify selectors against
the live page before a production run.

## Identity blinding

By default the model is **not** told the speaker, institution or document title —
only the text, document type and date. There is published evidence that LLMs use
party cues when evaluating political statements, and the pipeline already knows
the speaker from the officeholder join, so the model does not need it.

`--identity-mode full` restores the metadata. Running both over the same corpus
and diffing the selections is the paired robustness test: if selection depends on
who is speaking, that shows up as disagreement between the two runs. The cache
key includes the mode, so the two runs do not collide.

## Tuning the extraction criteria

The whole of the model's judgement lives in one editable string,
`EXTRACT_SYSTEM` in `src/eps/extract.py`. It has four parts: a QUALIFIES
definition, a NOT-qualifying exclusion list, structural SELECTION RULES, and the
output schema. The first two are §4/§5/§8 of the field guide restated; they are
where you tune what counts.

**While you are still tuning**, just edit `EXTRACT_SYSTEM`, re-run `extract` and
`build`, and look at the output. Nothing else is required. The prompt text is
part of the cache key, so an edit invalidates the cache by itself — you do not
need to bump `PROMPT_VERSION` for your change to take effect.

Every output row carries `prompt_sha`, a 12-character hash computed from the
prompt text itself. It changes whenever the wording changes, so provenance is
recorded automatically whether or not you label anything. Rows sharing a
`prompt_sha` came from identical prompts.

**Before anything leaves your machine** — a trial dataset for a supervisor, or a
release — do the labelling properly:

1. Set `PROMPT_VERSION` to something meaningful (`P3-narrower-growth`).
2. Copy the prompt as it stands into `prompts/<version>.md`.
3. Commit, and note the `prompt_sha` in your covering note.

`prompt_sha` is the machine record and needs no discipline; `PROMPT_VERSION` and
`prompts/` are the human record and need a little. Spend the effort only on
versions someone else will see.

The structural rules (contiguity, single paragraph, selectable-only) are enforced
in code as well as stated in the prompt, so loosening the wording alone will not
change behaviour — you would also need to change `reconstruct_quote()`.

## What the model decides, and what the code decides

Exactly one stage exercises judgement: `Extractor.select_units()` chooses which
sentences qualify, and `classify()` chooses JEL codes from a fixed list. That
judgement lives in the `EXTRACT_SYSTEM` prompt, not in an algorithm — there is no
threshold or keyword list to inspect.

Everything else is code: which documents exist, where sentence boundaries fall,
which sentences are *eligible* for selection, whether the speaker was in post, the
quote text itself, and whether the selection is structurally legal.

The `model_reason` column records the model's stated justification. It is
generated *after* the selection, so treat it as a summary for a human reviewer,
never as evidence about how the choice was made.

Note the asymmetry: **every validator guards precision; nothing guards recall.**
A missed passage is invisible to the pipeline. Only comparison against source
documents can detect it.

## Reference data (edit these before a real run)

- `institutions.csv` — 30 institutions with GOV.UK slugs. Extend to the full 24+24.
- `officeholders.csv` — **stub, replace this.** Eligibility is a join on
  `(institution, date)`, so this table decides which documents count. US acting-head
  churn and UK reshuffles both mean several institutions have multiple eligible
  speakers inside a seven-month window.
- `jel_codes.csv` — **partial bootstrap** (16 majors, 33 subcategories, 17
  detailed codes) so the tests run offline. Run `eps fetch-jel` and check the
  output before using it for anything real; the guide requires the AEA's exact
  current titles.

## Recorded but not yet used

- `delivery_status` — `as_delivered` / `as_prepared` / `unknown`. Most US
  agencies publish "remarks as prepared for delivery", which is what the
  speechwriter wrote, not what was said. Captured at harvest time because it
  cannot be reconstructed later.
- `raw_sha256`, `text_sha256`, `segmenter_version` — the segmenter version is
  part of document identity. Bump `SEGMENTER_VERSION` if you change any
  segmentation rule; old unit IDs will no longer point at the same text.

## Not yet built

- The 0.00–1.00 relevance score (deferred deliberately). When added, compute it
  from the Section 8 rubric as booleans rather than asking the model for a
  number — LLM confidence scores cluster on round values and the 0.60 cutoff
  would inherit that lumpiness.
- Automatic diffing of `blind` vs `full` runs. Currently you run both and compare
  `observations_internal.csv` yourself.
- The Section 11 review sampler. When you build it, record the probability each
  document was drawn with; that cannot be reconstructed afterwards.
- `k`-run stability: run extraction several times and keep units selected in a
  majority of runs.

## Tests

```bash
python -m pytest tests/ -q
```

The suite covers segmentation stability, offset correctness, quote
reconstruction, rejection of non-contiguous and cross-paragraph spans, rejection
of hallucinated unit IDs, exact-match anchoring, press-release attribution, and
JEL hierarchy/title validation.
