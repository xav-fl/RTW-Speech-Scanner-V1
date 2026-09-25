# INTENTION_TAG_REPORT_v1 — Intention tagging

## 1. Outcome

Intention tagging is built, wired into the pipeline and tested offline. Every kept quote gets a label, two Yes/No flags, a sidecar log record and a named failure reason if it fails. **The trial run on the v7 quotes has not happened yet** because no API key is set on this machine (STOP condition 5). Everything else is finished, and the trial now needs one command (Section 9).

## 2. Stage 0 findings

- **Repository.** `git rev-parse --show-toplevel` gave `C:/Users/xavif/WISE-PC/GITHUB CODE/RTW-Speech-Scanner-V1`, and the package is at `scanner-code/eps-pipeline/eps/src/eps/`. Both checks passed.
- **Snapshot.** The working tree had uncommitted changes, including the quote-context module (`context.py`, `test_context.py`) and two run folders. They were committed as `Pre-intention-tag snapshot` on `multi-dept-descriptives`, and the `intention-tag` branch was created from there. The repository has no `.gitignore` and already tracks run folders, so the snapshot included them.
- **Where the tagger sits.** `build()` in `pipeline.py` validates each document's observations and collects the kept rows. The context stage's `quote_in_context` is joined into those rows by quote ID. The tagger is called once, on that finished list, just before `write_dataset()`. At that point the quotes are final.
- **Pattern mirrored.** The quote-context step (`context.py`, class `Contextualiser`) takes the provider as its only external dependency. It caches every call in the run's `ResponseCache`, keyed on provider, model, prompt text, request and prompt version. It gives every quote exactly one final status. `IntentionTagger` follows the same structure: same constructor shape, same cached `_call`, same `_parse_json` reader borrowed from `extract.py`, one result per quote in.
- **Providers.** `providers.py` exposes `.call(system, user, max_tokens, cache_system)`. The Anthropic SDK retries with backoff up to 8 times, and temperature is fixed at 0. An account-level refusal (out of credit, key rejected) raises `ProviderStopped`. The tagger uses extraction's default, Anthropic `claude-sonnet-4-6`.
- **Models.** The project uses plain `dataclasses`, not pydantic, so the validators are written in `__post_init__`.
- **Neighbouring units.** A quote row carries `doc_id` and space-separated `unit_ids`. These are looked up in `Document.units`, which is in document order, to find the two units before and one after.
- **Release.** `RELEASE_COLUMNS` is written by `write_dataset()` to `dataset.csv`. The internal table repeats the release columns and adds more. **CSV is the only release format; there is no Excel writer.**
- **Prompt versioning.** `extract.prompt_fingerprint()` hashes the system prompts plus the source code of the functions that build user messages, and keeps the first 12 characters. The tagger's fingerprint is computed the same way.
- **Tests.** Tests live in `scanner-code/eps-pipeline/eps/tests/`, run with `python -m pytest`, and use `FakeProvider` so they never touch the network.
- **The v7 run.** `Downloads/dataset_context_trial_v7.csv` is byte-for-byte identical to `runs/trial-context-latest/out/dataset.csv` (221 quotes, 93 documents), so that run is the trial run.

## 3. Files created and edited

All paths are under `scanner-code/eps-pipeline/eps/` unless they start at the repository root.

| File | What changed |
|---|---|
| `src/eps/intention.py` (new) | The tagger: prompt `I1`, request builder, cue check, one retry, named failures, log writer, trial-file writer. |
| `src/eps/models.py` | Label codes, valid broad→sub pairs, evidence types, failure reasons, and `IntentionResult`, which checks itself on creation. |
| `src/eps/assemble.py` | Three release columns after `quote_in_context`, and the one display table that turns codes into release text. |
| `src/eps/pipeline.py` | One tagger call in `build()`, the `intention_log.jsonl` sidecar, and an `intention` section in `summary.json`. |
| `src/eps/cli.py` | `--skip-intention` on `build`, plus a new `tag-intention` command. |
| `tests/test_intention.py` (new) | 38 offline tests covering the 8 required checks and a few more. |
| `tests/test_pipeline.py` | The test that pins the release header now lists the three new columns. The brief requires the new columns, so this is not a weakened test. |
| `INTENTION_CODEBOOK.md` (root, new) | Word-for-word copy of the brief's Sections 4 and 5. |
| `INTENTION_TAG_REPORT_v1.md` (root, new) | This report. |

No file on the do-not-edit list was touched (extraction, JEL, validation, harvest, reference data, existing prompts, `PROMPT_VERSION`, `DECISIONS.md`). No new dependencies were added.

## 4. Tests

- **Before any changes:** 243 passed, 1 skipped, **3 failed**. The failures were `test_cross_paragraph_units_rejected`, `test_press_release_quoted_passage_is_attributable` and `test_attribution_frame_trimmed_from_press_release_quote`, all in `test_pipeline.py`.
- **After:** 281 passed, 1 skipped, **the same 3 failed**. Nothing that passed before fails now, and all 38 new tests pass.

The three existing failures are in attribution and segmentation code this feature does not touch. They were already failing on the snapshot commit.

I also did a dry run of `tag-intention` on a scratch copy of the v7 run, with a fake model supplying the answers. It gave 221 quotes in and 221 out, and every existing column was identical to v7. All 221 quotes found their neighbouring units. Failed first answers were recovered by the retry, and all four trial files were written.

## 5. How to use it

