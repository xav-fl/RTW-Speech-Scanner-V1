# INTENTION_FINALISE_REPORT_v1 — Intention tagging in the normal build

## 1. Outcome

Yes. `eps build` is ready to produce the dataset with the one new `intention` column. It tags with prompt I3 and keeps the existing `quote_in_context` values. An offline build of the v7 run produced exactly v7's columns plus `intention`, with every existing value unchanged.

No live model calls were made and nothing was re-extracted.

## 2. Files edited

All paths are under `scanner-code/eps-pipeline/eps/` unless they start at the repository root.

| File | Change |
|---|---|
| `src/eps/assemble.py` | Removed the two flag columns from the release. They stay in the internal table (`observations_internal.csv`). |
| `src/eps/pipeline.py` | `build()` now reads `context_log.csv` from the run's output folder and joins `quote_in_context`, warning if the log is missing or incomplete. It also warns when tagging runs without an API key, and prints the Not-tagged count by reason. |
| `src/eps/cli.py` | `tag-intention` now uses the shared context loader from `pipeline.py`. The key warning and the per-reason printout moved into `build()`, so each appears once. (Not on the brief's list; see Section 7.) |
| `tests/test_intention.py` | Updated the release tests. Added tests that the flags are absent from the release but present in the log, for the three context cases, for the explicit-context override, and for the missing-key warning. |
| `tests/test_pipeline.py` | The pinned release header now reads `…quote_in_context, intention, economics_topics…`. |
| `INTENTION_CODEBOOK.md` (root) | New "Release format" section. No label, definition or rule changed. |
| `INTENTION_FINALISE_REPORT_v1.md` (root) | This report. |

Two things were **not** changed. `intention.py` needed no edit: `INTENTION_PROMPT_VERSION` is already `"I3"`, and the tagger that `eps build` creates uses it by default. No prompt text or prompt version was touched.

## 3. Test results

| | Passed | Skipped | Failed |
|---|---|---|---|
| Before (on the `Pre-finalise snapshot` commit) | 284 | 1 | 3 |
| After | 291 | 1 | 3 |

The 3 failures are the known ones, both before and after: `test_cross_paragraph_units_rejected`, `test_press_release_quoted_passage_is_attributable` and `test_attribution_frame_trimmed_from_press_release_quote`. There are no new failures, and every previously passing test still passes.

Of the 7 extra passes:
- 6 are new tests;
- 1 is the flag-absence test that replaced the old flag-order test.

## 4. Offline check (Section 5 of the brief)

I made a scratch copy of `runs/trial-context-latest` (the v7 run) outside `runs/` and built it twice, both with no API key.

- **Build A** used the normal `eps build` with the real provider and no key. The 25 quotes with cached I3 answers from the earlier re-run replayed. The other 196 were recorded as `Not tagged (provider_error)`, as intended. The SDK refuses a keyless request before sending it, so no call left the machine. The missing-key warning printed, and the build finished.
- **Build B** was the same build with `FakeProvider` supplying answers for all 221 quotes.

| Check | Build A | Build B |
|---|---|---|
| `dataset.csv` has exactly v7's columns, plus `intention` right after `quote_in_context`, and no flag columns | ✅ | ✅ |
| `quote_in_context` identical to v7, row for row (221 rows, 70 with bracketed context) | ✅ | ✅ |
| Every other pre-existing column identical to v7 | ✅ | ✅ |
| `intention_log.jsonl` has both flags on every tagged quote | ✅ (25 of 25) | ✅ (221 of 221) |
| Context log joined, 0 unmatched (`summary.json`) | ✅ | ✅ |
| Prompt version in log | I3 | I3 |

The scratch copy was deleted afterwards.

## 5. How to run the next build

From `scanner-code/eps-pipeline/eps/`:

```bash
python -m eps.cli build --run-dir runs/<run>
```

**With an API key set**, every kept quote is tagged with prompt I3. Answers are saved in `runs/<run>/cache`, so building the same run again replays them for free. On the v7 run, 25 quotes are already cached and 196 would be new calls.

**Without a key**, the build still completes:

- a warning is printed at the start;
- cached answers replay;
- every other quote gets `intention = Not tagged`, with reason `provider_error` in `intention_log.jsonl`;
- the end of the build prints the Not-tagged count by reason.

**To skip tagging entirely**, add `--skip-intention`. The `intention` column is then blank and no model is called.

**Every build now**:

- reads `out/context_log.csv` and keeps the bracketed `quote_in_context`;
- warns `quote_in_context not joined: context_log.csv not found for this run` if the file is missing;
- warns with a count if some quotes have no row in the log. That count is also saved as `context.unmatched` in `summary.json`.

## 6. Merge information (nothing was merged)

**Main branch:** `main`. `origin/HEAD` points at `origin/main`, and `main` matches `origin/main` at `381003d0 Build: Initial harvest-code commit`. `main` contains only `harvest-code/`; it has no `scanner-code/` folder.

**What merging `intention-tag` into `main` would bring in: 30 commits.**

From `multi-dept-descriptives` (14). This is the whole scanner pipeline, which `main` does not yet have:

| Commit | Message |
|---|---|
| 5dcf0ea7 | Build: Gitignore, README, etc. |
| d4832a84 | Build: Tests |
| 16ee28eb | Build: src |
| 5a95b6c8 | Build: speeches |
| 7a571adc | Build: prompts and examples |
| 4f574d07 | Build: examples and prompts |
| 5e37fbc9 | Refactor: organised folders |
| 510cdfd8 | Docs: add DECISIONS_REPORT.md |
| 694b6625 | Fix: recover JEL level mismatches in _refine() instead of losing the observation |
| f6f766eb | Docs: record the B-10 fix in DECISIONS_REPORT.md |
| 17d7c378 | 27.08.2026 Version of Prompt |
| fc70664c | Add prompt caching to classify() — ready for production use |
| 832bdf9a | Snapshot of all uncommitted work before quote-context stage |
| 330af837 | Pre-intention-tag snapshot |

From `intention-tag` itself (16):

| Commit | Message |
|---|---|
| 298ef8dc | intention: add intention data models and validators |
| d8332e95 | intention: add tagger module, prompt I1 and codebook |
| 291a8afd | intention: add three release columns and display mapping |
| 4b3fc983 | intention: call the tagger in build() and write intention_log.jsonl |
| b1261631 | intention: add --skip-intention to build and a tag-intention command |
| a2390a0f | intention: add offline tests for tagging, failures, release values and skip |
| e515a1eb | intention: add final report |
| 62bb1228 | intention: trial run on v7 quotes and report results |
| 2d4974f4 | intention: prompt I2 with the project lead's rule changes |
| 4b1fdf88 | intention: I2 subset trial (78 of 221 v7 quotes) and report addendum |
| 4e8e1262 | intention: prompt I3 - explicit action test for Q3, present continuous in Q6 |
| 3166cfb3 | intention: I3 re-run on 25 affected rows and report addendum |
| 74d162b3 | Pre-finalise snapshot |
| 82e8e174 | intention-final: flags out of the release, kept in internal table and log |
| 7a8d95a6 | intention-final: build joins context_log.csv; missing-key warning |
| 745b8753 | intention-final: codebook release format section |

(Plus the commit that adds this report.)

**To merge everything.** This is the recommended route. `main` is an ancestor of `intention-tag`, so this is a fast-forward: no merge commit and no conflicts. `git merge-tree` confirmed this.

```bash
git checkout main
git merge --ff-only intention-tag
git push origin main
```

(Push only when you are ready to publish.)

**To bring only the `intention-tag` commits onto `main`:**

```bash
git checkout -b intention-only main
git cherry-pick multi-dept-descriptives..intention-tag
```

**This does not work.** I tried it on a throwaway branch and deleted the branch afterwards. It stops on the very first commit with a conflict ("models.py deleted in HEAD and modified in 298ef8dc"). The reason: the intention commits change files such as `models.py`, `pipeline.py` and `cli.py` that only exist in the `multi-dept-descriptives` commits. The tagger also imports `context.py`, which arrived in the `Pre-intention-tag snapshot`. Without the 14 pipeline commits, there is nothing for the intention commits to apply to. **Use the full merge.**

One note before merging: the `multi-dept-descriptives` snapshot commits include run folders (documents, caches and outputs). The repository has no `.gitignore` that excludes them, so they will land on `main` too.

## 7. Deviations from the brief

1. **`cli.py` was edited**, although it is not on the "may edit" list (it is not on the "must not edit" list either). Section 4.2 requires the context join to be shared and "called from both places", and one of those places, `tag-intention`, lives in `cli.py`. Moving the key warning and failure printout into `build()` (Section 4.3) also meant removing the old copies from `cli.py`, so nothing prints twice.
2. **4.2 and 4.3 share one commit**, because they touch the same lines of `build()`. 4.1 and 4.4 have their own commits.
3. **How `build()` finds the context log.** It reads `context_log.csv` from the folder it is writing to (`runs/<run>/out/`), unless a context mapping is passed in explicitly. `tag-intention --out-dir elsewhere` passes the run's own log, so writing to another folder still keeps the context.
4. **The key warning checks the provider actually in use.** That is `ANTHROPIC_API_KEY` for Anthropic (the default), or `MISTRAL_API_KEY` if Mistral is chosen.
5. **The flags stay in `observations_internal.csv` on purpose.** The internal column list is built from the release list, so removing the flags from the release would have silently dropped them from the internal table too. They are now listed there explicitly.
6. **The `Pre-finalise snapshot` commit held only compiled bytecode** (`__pycache__`), which the repository tracks. Running the tests has since changed those files again; that new bytecode is left uncommitted.

## 8. STOP conditions

None hit.

## 9. Commits on this pass

| Commit | Message |
|---|---|
| 74d162b3 | Pre-finalise snapshot |
| 82e8e174 | intention-final: flags out of the release, kept in internal table and log |
| 7a8d95a6 | intention-final: build joins context_log.csv; missing-key warning |
| 745b8753 | intention-final: codebook release format section |
| (last) | intention-final: add finalise report |

**Nothing was merged, rebased or pushed, and nothing was run against the API.** The throwaway dry-run branch was deleted. The scratch copy of the v7 run was deleted, and nothing under `runs/` was modified.