Run these from `scanner-code/eps-pipeline/eps/`. (`eps` works in place of `python -m eps.cli` if it is on your PATH.)

```bash
# Normal build: tags intentions (the default)
python -m eps.cli build --run-dir runs/<run>

# Build without tagging: the three columns are left blank; no model call at all
python -m eps.cli build --run-dir runs/<run> --skip-intention

# Re-tag an existing run without re-extracting
python -m eps.cli tag-intention --run-dir runs/<run>
```

Points to know:

- `build` now calls the model when tagging is on. Answers are saved in `runs/<run>/cache`, so rebuilding an unchanged run replays them for free, without a key.
- `tag-intention` joins `quote_in_context` back in from `out/context_log.csv`. It then checks that the rebuilt quotes match the existing `dataset.csv` exactly, and warns if they do not.

## 6. Trial run results

**Not run: no API key.** No quotes have been tagged, so there are no label counts, failure rates, Unclear rate, quote-only count or model results to report yet. When it runs, it will use `claude-sonnet-4-6` with prompt version `I1` (fingerprint `e53b1022f033`).

Two numbers are already known from the offline dry run:
- all 221 quotes will get `context_source = units`, so none will be `quote_only`;
- the rebuilt release matches v7 exactly apart from the three new columns.

## 7. Review sample

After the trial run, the sample will be at:

`scanner-code/eps-pipeline/eps/runs/trial-context-latest/out/intention_trial_v7/intention_review_sample_seed20260925.csv`

It contains every Unclear and Not tagged quote, plus up to 4 random quotes from each other broad category (seed 20260925). Reading it takes about 30 minutes.

## 8. Deviations from the brief

1. **16 release values, not 17.** Section 4 says "17 permitted release values" but lists 13 pairs, Rules out option, Unclear and Not tagged, which is 16. The test checks the listed 16. A blank value is also possible, but only when tagging is skipped.
2. **"On by default" applies to the command line.** `eps build` tags unless given `--skip-intention`. The `build()` function in code only tags when a tagger is passed to it, because a default live model call would break the offline test suite.
3. **Prompt appendix.** Sections 4 and 5 were rewritten into the prompt using the stored codes. Flags are written `true`/`false` to match the JSON the model returns. Two parts were left out because they are instructions to the builder, not to the tagger: the release-value paragraph and the "write a test" sentences.
4. **Command options.** The command uses `--run-dir` rather than `--run`, to match every other command. It also has `--out-dir` (so the trial does not overwrite v7) and `--trial-files` (to write the Section 8 files).
5. **Seed in the file name.** The review sample is named `intention_review_sample_seed20260925.csv`, which the brief allows. It also has three extra columns: `failure_reason`, `sample_reason` and `quote_id`.
6. **Detecting cut-off answers.** The provider interface returns only text, not the API's stop reason, and `providers.py` is outside the files I was allowed to edit. So `truncated_output` is detected from a JSON object that opens but never closes. If a provider later exposes its stop reason, the tagger will use it.
7. **Interpretation choices.** None of these changes a rule; they fill gaps in the brief:
   - an empty label cue on any label except Unclear is recorded as `cue_not_in_input`;
   - a flag that is not `true`/`false` is recorded as `invalid_json`;
   - `provider_error` gets no extra retry, because the SDK has already retried;
   - if the account stops being served (out of credit, key rejected), the remaining quotes are recorded as `provider_error` without further calls.

**Found in passing, not changed.** A plain `eps build` never joined `context_log.csv`, so running it on the v7 run would reset `quote_in_context` to the plain quote. This was already true before my changes. `tag-intention` does join it.

## 9. STOP condition hit, and what to do next

**STOP condition 5: the API key is missing.** To finish the trial:

1. Set the key in the terminal you will use (PowerShell: `$env:ANTHROPIC_API_KEY = "sk-ant-..."`).
2. From `scanner-code/eps-pipeline/eps/`, run:
   ```bash
   python -m eps.cli tag-intention --run-dir runs/trial-context-latest --out-dir runs/trial-context-latest/out/intention_trial_v7 --trial-files
   ```
   This makes about 221 model calls. That should cost about $1–2 (my estimate) and take a few minutes. Nothing is re-extracted, and v7's own files are not modified.
3. The files will be in `runs/trial-context-latest/out/intention_trial_v7/`:
   - `release_with_intention.csv`
   - `intention_label_counts.csv`
   - `intention_failures.csv`
   - `intention_review_sample_seed20260925.csv`
   - `intention_log.jsonl`
4. Then apply the brief's Section 8.5 checks:
   - if more than 10% are Not tagged because of formatting, make one parsing fix, change the version to `I2` and re-run;
   - if more than 20% are Unclear, report it and leave the rules alone.

   Or ask Claude Code to continue from this step.

## 10. Branch and commits

Branch **`intention-tag`**, created from `multi-dept-descriptives`:

| Commit | Message |
|---|---|
| `330af837` | Pre-intention-tag snapshot *(on `multi-dept-descriptives`, before branching)* |
| `298ef8dc` | intention: add intention data models and validators |
| `d8332e95` | intention: add tagger module, prompt I1 and codebook |
| `291a8afd` | intention: add three release columns and display mapping |
| `4b3fc983` | intention: call the tagger in build() and write intention_log.jsonl |
| `b1261631` | intention: add --skip-intention to build and a tag-intention command |
| `a2390a0f` | intention: add offline tests for tagging, failures, release values and skip |
| *(last)* | intention: add final report |

**Nothing has been pushed or merged.**
