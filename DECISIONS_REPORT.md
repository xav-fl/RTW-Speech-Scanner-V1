# eps Pipeline — Decision Report

## Changelog

| Version | Date | Commit | Changes |
|---|---|---|---|
| v1.0 | 2026-08-25 | `5e37fbc` | Initial sweep. |
| v1.1 | 2026-08-25 | `694b662` | B-10 fixed in `_refine()`. No re-sweep; baseline commit unchanged. |

## Front matter

- **Version:** v1.0
- **Date:** 2026-08-25
- **Author:** [RA name — fill in]
- **Swept against commit:** `5e37fbc` (`initial-upload-branch`)
- **Working tree at sweep time:** dirty — 29 modified files and 14 untracked
  paths. The three patch scripts in `scripts/` have been applied to
  `normalise.py`, `validate.py`, `jel.py` and `harvest/local.py` but not
  committed; `runs/`, `scripts/`, `documents_v2/` and both DfE manifests are
  untracked. **This report describes the working tree, not commit `5e37fbc`.**
  Every entry below reflects the code as it stands on disk.
- **Pipeline state:** UK harvest complete and audited (2,672 documents
  retrieved, 936 attributable, 868 queued). Corpus re-extracted into
  `documents_v2` after the text-fidelity fault (B-05, B-06). DfE pilot extracted
  twice — `runs/dfe-pilot` (17 observations kept, 8 rejected) and `runs/dfe-v2`
  (24 kept, 5 rejected), 10 documents each. Full extraction not begun. US
  collection not started.

## Legend

**Location tags** take the form `[stage/filename:anchor]`. Paste the tag into your
editor's search to find the code. The anchor is a function name, variable name, or
line number.

The repository holds two codebases. The stage prefix names the pipeline stage,
not the folder, so this table maps a prefix to the directory the file is in:

| Prefix | Directory |
|---|---|
| `harvest/` | `harvest-code/` and `harvest-code/harvest-v3/` |
| `ingest/`, `extract/`, `build/` | `scanner-code/eps-pipeline/eps/src/eps/` |
| `manifest/` | `harvest-code/` and `scanner-code/eps-pipeline/eps/scripts/` |
| `reference/` | `scanner-code/eps-pipeline/eps/src/eps/reference/` and `harvest-code/` |

**IDs** are permanent and append-only. The letter marks the stage: H harvest,
I ingest, M manifest, E extraction, D dataset build, R reference data, S scope,
B bug fix. Numbers are never reused or reassigned.

**Status** takes one of three values:

- **Settled** — decided and implemented. Changing it means changing the code.
- **Pending PI decision** — awaiting a call from the PIs. Output will change once decided.
- **Superseded** — replaced by a later decision. Retained for the record, with a pointer
  to the entry that replaced it.

## How to use this document

Read it front to back the first time. Sections 1 to 6 run in the order the
pipeline executes — harvest, ingest, manifest, extraction, build, reference data
— not in order of importance, so a problem visible in the final spreadsheet can
be traced backwards stage by stage until you reach the decision that caused it.
Entries marked **Pending PI decision** are the ones that will change the output
once they are settled; they are gathered in Appendix A, and Section 7 holds the
definitional questions where PI sign-off is needed before release. Bugs carry a
`B` prefix but sit inline at the code they affected, because someone judging
whether the DfE pilot output is trustworthy needs to see a corrected fault in the
same place as the deliberate choice next to it. To regenerate: Claude Code
re-sweeps the repository against the commit named in the front matter, appends
new entries with the next free ID in each prefix, marks changed decisions
Superseded rather than deleting them, and the Markdown is converted to Word for
circulation. `DECISIONS_REPORT.md` is the canonical file; never hand-edit the
Word version.

## 1. Harvest

Two harvesters exist. `harvest-code/govuk_harvest.py` is the standalone script
that actually produced the UK corpus. `src/eps/harvest/govuk.py` is the packaged
harvester reachable from `eps harvest`; it has never been used for a real run and
does not currently work (B-14). Entries are ordered by file — the standalone
harvest first, then the audit tooling, then the packaged harvesters — and by
position within each file.

### H-01 — Nine GOV.UK document types are harvested; everything else is excluded

- **Location:** `[harvest/govuk_harvest.py:DOC_TYPE_MAP]`
- **Decision:** The Search API is filtered to `speech`, `authored_article`,
  `written_statement`, `oral_statement`, `government_response`, `press_release`,
  `news_story`, `correspondence` and `transcript`. Anything else GOV.UK publishes
  in the window is never retrieved. The same nine keys drive both the search
  filter and the mapping to the guide's normalised labels.
- **Rationale:** These are the publication types Section 4 of the field guide
  admits. Keeping the search filter and the label map in one dictionary means a
  type cannot be retrieved without also being labelled.
- **Status:** Settled
- **Context:** `govuk_audit.py` reports every type that exists in the window but
  was *not* pulled (H-22), so the exclusion is auditable rather than invisible.
  `HARVESTED_TYPES` in `govuk_audit.py` is a hand-maintained copy of these keys
  and must be edited alongside them.

### H-02 — `news_story` is mapped to `press_release`

- **Location:** `[harvest/govuk_harvest.py:DOC_TYPE_MAP]`
- **Decision:** GOV.UK's `news_story` type is written into the
  `normalised_document_type` column as `press_release`. 135 of the 868 queued
  documents are affected.
- **Rationale:** Section 4 names "News story" as an eligible publication type, but
  the closed list of eight normalised labels contains no equivalent. The
  alternatives considered were `other` (stays inside the specified list but
  discards information) or adding a ninth label (departs from the spec).
  `press_release` was chosen provisionally on 2026-08-09.
- **Status:** Pending PI decision
- **Context:** The original GOV.UK type is preserved in the `govuk_document_type`
  column throughout, so this can be revised without re-harvesting. `DECISIONS.md`
  §3 records `relabel_doc_types.py` as the tool that would apply either
  alternative — **that script is not present in this repository** (see Findings).
  See also S-06.

### H-03 — HTTP retries: four attempts with exponential backoff, 45-second timeout

- **Location:** `[harvest/govuk_harvest.py:get_json()]`
- **Decision:** Every API call is retried up to four times with a `2 ** attempt`
  second pause (1s, 2s, 4s). After the fourth failure the function returns `None`
  and the caller records the failure rather than aborting the run.
- **Rationale:** Not recorded — confirm with RA. The observable effect is that a
  transient network failure costs a document rather than the whole harvest.
- **Status:** Settled
- **Context:** A document whose content fetch exhausts its retries still gets a
  screening-log row with `exclusion_reason = content_api_unreachable` (H-19), so
  the loss is counted rather than silent.

### H-04 — A 0.3-second pause between API requests

- **Location:** `[harvest/govuk_harvest.py:search_documents()]`
- **Decision:** 0.3 seconds between search pages and between content fetches.
- **Rationale:** Not recorded — confirm with RA. Presumed courtesy rate-limiting
  against an unauthenticated public API.
- **Status:** Settled
- **Context:** Hardcoded, not a flag. At 2,672 documents this is roughly 13
  minutes of the run spent deliberately idle. The packaged harvester uses 0.2s
  (H-30) and the US harvester 0.5s (H-31); none of the three is configurable from
  the CLI.

### H-05 — Organisation lookup deliberately does not filter on organisation type

- **Location:** `[harvest/govuk_harvest.py:resolve_departments()]`
- **Decision:** Every organisation record GOV.UK returns is fetched and matched
  against the canonical department list. There is no
  `organisation_type == "ministerial_department"` filter.
- **Rationale:** When GOV.UK closes a department it reclassifies it from
  `ministerial_department` to `other`. A type filter therefore drops exactly the
  merged predecessors the collection needs. Matching against the canonical list is
  what bounds the result, so genuinely historical departments cannot get through.
- **Status:** Settled
- **Context:** Introduced in response to B-02, which lost roughly 240 DBT and DSIT
  documents.

### H-06 — Every slug variant for a department is searched, live records first

- **Location:** `[harvest/govuk_harvest.py:resolve_departments()]`
- **Decision:** All GOV.UK organisation records matching a canonical name are
  kept, sorted so live organisations precede closed ones, and every slug is
  searched. Results are deduplicated by URL before any further processing.
- **Rationale:** GOV.UK carries both `wales-office` and
  `office-of-the-secretary-of-state-for-wales` as separate records with content
  split between them. Picking one silently loses the other.
- **Status:** Settled
- **Context:** The first slug in the sorted list is what appears in the
  `govuk_slug` column; the full list is used for searching. See S-11 for the Wales
  Office case, where a second slug carrying the missing content does not exist.

### H-07 — The harvest iterates the canonical department list, not the API's output

- **Location:** `[harvest/govuk_harvest.py:CANONICAL_UK_DEPARTMENTS]`
- **Decision:** Both the harvest and the audit loop over the frozen list of
  departments. A department that publishes nothing still produces a screening-log
  row with `exclusion_reason = no_documents_in_window`.
- **Rationale:** Section 5 requires a genuine zero to be distinguishable from a
  department that was never processed. Iterating whatever the API returns makes a
  silent department vanish from every downstream report.
- **Status:** Settled
- **Context:** This is the fix for B-03. Three UK offices produced genuine zeros in
  the window; see S-10.

### H-08 — DBIST is harvested as a 25th department alongside DBT and DSIT

- **Location:** `[harvest/govuk_harvest.py:CANONICAL_UK_DEPARTMENTS]`
- **Decision:** The canonical list holds 25 entries: the guide's 24 plus
  "Department for Business, Innovation, Science and Trade". DBT, DSIT and DBIST are
  all harvested as separate institution labels (123, 120 and 4 documents).
- **Rationale:** GOV.UK merged DBT and DSIT into DBIST at the 2026-07-20 reshuffle.
  Documents published before that date remain filed under the old slugs, so all
  three must be searched to cover January to July. Collecting all three defers the
  question of whether DBIST is one unit of observation or two, rather than
  foreclosing it.
- **Status:** Pending PI decision
- **Context:** See R-03 and S-04. `check_queue.py` still checks against the guide's
  24 and will flag DBIST as an unexpected institution (M-13).

### H-09 — Institution names are normalised and aliased; the frozen list is not edited

- **Location:** `[harvest/govuk_harvest.py:normalise_institution()]`,
  `[harvest/govuk_harvest.py:INSTITUTION_ALIASES]`
- **Decision:** Both sides of every institution comparison are lowercased,
  ampersands folded to "and", punctuation dropped and whitespace collapsed. Five
  cases where GOV.UK's official title differs from the canonical name entirely
  (Scotland Office, Wales Office, both Leaders' Offices, Advocate General) are
  handled by an explicit alias table.
- **Rationale:** GOV.UK writes "Department for Environment, Food **&** Rural
  Affairs" where the guide writes "...Food and Rural Affairs". Normalising both
  sides keeps the guide's frozen list unmodified, which the guide requires.
- **Status:** Settled
- **Context:** The alias table is applied inside `normalise_institution()`, so it
  affects slug resolution as well as officeholder lookup.

### H-10 — A separate alias table is applied only when looking up an officeholder

- **Location:** `[harvest/govuk_harvest.py:OFFICEHOLDER_ALIASES]`,
  `[harvest/govuk_harvest.py:eligible_on()]`
- **Decision:** DBIST maps to "department for business and trade" **only** when
  resolving the eligible speaker, never when resolving a GOV.UK slug.
- **Rationale:** DBIST has no officeholder row of its own; Jonathan Reynolds heads
  both it and DBT from 2026-07-20, so borrowing DBT's row gives correct
  attribution. Keeping the table separate from `INSTITUTION_ALIASES` stops DBIST
  and DBT collapsing into a single slug and losing the distinction the PIs still
  need to rule on.
- **Status:** Settled
- **Context:** Depends on H-08 remaining as it is. If the PIs fold DBIST into DBT,
  this table becomes redundant rather than wrong.

### H-11 — Name matching strips honorifics and post-nominals and requires a shared forename

- **Location:** `[harvest/govuk_harvest.py:normalise_name()]`,
  `[harvest/govuk_harvest.py:names_match()]`
- **Decision:** Bracketed peerage titles, a fixed list of leading honorifics
  (`HONORIFICS`) and a fixed set of 30 post-nominals (`POST_NOMINALS`) are removed
  before comparison. Two names match when the last token is identical **and**
  either they share a forename token or one name carries no forename at all.
- **Rationale:** GOV.UK writes "The Rt Hon Bridget Phillipson MP" where the
  officeholders file writes "Bridget Phillipson". Surname alone is insufficient:
  Ellie Reeves and Rachel Reeves, and Emma Reynolds and Jonathan Reynolds, all hold
  posts inside the window. The no-forename escape exists for titles such as
  "Baroness Smith of Cluny".
- **Status:** Settled
- **Context:** This is the fix for B-01. Note that the no-forename escape is
  permissive by design: any officeholder recorded under a title alone will match
  every person sharing that surname.

### H-12 — Attribution is a five-value ladder, and only `linked` reaches the queue

- **Location:** `[harvest/govuk_harvest.py:main()]`
- **Decision:** Each document is assigned exactly one of `linked` (GOV.UK names a
  speaker who matches the eligible officeholder), `linked_mismatch` (GOV.UK names
  someone else), `name_in_body` (no structured speaker, but the officeholder's
  surname appears in the text), `no_match`, or `no_officeholder_record`.
- **Rationale:** An explicit GOV.UK speaker link is strong evidence; a surname
  appearing in body text is weak and is flagged as a triage signal rather than a
  confirmed attribution.
- **Status:** Settled
- **Context:** Outcomes across 2,672 documents: 936 `linked`, 1,042
  `linked_mismatch` (mostly junior ministers), 584 `no_match`, 110 `name_in_body`.
  Only `linked` documents enter the extraction queue (M-03, M-04). The
  `name_in_body` test is a lowercased substring search for the surname, so it also
  matches a surname occurring inside a longer word.

### H-13 — Structured speakers are read from four places

- **Location:** `[harvest/govuk_harvest.py:extract_speakers()]`
- **Decision:** Names are collected from `links.speaker`, `links.people`,
  `links.ministers` and the string form of `details.speaker`, in that order,
  deduplicated, and joined with "; " into the `linked_speakers` column.
- **Rationale:** Speeches carry `links.speaker`; press releases usually carry
  nothing, which is why the name-matching fallback exists downstream.
- **Status:** Settled
- **Context:** Because `links.people` is included, a document listing several
  ministers produces several candidate names and is marked `linked` if **any** of
  them is the eligible officeholder.

### H-14 — Officeholder `end_date` is treated as INCLUSIVE in the harvest

- **Location:** `[harvest/govuk_harvest.py:eligible_on()]`
- **Decision:** A spell covers a document when `start_date <= date` and
  `date <= end_date`. A document published on a handover date matches both the
  outgoing and the incoming officeholder, and `eligible_on()` returns both.
- **Rationale:** Not recorded — confirm with RA.
- **Status:** Pending PI decision
- **Context:** This contradicts two other places in the project. The officeholder
  workbook's own README states the rule as "start date <= publication date <
  end date" (R-11), and `check_queue.py` defaults to exclusive (M-11) and reports
  overlapping spells as a data error on that basis. `OfficeholderTable` in the
  build stage is also inclusive but returns only the first matching row (D-10).
  Until this is settled, a handover-day document has an ambiguous speaker. See
  S-07.

### H-15 — Publication date is used as the document date, not delivery date

- **Location:** `[harvest/govuk_harvest.py:main()]`
- **Decision:** The `date` column is the first ten characters of GOV.UK's
  `public_timestamp`.
- **Rationale:** Delivery date is not available from the Search API, and
  publication date is what the source records.
- **Status:** Settled
- **Context:** For speeches the two can differ, which would matter across a
  reshuffle. Checked once: all five speeches published between 10 and 31 July have
  GOV.UK speaker links agreeing with the officeholder file, so no misattribution
  was found. The risk remains theoretical but unobserved. See S-15.

### H-16 — Each document is written as a text file with a five-line metadata header

- **Location:** `[harvest/govuk_harvest.py:main()]`
- **Decision:** Files are named `documents/<date>__<slugified-url>.txt`, truncated
  to 120 characters, and open with `TITLE:`, `URL:`, `DATE:`, `GOVUK_TYPE:` and
  `LINKED_SPEAKERS:` lines followed by `---` and the body text.
- **Rationale:** Not recorded — confirm with RA. The header makes a file
  self-describing if it is separated from the screening log.
- **Status:** Settled
- **Context:** `audit_text_fidelity.py:strip_header()` removes these lines before
  comparison so header tokens such as "govuk" are not mistaken for corrupted body
  text. The rewritten `documents_v2` files carry **no** header — the rewriter
  writes body text only.

### H-17 — The harvest refuses to run if any department cannot be resolved

- **Location:** `[harvest/govuk_harvest.py:main()]`
- **Decision:** If any canonical department fails to resolve to a GOV.UK slug, the
  script prints the names and exits, unless `--allow-partial` is passed.
- **Rationale:** A partial harvest looks complete downstream. Failing loudly is the
  only way the gap stays visible.
- **Status:** Settled
- **Context:** `--allow-partial` is off by default and was not used for the
  production harvest.

### H-18 — Officeholder coverage is checked before any downloading starts

- **Location:** `[harvest/govuk_harvest.py:main()]`
- **Decision:** Before the first document is fetched, every resolved department is
  tested against the officeholders CSV and any department with no matching row is
  listed, together with unmatched CSV institution names as possible near-misses.
  This is a warning, not a stop.
- **Rationale:** An unmatched name silently produces a department with no eligible
  speaker and therefore no observations, which is invisible until the whole run has
  finished.
- **Status:** Settled
- **Context:** Unlike H-17 this does not abort. A department with no officeholder
  row is still harvested; every one of its documents is marked
  `no_officeholder_record`.

### H-19 — A document whose content fetch fails is still recorded

- **Location:** `[harvest/govuk_harvest.py:main()]`
- **Decision:** When the Content API returns nothing, a screening-log row is
  written with the metadata that is known and
  `exclusion_reason = content_api_unreachable`, and no text file is produced.
- **Rationale:** Section 6 requires every page inspected to stay on record.
- **Status:** Settled
- **Context:** These rows have `word_count = 0` and are excluded from the queue by
  the length filter regardless.

### H-20 — Body text comes from `details.body`, falling back to `details.parts`

- **Location:** `[harvest/govuk_harvest.py:body_text()]`
- **Decision:** If `details.body` is a non-empty string it is converted to text.
  Otherwise the document's `parts` are concatenated, each part's title followed by
  its converted body.
- **Rationale:** Some GOV.UK formats split the body across parts; ignoring them
  would produce an empty document that looks like a short one.
- **Status:** Settled
- **Context:** Part titles are interleaved with body text, so a multi-part
  document's headings become ordinary paragraphs.

### H-21 — The officeholders CSV is filtered to the United Kingdom

- **Location:** `[harvest/govuk_harvest.py:load_officeholders()]`
- **Decision:** Only rows whose `country` column is exactly `United Kingdom` are
  loaded. The `csv` module is used rather than splitting on commas.
- **Rationale:** Several institution names contain commas inside quoted fields. The
  country filter keeps the US half of the same file out of the UK harvest.
- **Status:** Settled
- **Context:** The match is exact and case-sensitive. `check_queue.py` applies a
  looser test to the same file (`startswith("uk", "united k")` after lowercasing).

### B-01 — Surname matching returned "MP", so nothing was ever attributed

- **Location:** `[harvest/govuk_harvest.py:POST_NOMINALS]`
- **Decision:** Post-nominals were not stripped before comparison, so the last
  token of "The Rt Hon Bridget Phillipson MP" was "mp". Every comparison failed and
  zero speeches were attributed to any officeholder. Fixed by adding the
  `POST_NOMINALS` set and filtering it out in `normalise_name()`.
- **Rationale:** n/a — defect.
- **Status:** Settled
- **Context:** Surfaced because the audit's speaker column read 0 across every
  department. `fix_speaker_match.py`, recorded in `DECISIONS.md` §8 as the one-off
  repair, is superseded by this fix and is not present in the repository.

### B-02 — Merged departments were silently lost

- **Location:** `[harvest/govuk_harvest.py:resolve_departments()]`
- **Decision:** Filtering organisations by `organisation_type` excluded DBT and
  DSIT after GOV.UK reclassified them on closure, losing roughly 240 documents.
  Fixed by removing the type filter and bounding the result with the canonical list
  instead (H-05).
- **Rationale:** n/a — defect.
- **Status:** Settled
- **Context:** Caught by DBT showing 66 documents in the log where the Search API
  reported 824.

### B-03 — Silent departments vanished from the audit

- **Location:** `[harvest/govuk_audit.py:main()]`
- **Decision:** The audit iterated over institutions present in the screening log,
  so a department that produced nothing simply did not appear — the exact failure
  the audit existed to detect. Fixed by iterating `CANONICAL_UK_DEPARTMENTS`
  imported from the harvest.
- **Rationale:** n/a — defect.
- **Status:** Settled
- **Context:** The same reasoning drove H-07 on the harvest side.

### B-04 — Cross-institution "missed document" counts were inflated

- **Location:** `[harvest/govuk_audit.py:main()]`
- **Decision:** The person-level cross-check ignored tenure dates and compared a
  minister's documents against one department's URLs only, so ministers who changed
  department at the reshuffle appeared to have enormous coverage gaps. Fixed by
  restricting each person's spells to that institution and comparing against every
  URL in the log.
- **Rationale:** n/a — defect.
- **Status:** Settled
- **Context:** The Secretary of State for Business and Trade also heads UK Export
  Finance, so the second half of the fix matters even without a reshuffle.

### H-22 — The audit reconciles the log against a Search API aggregate

- **Location:** `[harvest/govuk_audit.py:type_breakdown()]`
- **Decision:** For each department the audit issues one `count=0` request with
  `aggregate_content_store_document_type`, compares the API's per-type totals
  against the log, and prints both the harvested types and the residual types that
  were not pulled.
- **Rationale:** One cheap request regardless of how many thousands of documents
  the organisation published, and it turns the exclusion in H-01 into a visible
  decision rather than an accident.
- **Status:** Settled
- **Context:** Reconciliation passed for all 25 institutions in the production
  harvest — the log count matches the API count for the same filters.

### H-23 — The person cross-check is bounded by tenure at that institution

- **Location:** `[harvest/govuk_audit.py:main()]`
- **Decision:** For each officeholder the audit resolves their GOV.UK person page,
  lists everything GOV.UK links to them in the window, and reports documents absent
  from the **whole** screening log, restricted to that person's spells at that
  institution and to harvested document types.
- **Rationale:** Catches documents filed under a different organisation — joint
  announcements, No10, cross-department launches — that a department-filtered
  search cannot see.
- **Status:** Settled
- **Context:** This is what found the Wales Office gap (S-11).

### B-05 — HTML-to-text conversion dropped spaces and welded words together

- **Location:** `[harvest/audit_text_fidelity.py:_clean_inline()]`
- **Decision:** The original extractor removed tags and newlines without leaving a
  space, so "Parents end up fighting" was stored as "Parents endup fighting". Fixed
  in the re-extractor by replacing **every** tag with a space, converting `<br>` to
  a newline, and then pulling spaces back from before punctuation without ever
  merging two words.
- **Rationale:** n/a — defect. It broke the pipeline's central guarantee: quotes
  are verbatim against the frozen text, but the frozen text no longer matched the
  page it cited.
- **Status:** Settled
- **Context:** The faulty code is still live in
  `[harvest/govuk_harvest.py:TextExtractor]` — the fix was made in a separate
  re-extraction script rather than in the harvester, so **a re-run of
  `govuk_harvest.py` would reproduce the fault.** Detected by `--audit`, which
  re-fetches a sample and looks for words present in the fresh text whose halves
  are welded together in the stored file.

### B-06 — Blockquote structure was flattened, destroying the attribution signal

- **Location:** `[harvest/audit_text_fidelity.py:html_to_blocks()]`,
  `[harvest/audit_text_fidelity.py:render()]`
- **Decision:** GOV.UK press releases mark ministerial speech with `<blockquote>`
  and no quotation marks. The original ingestion flattened these into ordinary
  paragraphs, destroying the only structural signal separating the minister's words
  from departmental prose. Fixed by rebuilding the corpus through the Content API
  into `documents_v2`, tracking blockquote depth and prefixing quoted paragraphs
  with `> `.
- **Rationale:** n/a — defect. Without the marker there is nothing for a structural
  attribution rule to work from; see I-09 and B-09.
- **Status:** Settled
- **Context:** `documents_v2` is the corpus the `dfe-v2` run used; `documents` is
  the original and was used for `dfe-pilot`. Both directories are present and
  neither is tracked by git.

### H-24 — The re-extraction writes to a new folder and never touches the originals

- **Location:** `[harvest/audit_text_fidelity.py:main()]`
- **Decision:** `--rewrite` writes into `documents_v2/` and records every document
  in `rewrite_log.csv` with its URL, quote-block count, linked speakers and status.
- **Rationale:** The original harvest is a dated snapshot of pages that change;
  overwriting it would destroy the only record of what was retrieved on 2026-08-09.
- **Status:** Settled
- **Context:** The rewriter re-fetches from the live Content API, so `documents_v2`
  is a snapshot of a **later** date than `documents`. Any page GOV.UK edited
  between the two runs differs between the folders, and neither the rewrite log nor
  the screening log records a second retrieval date.

### H-25 — The fidelity audit samples 12 documents with a fixed seed

- **Location:** `[harvest/audit_text_fidelity.py:main()]`
- **Decision:** `--sample` defaults to 12 and `--seed` to 0, so repeated audits
  inspect the same documents. `--url` audits one named document instead.
- **Rationale:** A fixed seed makes the audit reproducible; the sample size keeps it
  to a few minutes of API calls. The choice of 12 specifically is not recorded —
  confirm with RA.
- **Status:** Settled
- **Context:** A 12-document sample of 868 gives no useful upper bound on the
  corpus-wide corruption rate; it was used as a detector, not as an estimator.

### H-26 — The packaged harvester maps five extra GOV.UK types to `other`

- **Location:** `[harvest/govuk.py:GOVUK_TYPE_MAP]`, `[harvest/govuk.py:DEFAULT_TYPES]`
- **Decision:** `src/eps/harvest/govuk.py` recognises `open_letter` (as `letter`)
  and maps `policy_paper`, `guidance`, `detailed_guide` and `consultation_outcome`
  to `other`. Its search filter, `DEFAULT_TYPES`, omits `government_response` —
  which the standalone harvester does retrieve — and includes `open_letter`, which
  the standalone harvester does not.
- **Rationale:** Not recorded — confirm with RA.
- **Status:** Settled
- **Context:** The two harvesters would therefore produce different corpora from
  the same window. Only the standalone script has been used for a real run.

### H-27 — Publication date falls back through three fields to a 1900 sentinel

- **Location:** `[harvest/govuk.py:_parse_date()]`
- **Decision:** `first_published_at`, then `public_updated_at`, then
  `published_at`; if all are absent the date becomes `1900-01-01`.
- **Rationale:** A sentinel is visible in the output; a crash or a `None` is not.
- **Status:** Settled
- **Context:** The same sentinel is used by the US harvester (H-31). Nothing
  downstream filters on it, so a 1900 row would reach the build stage and be
  excluded only by the officeholder join failing to find a spell.

### H-28 — `speaker_hint` is the first linked person only

- **Location:** `[harvest/govuk.py:build_document()]`
- **Decision:** `links.people[0].title` becomes the document's `speaker_hint`.
  Other linked people are discarded.
- **Rationale:** Not recorded — confirm with RA.
- **Status:** Settled
- **Context:** This differs from H-13, where the standalone harvester keeps every
  linked name and tests all of them. Since `speaker_hint` now also drives the
  attribution rule (I-20), picking the wrong person here would make a press
  release's quotations unattributable.

### H-29 — Delivery status is mapped from GOV.UK's delivery type

- **Location:** `[harvest/govuk.py:DELIVERY_MAP]`
- **Decision:** `speech` and `transcript` map to `as_delivered`;
  `written_statement_to_parliament` and `authored_article` to `as_prepared`;
  anything unrecognised to `unknown`.
- **Rationale:** Whether the text is what was said or what was written to be said
  cannot be reconstructed after the fact, so it is recorded at harvest time.
- **Status:** Settled
- **Context:** The column is recorded but not yet used by any analysis. The
  standalone harvester does not populate it at all — `queue_to_manifest.py`
  hardcodes `unknown` (M-07), so every document in the DfE pilot carries `unknown`.

### H-30 — The packaged harvester pages 200 at a time with a 0.2-second pause

- **Location:** `[harvest/govuk.py:PAGE_SIZE]`
- **Decision:** `PAGE_SIZE = 200`, with a comment noting the Search API allows
  more, and `pause = 0.2` as a constructor default.
- **Rationale:** Keeps responses small and stable.
- **Status:** Settled
- **Context:** Neither is exposed on the CLI.

### H-31 — US sources are declared as data, not code

- **Location:** `[harvest/us.py:USSource]`, `[harvest/us.py:USHarvester]`
- **Decision:** Each US agency is a YAML record in `reference/us_sources.yaml`
  giving a listing URL, a CSS link selector and body/title/date selectors.
  Defaults: `doc_type = press_release`, `max_pages = 20`, `pause = 0.5`, date
  sentinel `1900-01-01`. Pagination stops early when a page yields no new links.
- **Rationale:** There is no federal equivalent of the GOV.UK APIs. Adding an
  agency should mean adding a few lines of YAML rather than writing a
  twenty-fifth bespoke script.
- **Status:** Settled
- **Context:** **`reference/us_sources.yaml` does not exist in the repository**, so
  `eps harvest --country US` reports "no entry in us_sources.yaml" for every
  agency. The US collection has not started. `--start`/`--end` are applied after
  fetching for US sources, not before, so an out-of-window document is downloaded
  and then discarded.

### H-32 — URLs are canonicalised: tracking parameters stripped, trailing slash removed

- **Location:** `[harvest/store.py:canonical_url()]`
- **Decision:** Scheme and host are lowercased, the trailing slash is removed from
  the path, and query parameters beginning `utm_`, `mc_`, `_hs`, `fbclid`, `gclid`,
  `msclkid` or `ref` are dropped. Fragments are discarded entirely.
- **Rationale:** Section 6 requires canonical URLs. The canonical URL is also half
  of the document ID (I-07), so a tracking parameter would change a document's
  identity.
- **Status:** Settled
- **Context:** The `ref` prefix is matched with `startswith`, so a legitimate
  parameter named `reference` or `refresh` would also be stripped.

### H-33 — Raw bytes are stored content-addressed and never re-fetched

- **Location:** `[harvest/store.py:RawStore]`
- **Decision:** Every fetched page is written once to
  `raw/blobs/<first-two-hex>/<sha256>.bin` with an append-only
  `raw/manifest.jsonl` recording URL, digest, byte count, retrieval time and caller
  metadata. Reprocessing reads from disk.
- **Rationale:** This is what makes the corpus frozen and the pipeline replayable:
  the same bytes always produce the same units with the same IDs.
- **Status:** Settled
- **Context:** `eps ingest --no-store` skips the store and hashes the bytes
  directly, which produces the same `doc_id` but leaves no archived copy.

### B-14 — `eps harvest` cannot select any institution

- **Location:** `[build/pipeline.py:load_institutions()]`,
  `[reference/institutions.csv]`
- **Decision:** `load_institutions()` expects columns `institution`, `country`,
  `govuk_slug` and `us_domain`. The shipped `institutions.csv` has
  `institution_id`, `country`, `institution`, `status`, `successor_institution_id`
  and `note`. Its `country` values are `United Kingdom` / `United States`, while
  the CLI's `--country` flag accepts only `UK` / `US`, and no row carries a
  `govuk_slug`. Verified at sweep time: `eps harvest --country UK` prints "No
  institutions matched"; without `--country` every UK row is skipped for having no
  slug.
- **Rationale:** n/a — defect. The reference file and the loader were written
  against different schemas.
- **Status:** Settled *(as a recorded fault; not yet fixed)*
- **Context:** This does not affect any output produced so far, because the UK
  corpus came from the standalone `govuk_harvest.py` and the DfE pilots came from
  `eps ingest`. It does mean the `harvest` verb is currently dead code. Fixing it
  requires either adding `govuk_slug` and two-letter country codes to
  `institutions.csv` or teaching `load_institutions()` the file's actual schema.

## 2. Ingest and normalisation

Entries are ordered by file — `normalise.py` then `harvest/local.py` — and by
position within each file. `normalise.py` is shared by every corpus-building
path, so its rules apply to `ingest` and `harvest` alike.

### I-01 — The segmenter version is part of document identity

- **Location:** `[ingest/normalise.py:SEGMENTER_VERSION]`
- **Decision:** `SEGMENTER_VERSION = "seg-1.0.0"` is recorded on every document and
  copied into every output row. Any change to a segmentation rule requires bumping
  it.
- **Rationale:** Unit IDs are positional. Change how text is split and an old unit
  ID no longer points at the same words, which would silently invalidate every
  stored observation.
- **Status:** Settled
- **Context:** The version has not been bumped despite the attribution rewrite
  (I-09). That rewrite changes `Unit.text` and `char_start` for blockquoted
  paragraphs but not the number or ordering of units, so existing unit IDs still
  resolve — but the *text* they resolve to differs. Worth a decision on whether
  that counts as a segmentation change.

### I-02 — Text is NFC-normalised with a fixed set of character substitutions

- **Location:** `[ingest/normalise.py:normalise_text()]`
- **Decision:** Unicode NFC normalisation; CRLF and CR folded to LF; U+00A0
  non-breaking space replaced with an ordinary space; U+200B zero-width space
  deleted; runs of intra-line whitespace collapsed to one space; every line
  stripped.
- **Rationale:** The same input bytes must always give the same units with the same
  IDs. Character-level variation that carries no meaning would otherwise change
  offsets and hashes.
- **Status:** Settled
- **Context:** This is applied before hashing, so `text_sha256` is a hash of the
  normalised text, not the source.

### I-03 — A single newline inside a block is a space; only blank lines separate paragraphs

- **Location:** `[ingest/normalise.py:normalise_text()]`, `[ingest/normalise.py:_SINGLE_NL]`
- **Decision:** Two or more consecutive newlines collapse to exactly two; a lone
  newline is replaced with a space.
- **Rationale:** A single newline inside a block is soft-wrapping in the source
  markup, not a paragraph break. Collapsing it means a quotation comes out as one
  continuous line.
- **Status:** Settled
- **Context:** This is why the `> ` blockquote marker (B-06) survives: the rewriter
  separates blocks with blank lines, so each quoted block stays its own paragraph.

### I-04 — Block and drop tag sets are fixed lists

- **Location:** `[ingest/normalise.py:_BLOCK_TAGS]`, `[ingest/normalise.py:_DROP_TAGS]`
- **Decision:** Fourteen tags create paragraph boundaries; eight
  (`script`, `style`, `nav`, `header`, `footer`, `aside`, `form`, `noscript`) have
  their entire subtree removed. `<br>` becomes a single newline.
- **Rationale:** Paragraph boundaries are the outer level of the unit-ID scheme and
  the field guide requires them preserved. Dropping navigation and page furniture
  keeps boilerplate out of the corpus.
- **Status:** Settled
- **Context:** If `lxml` cannot parse the fragment at all, the function falls back
  to a regex tag-strip, which produces text with no paragraph structure. Nothing
  flags when that fallback fires.

### I-05 — Sentence splitting uses an explicit abbreviation list, not a model

- **Location:** `[ingest/normalise.py:_ABBREV]`, `[ingest/normalise.py:split_sentences()]`
- **Decision:** A sentence ends at `.`, `!` or `?` followed by whitespace, unless
  the preceding word is one of about 50 listed abbreviations.
- **Rationale:** Deliberately conservative and explicit rather than model-based, so
  it never drifts between runs.
- **Status:** Settled
- **Context:** The list is UK/US government-prose specific (`mp`, `cbe`, `obe`,
  month abbreviations, `u.k`, `u.s`). An unlisted abbreviation splits a sentence in
  two, which changes unit IDs and can make a quotation appear non-contiguous.

### I-06 — Single initials, decimals and numbered lists do not end sentences

- **Location:** `[ingest/normalise.py:_ends_with_abbrev()]`, `[ingest/normalise.py:split_sentences()]`
- **Decision:** A one-character word before a full stop is treated as an initial
  ("J." in "J. D. Vance"). A full stop preceded by a digit and followed by a digit
  is treated as a decimal point or a list marker.
- **Rationale:** Both are common in policy prose and both would otherwise fragment
  a sentence.
- **Status:** Settled
- **Context:** The initial rule is unconditional, so a genuine one-letter sentence
  ending would be merged with the next.

### I-07 — Unit IDs are `D<hash>.Pnnn.Snnn`, and the document ID hashes URL plus raw bytes

- **Location:** `[ingest/normalise.py:segment()]`, `[ingest/normalise.py:make_doc_id()]`
- **Decision:** `doc_id` is `"D"` plus the first ten hex characters of
  `sha256(url + "|" + raw_bytes_hash)`. Units are numbered by paragraph and by
  sentence within that paragraph, both zero-padded to three digits, and carry
  absolute character offsets into the normalised text. Empty paragraphs are skipped
  and do not consume a paragraph number.
- **Rationale:** The ID has to be stable across re-runs and has to name a span the
  quote can be copied from. Hashing the URL together with the bytes means the same
  page fetched twice with identical content gets the same ID.
- **Status:** Settled
- **Context:** Ten hex characters is roughly 40 bits. Collision risk is negligible
  at this corpus size but is not zero and nothing checks for it.

### I-08 — For five document types the whole body is the speaker's own words

- **Location:** `[ingest/normalise.py:SPEAKER_ONLY_TYPES]`
- **Decision:** `speech`, `statement`, `op_ed`, `letter` and `testimony` are
  treated as wholly attributable; every unit is selectable and no structural
  attribution test is applied.
- **Rationale:** For these types the document *is* the speaker talking. There is no
  departmental prose to separate out.
- **Status:** Settled
- **Context:** This set also controls two other rules: cross-paragraph quotation
  (D-02) and whether the quote is trimmed to the material inside quotation marks
  (D-05). `press_release`, `interview_transcript` and `other` fall outside it.

### I-09 — Attribution in mixed documents is structural: a `> ` block under a frame naming the speaker

- **Location:** `[ingest/normalise.py:mark_attribution()]`
- **Decision:** For document types outside `SPEAKER_ONLY_TYPES`, a paragraph is
  attributable only when it begins with the `> ` blockquote marker **and** the
  nearest preceding non-quote paragraph is a frame — a paragraph ending in `:` —
  that names the eligible speaker. With no speaker supplied nothing is
  attributable: the rule fails closed.
- **Rationale:** GOV.UK press releases contain no quotation marks at all; the
  quotation is a `<blockquote>` introduced by a line naming the speaker. Getting
  this wrong is the single largest source of false positives, so it is decided in
  code rather than left to the model.
- **Status:** Settled
- **Context:** This replaced the punctuation-and-cue-word rule that caused B-08 and
  B-09. It depends entirely on the `> ` marker produced by B-06's fix, so it only
  works on `documents_v2`. Applied to the working tree by
  `scripts/patch_attribution.py`, which is uncommitted. In the pilot it raised
  documents producing at least one observation from 4 of 10 to 6 of 10.

### I-10 — A frame must contain every distinctive token of the speaker's name

- **Location:** `[ingest/normalise.py:frame_names_speaker()]`,
  `[ingest/normalise.py:_name_tokens()]`, `[ingest/normalise.py:_NAME_NOISE]`
- **Decision:** The speaker's name is reduced to lowercase alphabetic tokens with
  honorifics, titles and the words "of"/"for" removed, and single characters
  dropped. Every remaining token must appear somewhere in the frame text. A name
  reducing to fewer than two tokens never matches.
- **Rationale:** Surname alone is too loose — a press release may quote a different
  person of the same surname. Requiring all tokens means "Education Secretary
  Bridget Phillipson said:" matches while "Paul Whiteman, general secretary of the
  NAHT, said:" does not.
- **Status:** Settled
- **Context:** The two-token minimum means an officeholder recorded under a title
  alone (for example "Baroness Smith of Cluny" reduces to "smith", "cluny" — two
  tokens, so it passes; but a single-word entry would not) never has any press
  release attributed to them. Matching is substring-based, so a token appearing
  inside a longer word counts.

### I-11 — Consecutive quote paragraphs inherit the frame above them

- **Location:** `[ingest/normalise.py:mark_attribution()]`
- **Decision:** A run of `> ` paragraphs is evaluated once against the frame that
  precedes the run; every paragraph in the run takes the same verdict. A non-quote
  paragraph that does not end in `:` clears the frame.
- **Rationale:** A minister's quotation frequently runs to several blockquoted
  paragraphs under a single introduction.
- **Status:** Settled
- **Context:** A non-quote paragraph *between* two quote blocks resets the frame,
  so a second quotation under an unnamed introduction is correctly excluded.

### I-12 — The `> ` marker is stripped from the unit text and the offset advanced past it

- **Location:** `[ingest/normalise.py:mark_attribution()]`,
  `[ingest/normalise.py:QUOTE_MARKER]`
- **Decision:** Only the first sentence of a quoted block carries the marker. Its
  text has the two characters removed and its `char_start` is advanced by two.
- **Rationale:** The marker is our own insertion, not the department's words.
  Because `reconstruct_quote()` slices `doc.text[char_start:char_end]`, advancing
  the offset puts the marker outside the slice by construction, so it can never
  enter a quotation.
- **Status:** Settled
- **Context:** The marker remains in `doc.text` and therefore in `text_sha256`. A
  quote reconstructed from a `documents_v2` document is a verbatim substring of the
  *rewritten* text, which differs from the GOV.UK page by exactly these markers.

### B-08 — Curly apostrophes were counted as quotation marks

- **Location:** `[ingest/normalise.py:_QUOTE_CHARS]`
- **Decision:** `_QUOTE_CHARS` originally included U+2018 and U+2019. In British
  prose the right single quote **is** the apostrophe, so every possessive
  ("Children's", "leaders'", "Government's") satisfied the quotation test. Fixed by
  restricting the set to `"`, U+201C and U+201D.
- **Rationale:** n/a — defect. `validate.py` had already excluded them for the same
  reason, so the two halves of the pipeline disagreed.
- **Status:** Settled
- **Context:** `_QUOTE_CHARS` is now unreferenced by `mark_attribution()`, which
  uses the structural rule instead (I-09). It survives as a constant; the live
  quote-character set for the build stage is `_OPEN_Q`/`_CLOSE_Q` in `validate.py`
  (D-06).

### B-09 — The old attribution rule marked third-party frames as the speaker's own words

- **Location:** `[ingest/normalise.py:mark_attribution()]`
- **Decision:** The previous rule marked a sentence attributable when it contained
  a quote character **and** either an attribution cue (`said|says|added|told|
  commented|explained|continued|noted|stated`) or opened with a quote character.
  Combined with B-08 this marked the *attribution frames* — the department's own
  words introducing a speaker — as attributable, and never marked the actual
  quotation, which carries no quote characters at all.
- **Rationale:** n/a — defect.
- **Status:** Settled
- **Context:** In the DfE pilot this produced zero observations from six press
  releases, and the sentences it did mark belonged to a union leader, the
  Children's Commissioner and a campaign group. Had the model been less
  conservative, their statements would have entered the dataset under the Secretary
  of State's name — verbatim-exact and undetectable downstream. Replaced by I-09.

### B-07 — The packaged harvesters still call `mark_attribution()` without a speaker

- **Location:** `[harvest/govuk.py:build_document()]`, `[harvest/us.py:build_document()]`
- **Decision:** `scripts/patch_attribution.py` updated only the ingest call site.
  Both harvester call sites still pass two arguments, so `speaker` defaults to
  `None`. Under the fail-closed rule in I-09 that makes **every** unit of every
  harvested press release non-attributable, and therefore every observation from
  such a document is rejected.
- **Rationale:** n/a — defect. The patch script's own docstring names
  `src/eps/ingest/local.py` as its target, a path that does not exist in this
  layout; the file is at `src/eps/harvest/local.py`.
- **Status:** Settled *(as a recorded fault; not yet fixed)*
- **Context:** No output is affected today, because `eps harvest` is separately
  non-functional (B-14) and every corpus so far came through `eps ingest`. It must
  be fixed before the `harvest` verb is used.

### I-13 — The manifest is the source of record for document metadata

- **Location:** `[ingest/local.py:MANIFEST_COLUMNS]`
- **Decision:** Ten columns — `path`, `institution`, `country`, `url`, `title`,
  `doc_type`, `date`, `delivery_status`, `speaker_hint`, `notes` — supplied by
  hand rather than parsed from page markup.
- **Rationale:** Metadata a scraper would read from markup has to come from
  somewhere, and stating it explicitly is more reliable than guessing. The manifest
  is also a citable record of exactly which documents entered the dataset.
- **Status:** Settled
- **Context:** `queue_to_manifest.py` generates this file from the harvest queue
  (M-07), so in practice the values come from GOV.UK by way of the screening log
  rather than from a person.

### I-14 — Manifests are read as UTF-8 with BOM tolerance

- **Location:** `[ingest/local.py:read_manifest()]`
- **Decision:** `encoding="utf-8-sig"`.
- **Rationale:** Excel on Windows saves CSV with a byte-order mark. Read as plain
  UTF-8 the mark stays glued to the first header cell, so `path` is silently read as
  something else and the file appears to be missing a column that is in fact right
  there.
- **Status:** Settled
- **Context:** Recorded in `RUNNING.md` as a fixed fault. The same encoding is used
  by `prepare_extraction.py`, `queue_to_manifest.py`, `check_queue.py` and
  `audit_text_fidelity.py`, but **not** by `pipeline.load_officeholders()` or
  `load_institutions()`, which use plain UTF-8 and would inherit the fault.

### I-15 — Manifest validation is strict by default; `--lenient` skips bad rows

- **Location:** `[ingest/local.py:validate_row()]`, `[ingest/local.py:ingest_manifest()]`,
  `[extract/cli.py:cmd_ingest()]`
- **Decision:** Every row is validated before anything is ingested. Any problem
  aborts the whole run with a list of row numbers and reasons. `--lenient` is
  **off** by default; passing it skips the offending rows and continues, printing
  each to stderr.
- **Rationale:** A missing date or a bad `doc_type` should fail loudly rather than
  produce a quietly wrong row.
- **Status:** Settled
- **Context:** The default matters: a lenient run silently shrinks the corpus, and
  the count of skipped rows appears only on stderr, not in any output file.

### I-16 — `country` must be exactly `US` or `UK`

- **Location:** `[ingest/local.py:validate_row()]`
- **Decision:** Any other value, including `United Kingdom`, is a validation error.
- **Rationale:** Not recorded — confirm with RA.
- **Status:** Settled
- **Context:** `institutions.csv` and `officeholders_2026.csv` both use the long
  form, which is one half of B-14. The manifest and the reference data disagree on
  this and nothing reconciles them.

### I-17 — Delivery status is inferred from the title and the first 2,000 characters

- **Location:** `[ingest/local.py:ingest_row()]`, `[ingest/local.py:_AS_PREPARED]`,
  `[ingest/local.py:_AS_DELIVERED]`
- **Decision:** When the manifest says `unknown`, the title plus the first 2,000
  characters are searched for "as prepared for delivery" or "prepared remarks"
  (→ `as_prepared`), then for "as delivered" or the word "transcript"
  (→ `as_delivered`). Otherwise `unknown` stands.
- **Rationale:** Most US agencies publish "remarks as prepared for delivery", which
  is what the speechwriter wrote, not what was said. It cannot be reconstructed
  later, so it is captured at ingest.
- **Status:** Settled
- **Context:** `as_prepared` is tested first, so a document matching both patterns
  is recorded as prepared. Every DfE pilot document carries `unknown` because
  neither phrase appears in GOV.UK prose.

### I-18 — PDF paragraphs are rebuilt with a short-line heuristic

- **Location:** `[ingest/local.py:_pdf_to_text()]`
- **Decision:** Blank lines start a new block; additionally, a line shorter than 60
  characters that ends in sentence punctuation closes the block it is in.
- **Rationale:** A naive PDF extract runs lines together and destroys the paragraph
  boundaries the unit scheme depends on.
- **Status:** Settled
- **Context:** The 60-character threshold is a guess and is not recorded — confirm
  with RA. No PDF has been ingested in any run to date, so the heuristic is
  untested against real material.

### I-19 — `.docx` ingestion keeps paragraph objects only

- **Location:** `[ingest/local.py:_docx_to_text()]`
- **Decision:** Non-empty `document.paragraphs` are joined with blank lines.
  Tables, headers, footers and footnotes are discarded.
- **Rationale:** Not recorded — confirm with RA.
- **Status:** Settled
- **Context:** Untested against real material; no `.docx` has been ingested.

### I-20 — `speaker_hint` from the manifest drives the attribution rule

- **Location:** `[ingest/local.py:ingest_row()]`
- **Decision:** The manifest's `speaker_hint`, stripped and coerced to `None` when
  blank, is passed as the third argument to `mark_attribution()`.
- **Rationale:** The structural attribution rule (I-09) needs a name to test frames
  against, and at ingest time the manifest is the only place one is available.
- **Status:** Settled
- **Context:** This makes attribution depend on a value that is not validated
  against the officeholder table at ingest time. A misspelled `speaker_hint`
  produces a corpus with no attributable press-release units and no error message.
  `queue_to_manifest.py` fills it from the harvest's `expected_officeholder` column
  (M-07), so in practice it is machine-generated.

### I-21 — Source files are copied into the run's raw store unless `--no-store` is given

- **Location:** `[extract/cli.py:cmd_ingest()]`
- **Decision:** By default `eps ingest` writes every source file's bytes into
  `runs/<name>/raw/` through `RawStore`. `--no-store` skips it.
- **Rationale:** Makes a run self-contained: the corpus travels with the outputs
  rather than depending on paths on one machine.
- **Status:** Settled
- **Context:** Both DfE manifests use absolute Windows paths under
  `C:\Users\xavif\...`, so without the raw store a run directory would not be
  reproducible on another machine.

## 3. Manifest / prepare extraction

Ordered by execution: `prepare_extraction.py` builds the queue, `check_queue.py`
gates it, `queue_to_manifest.py` translates it into the ingest manifest.

### M-01 — Duplicates are resolved by attribution strength, ties broken alphabetically

- **Location:** `[manifest/prepare_extraction.py:choose_primary()]`,
  `[manifest/prepare_extraction.py:ATTRIBUTION_RANK]`
- **Decision:** Rows sharing a URL are grouped and ranked
  `linked` < `name_in_body` < `linked_mismatch` < `no_match` <
  `no_officeholder_record`, with the institution name as the tiebreaker. The first
  row wins and is marked `is_primary = yes`.
- **Rationale:** The guide excludes duplicate versions of the same statement. The
  primary should be the department whose head is actually linked as speaker; ties
  are broken alphabetically so the choice is reproducible rather than dependent on
  harvest order.
- **Status:** Settled
- **Context:** 181 URLs appeared under more than one department (joint
  announcements), creating 217 duplicate rows.

### M-02 — Duplicate rows are retained in the screening log, not deleted

- **Location:** `[manifest/prepare_extraction.py:main()]`
- **Decision:** Non-primary rows get `is_primary = no`, `duplicate_of = <primary
  institution>` and, if no reason was already set,
  `exclusion_reason = duplicate_of_another_institution`.
- **Rationale:** Section 6 requires every page inspected to stay on record.
- **Status:** Settled
- **Context:** An existing `exclusion_reason` is never overwritten, so a
  content-fetch failure that is also a duplicate keeps the fetch failure as its
  reason.

### M-03 — A document enters the queue if it is primary, `linked`, and at least 40 words

- **Location:** `[manifest/prepare_extraction.py:main()]`
- **Decision:** Three tests, applied in order: primary, attribution in the accepted
  set, then `word_count >= --min-words` (default 40).
- **Rationale:** Long enough to contain a policy statement, attributable to an
  eligible speaker, and not a duplicate.
- **Status:** Settled
- **Context:** 13 documents were excluded as too short. The rationale for 40
  specifically is not recorded — confirm with RA. Word count is
  `len(text.split())` computed at harvest time on the **original** text, so the
  count for a `documents_v2` file may differ slightly from the value the filter
  used.

### M-04 — `name_in_body` documents are excluded by default

- **Location:** `[manifest/prepare_extraction.py:main()]`
- **Decision:** The accepted attribution set is `{"linked"}`.
  `--include-name-in-body` widens it, and was not used.
- **Rationale:** `name_in_body` is a triage flag, not a confirmed attribution
  (H-12).
- **Status:** Settled
- **Context:** 110 documents are affected. They stay in the screening log and could
  be added later without re-harvesting.

### M-05 — No document-type filter is applied when building the queue

- **Location:** `[manifest/prepare_extraction.py:main()]`
- **Decision:** `--types` defaults to `None`, so every type that survived H-01
  reaches the queue.
- **Rationale:** Narrowing at this stage would have to be undone to widen again;
  the type breakdown is reported instead so the composition is visible.
- **Status:** Settled
- **Context:** The resulting queue is 584 press releases, 135 news stories, 75
  speeches, 28 oral statements, 26 correspondence, 14 written statements and 6
  government responses. **719 of 868 are press releases or news stories**, so most
  observations will derive from short embedded quote blocks rather than sustained
  argument. See S-14.

### M-06 — The screening log is rewritten in place, with a one-time backup

- **Location:** `[manifest/prepare_extraction.py:main()]`
- **Decision:** `prepare_extraction.py` adds `is_primary` and `duplicate_of`
  columns and overwrites the log. A `.predupe.bak` copy is made the first time and
  never overwritten afterwards.
- **Rationale:** Not recorded — confirm with RA. The one-time backup preserves the
  pre-deduplication state across repeated runs.
- **Status:** Settled
- **Context:** `screening_log.csv.predupe.bak` is present in `harvest-v3/`.
  Re-running after an intervening manual edit would silently keep the original
  backup, so the backup is not necessarily the state immediately before the last
  run.

### M-10 — `check_queue.py` is a pre-flight gate that exits non-zero on any failure

- **Location:** `[manifest/check_queue.py:def render(]`
- **Decision:** Eight checks — document types, dates in window, duplicate live
  URLs, institution coverage against the guide's 24, file existence and
  non-emptiness, overlapping officeholder spells, one-and-only-one eligible spell
  per row, and agreement between the queue's speaker and the table's. Any failure
  exits 1.
- **Rationale:** Every check either passes silently or prints a numbered problem,
  before anything is ingested or any money is spent.
- **Status:** Settled
- **Context:** Purely advisory — nothing in the pipeline invokes it automatically.

### M-11 — `check_queue.py` treats `end_date` as EXCLUSIVE

- **Location:** `[manifest/check_queue.py:main()]` — the `--end-date-exclusive`
  argument
- **Decision:** `end_ok` is `d < s["end"]` by default.
- **Rationale:** It resolves a same-day handover to exactly one officeholder, and
  the check that reports overlapping spells says so explicitly: "Treating end_date
  as exclusive resolves a same-day handover; anything wider is a data error."
- **Status:** Pending PI decision
- **Context:** Directly contradicts H-14 and D-10, both of which are inclusive. The
  flag is declared with `action="store_true", default=True`, so it cannot be turned
  off from the command line — the inclusive branch is unreachable. See S-07.

### M-12 — The collection window is hardcoded in the pre-flight check

- **Location:** `[manifest/check_queue.py:WINDOW_START]`,
  `[manifest/check_queue.py:WINDOW_END]`
- **Decision:** `2026-01-01` to `2026-07-31`, inclusive at both ends, as module
  constants.
- **Rationale:** Not recorded — confirm with RA.
- **Status:** Settled
- **Context:** The harvest takes `--start`/`--end` (defaults matching these), so
  extending the window to January 2025 (S-01) means editing this file as well as
  re-running the harvest.

### M-13 — The pre-flight check carries its own copy of the guide's 24 institutions

- **Location:** `[manifest/check_queue.py:GUIDE_UK_INSTITUTIONS]`
- **Decision:** A hardcoded list of the 24 UK ministerial departments. Institutions
  present in the queue but absent from this list are reported as "name mismatch, or
  a new department"; institutions on the list with zero documents are reported as a
  Section 5 failure.
- **Rationale:** The check has to compare against the guide rather than against
  whatever the harvest produced, or it cannot detect a missing department.
- **Status:** Settled
- **Context:** This is the **third** copy of the canonical list in the repository,
  after `govuk_harvest.CANONICAL_UK_DEPARTMENTS` (25 entries, including DBIST) and
  `reference/institutions.csv` (24 UK rows plus 24 US). They can drift
  independently, and already have: DBIST will be reported as unexpected, and the
  three genuine zeros (S-10) will be reported as Section 5 failures on every run.

### M-07 — The manifest's document type, speaker and delivery status are taken from fixed queue columns

- **Location:** `[manifest/queue_to_manifest.py:row_to_manifest()]`
- **Decision:** `doc_type` ← `normalised_document_type`; `speaker_hint` ←
  `expected_officeholder`; `title` ← `document_title`; `delivery_status` is
  hardcoded to `"unknown"`.
- **Rationale:** The two files describe the same documents in different
  vocabularies; this is the translation and nothing else. Anything dropped is
  reported rather than silently discarded.
- **Status:** Settled
- **Context:** Hardcoding `unknown` means the delivery-status inference in I-17
  runs on every document, and GOV.UK's own `delivery_type` field (H-29) is never
  consulted on this path. Because `expected_officeholder` is the join result rather
  than the GOV.UK-linked name, a row where the two disagree carries the table's
  name as the hint.

### M-08 — Pilot sampling defaults to `spread`, with the shortest documents as negative controls

- **Location:** `[manifest/queue_to_manifest.py:pick()]`,
  `[manifest/queue_to_manifest.py:main()]`
- **Decision:** `--sample` defaults to `spread` — round-robin across document
  types, taking the longest remaining document within each type. `first` and
  `longest` are the alternatives. `--plus-shortest N` appends the N shortest
  remaining documents.
- **Rationale:** A spread sample exercises every attribution path; the shortest
  documents are negative controls that should yield nothing.
- **Status:** Settled
- **Context:** Both DfE manifests hold 10 documents. This is a pilot-selection
  method, not a probability sample — if the Section 11 review sampler is built on
  it, the probability each document was drawn with will not be recoverable.

### M-09 — `queue_to_manifest.py` defaults `country` to `UK`

- **Location:** `[manifest/queue_to_manifest.py:main()]`
- **Decision:** `--country` defaults to `"UK"` and is written into every row.
- **Rationale:** Not recorded — confirm with RA. The queue itself carries no
  country column.
- **Status:** Settled
- **Context:** A US queue processed without `--country US` would be silently
  labelled UK, and would then pass `validate_row()` (I-16) because `UK` is a legal
  value.

## 4. Extraction

Ordered by file: `extract.py`, then `providers.py`, then the `extract` verb in
`cli.py`.

### E-01 — The model returns unit IDs; it never writes quote text

- **Location:** `[extract/extract.py:EXTRACT_SYSTEM]`,
  `[extract/extract.py:select_units()]`
- **Decision:** The model's output schema is
  `{"observations": [{"unit_ids": [...], "anchor": ..., "reason": ...}]}`. The
  quote is reconstructed by copying character ranges out of the frozen document in
  `validate.py`.
- **Rationale:** Quote fidelity becomes a property of the code rather than a metric
  to be measured afterwards. There is no code path by which model-generated text
  reaches the `direct_quote` column.
- **Status:** Settled
- **Context:** This is the design decision the whole pipeline is built around. The
  optional `anchor` (E-08) is the single exception, and it is exact-matched against
  the frozen text or the observation is dropped.

### E-02 — JEL classification is a two-stage selection from the frozen taxonomy

- **Location:** `[extract/extract.py:classify()]`,
  `[extract/extract.py:_refine()]`
- **Decision:** First the model picks a major category from the full list of
  majors; then, within that branch only, it picks a subcategory and optionally a
  detailed code. Both are checked against the taxonomy before use.
- **Rationale:** Selection from a fixed list makes an invented code impossible
  rather than merely discouraged, and stops the model reproducing AEA titles from
  memory.
- **Status:** Settled
- **Context:** Titles are always filled from the taxonomy (`fill_titles`), never
  taken from the model. See B-10 for the level check this stage is missing.

### E-03 — The model is not told who is speaking, by default

- **Location:** `[extract/extract.py:IDENTITY_MODES]`,
  `[extract/extract.py:build_user_message()]`,
  `[extract/cli.py:main()]` — `--identity-mode`
- **Decision:** `blind` is the default: the prompt carries document type and date
  only, plus a note stating the withholding is deliberate and that first-person
  plural statements should be read as the speaker's own words. `full` adds
  institution, country, eligible speaker and title.
- **Rationale:** There is published evidence that LLMs use party cues when
  evaluating political statements, and the pipeline already knows the speaker from
  the officeholder join, so the model does not need to be told.
- **Status:** Settled
- **Context:** The identity mode is part of the cache key (E-13) and is recorded on
  every output row, so `blind` and `full` runs over the same corpus do not collide
  and can be diffed. Automatic diffing is not built.

### E-04 — Document type and date are kept even in blind mode

- **Location:** `[extract/extract.py:build_user_message()]`
- **Decision:** Both are always in the header.
- **Rationale:** Type governs the attribution rules the model is asked to respect,
  and the date is needed to read tense correctly.
- **Status:** Settled
- **Context:** Document type is also a fairly strong proxy for institution in a
  UK-only corpus, so blinding is partial rather than complete.

### E-05 — Prompt provenance is recorded twice: a hand-set label and an automatic hash

- **Location:** `[extract/extract.py:PROMPT_VERSION]`,
  `[extract/extract.py:prompt_fingerprint()]`
- **Decision:** `PROMPT_VERSION` is currently `"P2-units-blind"`, set by hand.
  `prompt_sha` is the first 12 hex characters of
  `sha256(EXTRACT_SYSTEM + JEL_SYSTEM)`, computed automatically. Both appear on
  every output row.
- **Rationale:** The label may be forgotten; the hash cannot be. Two rows sharing a
  fingerprint came from identical prompts, whether or not anyone remembered to
  relabel.
- **Status:** Settled
- **Context:** `prompts/` archives the wording of versions that left the machine.
  It currently holds only a README — no version has been archived, so the pilot's
  prompt text exists only as source code and in the response cache.

### E-06 — What qualifies as an economics-relevant policy statement lives in one prompt string

- **Location:** `[extract/extract.py:EXTRACT_SYSTEM]`
- **Decision:** A passage qualifies when the eligible speaker expresses a policy
  position, priority, proposal, commitment, target, implementation choice or causal
  belief with a substantive connection to economic behaviour, institutions,
  markets, incentives, resource allocation, distribution, government activity or
  measurable economic outcomes.
- **Rationale:** This restates §4/§5/§8 of the field guide. Keeping it as one
  editable string means tuning the criteria never touches the validators.
- **Status:** Settled
- **Context:** This is the only stage in the pipeline that exercises judgement.
  There is no threshold or keyword list to inspect; the prompt text *is* the
  criterion.

### E-07 — Seven categories are explicitly excluded

- **Location:** `[extract/extract.py:EXTRACT_SYSTEM]`
- **Decision:** Ceremonial content; general values with no mechanism; passing
  mentions of growth/jobs/investment/cost/efficiency with no position or causal
  claim; partisan criticism without the speaker's own position; description of a
  policy the speaker opposes unless they state an alternative; purely legal,
  diplomatic or security content; and anything spoken by an interviewer, host or
  quoted third party.
- **Rationale:** These are the false-positive families the guide names. The last is
  also enforced structurally by I-09, so the prompt and the code agree.
- **Status:** Settled
- **Context:** The prompt also states "If nothing qualifies, return an empty list.
  Documents that produce nothing are expected and useful; do not stretch to find
  something." Four of ten pilot documents produced nothing.

### E-08 — The optional anchor is exact-matched or the observation is dropped

- **Location:** `[extract/extract.py:EXTRACT_SYSTEM]`,
  `[build/validate.py:reconstruct_quote()]`
- **Decision:** The model may supply an `anchor` — an exact substring copied
  character-for-character from the selected units — to narrow the quote to a
  clause. If it is not found in the reconstructed quote the observation is rejected
  with `anchor phrase does not appear exactly in the units`.
- **Rationale:** It allows a sub-sentence quote without letting the model author
  text: the anchor is only ever used to index into the frozen text.
- **Status:** Settled
- **Context:** This is the largest single rejection category in both pilots — 4 of
  8 rejections in `dfe-pilot`, 2 of 5 in `dfe-v2`. All the failures are single-unit
  selections, which suggests the model is paraphrasing or re-punctuating rather
  than copying. Worth investigating before the full run.

### E-09 — Non-attributable units are shown to the model, labelled as unselectable

- **Location:** `[extract/extract.py:render_units()]`
- **Decision:** Every unit is rendered as `<unit_id>: <text>`, with
  `  [not selectable: not the speaker's words]` appended when
  `attributable` is false. Paragraph breaks are marked by a blank line.
- **Rationale:** The surrounding prose is context the model needs to read the
  quotation correctly, but it must not be selectable.
- **Status:** Settled
- **Context:** The label is advisory to the model; `reconstruct_quote()` enforces
  it independently (D-04), so a model that ignores the label has its observation
  rejected rather than accepted.

### E-10 — Documents are truncated at 120,000 characters

- **Location:** `[extract/extract.py:render_units()]`
- **Decision:** Rendering stops once the accumulated line length exceeds 120,000
  characters and appends `[... document truncated ...]`.
- **Rationale:** Not recorded — confirm with RA. Presumed a context-window guard.
- **Status:** Settled
- **Context:** Truncation is invisible downstream: nothing records that a document
  was truncated, and the screening log shows such a document as ordinarily
  processed. Longest documents are also the ones `--sample longest` selects.

### E-11 — Every model call is made at temperature 0

- **Location:** `[extract/providers.py:AnthropicProvider]`,
  `[extract/providers.py:MistralProvider]`
- **Decision:** `temperature=0` on both providers, not exposed as a flag.
- **Rationale:** Not recorded — confirm with RA. Consistent with the pipeline's
  reproducibility aim.
- **Status:** Settled
- **Context:** Temperature 0 is not a determinism guarantee from any provider,
  which is why the response cache (E-13) exists.

### E-12 — Token budgets are 3,000 for selection and 500/400 for JEL

- **Location:** `[extract/extract.py:select_units()]`,
  `[extract/extract.py:classify()]`,
  `[extract/extract.py:_refine()]`
- **Decision:** `max_tokens` is 3,000 for unit selection, 500 for the major-category
  choice and 400 for refinement. `Extractor._call()` defaults to 2,000.
- **Rationale:** Not recorded — confirm with RA.
- **Status:** Settled
- **Context:** A truncated JSON response raises in `_parse_json()`, which
  `cmd_extract` catches per document (E-19), so the document silently yields no
  candidates.

### E-13 — Responses are cached content-addressed, and the cache is the replication artefact

- **Location:** `[extract/extract.py:ResponseCache]`,
  `[extract/extract.py:_call()]`
- **Decision:** The cache key is a SHA-256 of provider name, model ID, system
  prompt, user message, `prompt_version` and `identity_mode`. Hits replay; misses
  call the API and are written back.
- **Rationale:** Committing the cache is what makes a third party's re-run
  byte-identical: they replay it rather than re-querying a model whose outputs are
  not bitwise reproducible. It also means `build` can be iterated indefinitely for
  free.
- **Status:** Settled
- **Context:** **The cache is not committed.** `runs/` is untracked in this
  repository, so the stated replication guarantee does not currently hold. There is
  no `.gitignore`; the exclusion is by omission rather than by rule. Note also that
  because the prompt text is part of the key, editing `EXTRACT_SYSTEM` invalidates
  the cache by itself — bumping `PROMPT_VERSION` is not required for a change to
  take effect.

### E-14 — The default model is `claude-sonnet-4-6`

- **Location:** `[extract/extract.py:DEFAULT_MODEL]`
- **Decision:** Used unless `--model` overrides it. `--provider mistral` switches
  the default to `mistral-large-latest`.
- **Rationale:** Not recorded — confirm with RA.
- **Status:** Settled
- **Context:** The model ID is part of the cache key and is recorded on every
  output row, so a dataset built with one model and re-checked with another is
  never ambiguous.

### E-15 — Provider choice is isolated behind a one-method interface

- **Location:** `[extract/providers.py:ModelProvider]`,
  `[extract/providers.py:PROVIDERS]`
- **Decision:** A provider is anything with `.name` and
  `.call(system, user, max_tokens) -> str`. Anthropic, Mistral and a network-free
  `FakeProvider` all satisfy it. Nothing in extraction, validation or assembly
  knows which one ran.
- **Rationale:** Switching providers should mean passing a different object, not
  touching extraction logic. `FakeProvider` is what makes the pipeline testable at
  all.
- **Status:** Settled
- **Context:** The Mistral default model name is flagged in the source as a
  placeholder — Mistral's catalogue moves quickly, so it should be confirmed
  against Mistral's own documentation before being relied on.

### E-16 — The model's stated reason is recorded but treated as non-evidence

- **Location:** `[extract/extract.py:select_units()]`,
  `[build/models.py:Observation]`,
  `[build/assemble.py:observation_row()]`
- **Decision:** The prompt asks for a reason of under ten words; it is truncated at
  200 characters and written to the `model_reason` column of the internal table
  only.
- **Rationale:** It is generated *after* the selection, so it is a plausible account
  of the choice rather than evidence about how the choice was made. Recorded for
  human review, never as provenance.
- **Status:** Settled
- **Context:** It does not appear in the release table.

### E-17 — At most two secondary JEL codes, each in a different major category

- **Location:** `[extract/extract.py:classify()]`
- **Decision:** The secondary list is truncated to two, and a secondary assignment
  is discarded if it is empty or shares a major code with the primary.
- **Rationale:** The prompt asks for a secondary only when there is an additional,
  substantively important economic dimension — "At most two. Fewer is better." The
  same-major test stops a secondary restating the primary at a different depth.
- **Status:** Settled
- **Context:** `validate_jel()` re-checks the count of two independently (D-20).

### E-18 — JEL classification runs on the reconstructed quote, not on the model's own selection text

- **Location:** `[extract/extract.py:def extract(]`
- **Decision:** `reconstruct_quote()` is called before classification. If it
  rejects, no classification is attempted and the observation carries an empty
  assignment.
- **Rationale:** The model should classify exactly the text that will appear in the
  dataset — including any trimming to the quoted span (D-05) or narrowing to an
  anchor (E-08).
- **Status:** Settled
- **Context:** In `full` identity mode the document title is passed as additional
  context to the classifier; in `blind` mode it is not.

### E-19 — A document that raises during extraction yields no candidates and the run continues

- **Location:** `[extract/cli.py:cmd_extract()]`
- **Decision:** Any exception is printed to stderr and the document is recorded
  with an empty candidate list. Documents with no resolvable speaker are skipped
  the same way.
- **Rationale:** Not recorded — confirm with RA. A single malformed response should
  not lose an expensive run.
- **Status:** Settled
- **Context:** The screening log cannot distinguish "no qualifying passage" from
  "extraction raised" — both appear as `no qualifying passage` (D-13). The stderr
  line is the only record.

### E-20 — Selected JEL codes are verified against the taxonomy before use

- **Location:** `[extract/extract.py:_refine()]`
- **Decision:** A subcategory not present in the taxonomy is discarded; a detailed
  code is discarded if it is absent or if its recorded parent is not the chosen
  subcategory.
- **Rationale:** Selection from a fixed list, then verified — belt and braces
  against a model that returns a plausible-looking code.
- **Status:** Settled
- **Context:** Originally this checked membership and parentage but not level,
  which is B-10. It now checks level as well.

### B-10 — `_refine()` did not check a code's level, so a detailed code in the subcategory slot killed the observation

- **Location:** `[extract/extract.py:_refine()]`
- **Decision:** The refinement prompt shows subcategories and detailed codes in one
  indented list and asks for `{"sub": ..., "detailed": ...}`. The model sometimes
  returns a three-character code such as `J13` or `J24` in the `sub` slot.
  `_refine()` accepts it because it exists in the taxonomy, and the level mismatch
  is caught later by `JELTaxonomy.check()`, which rejects the **whole observation**
  with `JEL classification failed validation: 'J13' is not a level-2 code`.
  **Fixed in `694b662`:** `_refine()` now demotes a detailed code found in the
  `sub` slot, recovers its parent, and checks levels explicitly rather than only
  membership and parentage. Input it cannot repair degrades to a coarser
  assignment — major-only at worst — instead of to no observation.
- **Rationale:** n/a — defect. `_refine()` has the taxonomy in hand, so the slip
  is repairable at the point it occurs rather than fatal several stages later.
- **Status:** Settled
- **Context:** Three of eight rejections in `dfe-pilot` and two of five in
  `dfe-v2`. Every one of them discarded a quotation that had already passed every
  structural check — a valid observation lost to a recoverable classification slip.
  The fix was verified against the full 998-code taxonomy on the two codes that
  actually failed (`J13` → `J/J1/J13`, `J24` → `J/J2/J24`) plus seven adjacent
  cases; correct model responses pass through unchanged. **The two pilot runs
  still hold their pre-fix output** — `_refine()` runs during `extract`, so
  `runs/dfe-v2` needs `extract` and `build` re-run before the recovered
  observations appear. Not yet done: unit selection replays from the cache, but
  the JEL calls may re-fire, because the taxonomy grew from 87 codes to 998
  (R-13) and the code list is part of the cache key.

### B-11 — `extract` reported zero candidates for every document whose speaker came from the manifest

- **Location:** `[extract/cli.py:cmd_extract()]`, `[build/validate.py:resolve_speaker()]`
- **Decision:** `extract` consulted `officeholders.csv` alone and silently skipped
  every document whose speaker was supplied by `speaker_hint`, printing no error.
  Fixed by routing extraction through `resolve_speaker()`, which falls back to the
  manifest.
- **Rationale:** n/a — defect.
- **Status:** Settled
- **Context:** Recorded in `RUNNING.md`'s troubleshooting table. Because
  `officeholders.csv` is currently empty (R-18), every pilot document resolved its
  speaker from the manifest — so this fault would have blocked the pilot entirely.
  The fix is already in the committed code.

## 5. Dataset build

Ordered by execution: quote reconstruction and validation in `validate.py`,
speaker resolution, deduplication, then assembly in `assemble.py` and
orchestration in `pipeline.py`.

### D-01 — The quote is a character-range copy from the frozen text

- **Location:** `[build/validate.py:reconstruct_quote()]`
- **Decision:** `doc.text[units[0].char_start : units[-1].char_end]` — not a join
  of the individual unit texts.
- **Rationale:** Slicing preserves the original inter-sentence spacing verbatim; a
  join would normalise it and the result would no longer be a substring of the
  source.
- **Status:** Settled
- **Context:** This is what makes `verify_quote_in_source()` (D-08) an identity
  rather than a hope.

### D-02 — Cross-paragraph quotes are allowed for speeches, not for press releases

- **Location:** `[build/validate.py:reconstruct_quote()]` — `allow_cross_para`
- **Decision:** A quotation may span consecutive paragraphs when the document type
  is in `SPEAKER_ONLY_TYPES`. For every other type a span crossing a paragraph
  boundary is rejected with `unit_ids span a paragraph boundary`.
- **Rationale:** GOV.UK speeches use very short paragraphs, so a single policy claim
  often runs across three or four; the old rule rejected every such passage. Press
  releases keep the stricter rule because two consecutive blockquote paragraphs can
  carry two separate remarks, and `trim_to_quoted_span()` takes the **outermost**
  quote marks — a joined span would silently return `A." She added: "B` with the
  department's attribution frame inside the quotation.
- **Status:** Settled
- **Context:** Applied by `scripts/patch_cross_paragraph.py`, which is uncommitted.
  The prompt still tells the model "Units must be contiguous and within a single
  paragraph" (E-06), so the code is now more permissive than the instruction.

### D-03 — Contiguity is checked with paragraph-aware bounds

- **Location:** `[build/validate.py:reconstruct_quote()]` — `_bounds`
- **Decision:** Two units are contiguous when they are adjacent sentences of the
  same paragraph, or when the first is the last sentence of its paragraph and the
  second is the first sentence of the immediately following paragraph. Bounds are
  computed from the whole document, not from the selected units.
- **Rationale:** `sent_idx` restarts at 1 inside each paragraph, so lifting the
  paragraph rule without rewriting the contiguity check would let through spans
  that skip material. Taking bounds from the whole document stops a skipped
  sentence masquerading as a paragraph break.
- **Status:** Settled
- **Context:** One rejection in each pilot run is `unit_ids are not contiguous`,
  where the model skipped an intervening unit.

### D-04 — Every unit in a quote must be attributable

- **Location:** `[build/validate.py:reconstruct_quote()]`
- **Decision:** If any selected unit has `attributable = False` the observation is
  rejected with `passage is not attributable to the speaker`.
- **Rationale:** Enforces I-09 in code, independently of whether the model
  respected the `[not selectable]` labels in the prompt.
- **Status:** Settled
- **Context:** Neither pilot produced a rejection under this rule, which means the
  model respected the labels in every case.

### D-05 — Press-release quotes are trimmed to the material inside the outermost double quotes

- **Location:** `[build/validate.py:trim_to_quoted_span()]`
- **Decision:** For document types outside `SPEAKER_ONLY_TYPES`, the reconstructed
  span is narrowed to the text between the first opening and the last closing
  double quote. If there is no balanced pair the input is returned unchanged.
- **Rationale:** In a press release the selectable sentence usually carries an
  attribution frame — `The Secretary of State said: "..."`. That frame is the
  department's words, not the speaker's.
- **Status:** Settled
- **Context:** GOV.UK press releases carry no quotation marks at all (B-06), so on
  this corpus the function almost always returns its input unchanged and the frame
  is excluded structurally by I-09 instead. It remains live for sources that do use
  quotation marks.

### D-06 — Apostrophes are excluded from the quote-character set

- **Location:** `[build/validate.py:_OPEN_Q]`, `[build/validate.py:_CLOSE_Q]`
- **Decision:** Only `"`, U+201C and U+201D count as quotation marks.
- **Rationale:** Single quotes are ambiguous with possessives and contractions, and
  a mis-trim would silently corrupt the quote.
- **Status:** Settled
- **Context:** `validate.py` had this right from the start; `normalise.py` did not,
  which is B-08.

### D-07 — Quotes must be between 25 and 1,200 characters

- **Location:** `[build/validate.py:MIN_QUOTE_CHARS]`,
  `[build/validate.py:MAX_QUOTE_CHARS]`, `[extract/cli.py:main()]`
- **Decision:** Defaults 25 and 1,200, overridable per call and from the CLI with
  `--min-quote-chars` / `--max-quote-chars`.
- **Rationale:** The lower bound catches fragments, not policy content: real
  commitments are often short ("We will cap fees at 9,000 pounds."), so it is kept
  low deliberately.
- **Status:** Settled
- **Context:** Both bounds are measured **after** anchoring and trimming, so a long
  passage narrowed by a short anchor can fail the minimum. Neither pilot produced a
  length rejection.

### D-08 — Every reconstructed quote is re-checked as a substring of the source

- **Location:** `[build/validate.py:verify_quote_in_source()]`
- **Decision:** `quote in doc.text`. Failure sets
  `reject_reason = "quote not found in source (internal error)"`.
- **Rationale:** Belt and braces. It should never fail; asserting it anyway is what
  turns a silent corruption into a visible one.
- **Status:** Settled
- **Context:** Marked `pragma: no cover` — it is not exercised by the test suite.

### D-09 — Speaker resolution prefers the officeholder table and warns on disagreement

- **Location:** `[build/validate.py:resolve_speaker()]`
- **Decision:** The officeholder table is consulted first; the manifest's
  `speaker_hint` is the fallback. When both exist and differ case-insensitively,
  the table wins and a warning naming both values and the date is returned. The
  route taken is recorded as `speaker_source` on every screening row.
- **Rationale:** The table is an eligibility check as well as a lookup — no match
  means the document is out of scope. The hint saves building the table for
  hand-picked documents, at the cost of that check. A disagreement almost always
  means a wrong date somewhere.
- **Status:** Settled
- **Context:** Both pilot runs report `speaker_sources: {"manifest": 10}` — every
  document resolved from the manifest, so no eligibility check was applied to any
  observation currently in the repository. See R-18.

### D-10 — `OfficeholderTable` treats `end_date` as inclusive and returns the first match

- **Location:** `[build/validate.py:eligible_speaker()]`
- **Decision:** Institution is matched case-insensitively on the stripped name; a
  spell covers a date when `start <= on` and `on <= end`; the first matching row in
  file order is returned.
- **Rationale:** Not recorded — confirm with RA.
- **Status:** Pending PI decision
- **Context:** Inclusive, like H-14, and contradicting M-11 and R-11. The
  first-match rule means that on a handover date the answer depends on row order in
  the CSV — silently, with no warning. `check_queue.py` would report the same
  situation as two matches and fail (M-10). See S-07.

### D-11 — Duplicate quotes are dropped by normalised fingerprint, first occurrence kept

- **Location:** `[build/validate.py:dedupe()]`, `[build/validate.py:_fingerprint()]`
- **Decision:** The quote is lowercased, everything outside `[a-z0-9 ]` replaced
  with a space, and whitespace collapsed. A repeat fingerprint is marked invalid
  with `duplicate of an earlier observation`; an empty fingerprint is always kept.
- **Rationale:** Government communications reuse ministerial quotes across
  documents — a speech republished on several pages should be one observation.
- **Status:** Settled
- **Context:** Deduplication runs **within one document at a time**:
  `validate_observations()` is called per document from `build()`, so a quote
  repeated across two documents is not caught. That is the recycled-quote question
  in S-03, and it is not yet implemented anywhere.

### D-12 — Rejected candidates are written out with the rule that rejected them

- **Location:** `[build/assemble.py:write_reject_log()]`, `[build/pipeline.py:build()]`
- **Decision:** `rejected.csv` records `doc_id`, `url`, `unit_ids`, `anchor`,
  `reject_reason`, `model_reason` and full provenance for every candidate that
  failed validation.
- **Rationale:** Every validator guards precision; a rejection is a decision the
  pipeline made and needs to be inspectable.
- **Status:** Settled
- **Context:** This file is how B-10 was diagnosed.

### D-13 — Every document gets a screening row, with a three-level exclusion ladder

- **Location:** `[build/pipeline.py:build()]`, `[build/models.py:ScreeningRow]`
- **Decision:** One row per document regardless of outcome. `exclusion_reason` is
  set to a speaker-missing message when no speaker resolved, else "no qualifying
  passage" when the model returned nothing, else "all candidate passages failed
  validation" when everything was rejected, else empty.
- **Rationale:** A genuine zero must be distinguishable from a document that was
  never processed (Section 6).
- **Status:** Settled
- **Context:** `prompt_version` and `model_id` on the screening row are taken from
  the **first** observation only, so a document with no candidates records neither
  — even though a model call was made for it.

### D-14 — The release table is a projection of a wider internal table, and has eight columns

- **Location:** `[build/assemble.py:RELEASE_COLUMNS]`,
  `[build/assemble.py:INTERNAL_COLUMNS]`
- **Decision:** `dataset.csv` carries `agency`, `speaker`, `document_title`,
  `document_type`, `date`, `url`, `direct_quote`, `economics_topics`.
  `observations_internal.csv` adds JEL at all three levels, hashes, provenance and
  the model's reason. Both are written from the same row dictionaries.
- **Rationale:** The release format can change without re-running anything.
- **Status:** Settled
- **Context:** Section 6 specifies **nine** columns; the ninth is the 0.00–1.00
  relevance score, deferred by design (S-12). The release table is therefore
  incomplete against the spec until that is built, and the note in the source says
  so explicitly.

### D-15 — `economics_topics` gives the most specific level available, semicolon-separated

- **Location:** `[build/assemble.py:_topics()]`
- **Decision:** For the primary and each secondary assignment, the detailed code is
  used if present, else the subcategory, else the major, formatted as
  `J24 — Human Capital; Skills; ...`. Labels are joined with "; ".
- **Rationale:** Section 7's format.
- **Status:** Settled
- **Context:** The AEA's own titles contain semicolons, so the field's separator
  also occurs inside its values. Anyone splitting the column on ";" will
  over-split. The internal table's separate code columns are the safe parse.

### D-16 — Secondary JEL codes are recorded at subcategory level only

- **Location:** `[build/assemble.py:observation_row()]`
- **Decision:** `jel_secondary_1` and `jel_secondary_2` take `sub_code` and
  `sub_title`. Any detailed code chosen for a secondary is discarded from the
  internal table.
- **Rationale:** Not recorded — confirm with RA.
- **Status:** Settled
- **Context:** `_topics()` (D-15) does use the detailed level for secondaries, so
  the release column and the internal columns can disagree about the same
  assignment. A secondary with a subcategory but no detailed code appears blank in
  the internal columns only if the subcategory itself is empty.

### D-17 — Output rows are sorted on a fixed key

- **Location:** `[build/assemble.py:SORT_KEY]`
- **Decision:** `country`, `agency`, `date`, `url`, `unit_ids`, all compared as
  strings.
- **Rationale:** A diff between two runs should show real disagreement rather than
  ordering noise.
- **Status:** Settled
- **Context:** The screening log uses its own sort (`country`, `institution`,
  `pub_date`, `url`); `rejected.csv` is unsorted and follows document order.

### D-18 — Documents and extractions are persisted as pickles

- **Location:** `[build/pipeline.py:save_documents()]`, `[extract/cli.py:cmd_extract()]`
- **Decision:** `documents.pkl` and `extractions.pkl` hold the corpus and the
  candidate observations between stages.
- **Rationale:** Not recorded — confirm with RA. It preserves the dataclasses
  exactly, which a CSV would not.
- **Status:** Settled
- **Context:** Pickle is version-fragile and not a durable archive format. The
  durable record is `raw/` plus the response cache; the pickles are intermediate.
  Note that unpickling executes code, so a run directory received from someone else
  should not be built without inspecting it.

### D-19 — `summary.json` records counts, sources, reject reasons and speaker warnings

- **Location:** `[build/pipeline.py:build()]`
- **Decision:** Documents screened, documents with observations, kept, rejected,
  every speaker warning in full, counts by `speaker_source`, by reject reason and
  by institution, plus the paths written.
- **Rationale:** Not recorded — confirm with RA. It is the one file that has to be
  read after every build.
- **Status:** Settled
- **Context:** The counts quoted throughout this report come from the two pilot
  `summary.json` files.

### D-20 — JEL assignments are checked for existence, exact title and hierarchy

- **Location:** `[build/jel.py:def check(]`, `[build/validate.py:validate_jel()]`
- **Decision:** Every non-empty code must exist, sit at the level its slot implies,
  and — where a title is present — match the AEA title exactly. A detailed code
  must sit under the given subcategory, which must sit under the given major. A
  detailed code without its parent, or a subcategory without its major, is
  rejected. A missing primary, or more than two secondaries, is rejected.
- **Rationale:** The guide requires the AEA's exact current titles. Checking the
  hierarchy catches a plausible-looking but wrong assignment that membership alone
  would pass.
- **Status:** Settled
- **Context:** The level check here is what surfaced B-10. It is now a backstop
  rather than the first line of defence: `_refine()` repairs the same mismatch at
  the point it occurs.

## 6. Reference data

Three reference files ship inside the package (`institutions.csv`,
`officeholders.csv`, `jel_codes.csv`) and one alongside the harvest
(`officeholders_2026.csv`). The officeholder tables derive from a workbook,
`officeholders_US_UK_2025-2026.xlsx`, which holds the compilation notes; that
workbook is **not** in the repository (see Findings).

### R-01 — Institutions are keyed by a stable ID, with status and successor columns

- **Location:** `[reference/institutions.csv]`
- **Decision:** 48 rows — 24 UK ministerial departments and 24 US agencies — with
  `institution_id`, `country`, `institution`, `status`
  (`active`/`renamed`/`merged`/`dissolved`), `successor_institution_id` and a free
  `note`.
- **Rationale:** Machinery-of-government changes rename and merge departments
  inside the collection window. An ID that survives a rename is the only reliable
  join key; the note column carries the reasoning per institution.
- **Status:** Settled
- **Context:** `MHCLG`'s note makes the point explicitly: "GOV.UK uses both
  'Ministry of' and 'Department for' after July 2026 — match on ID, not name."
  Nothing in the pipeline currently joins on `institution_id`; every join is by
  name (see B-14).

### R-02 — The Cabinet Office's departmental head is the Chancellor of the Duchy of Lancaster

- **Location:** `[reference/institutions.csv]` — row `uk-cabinet-office`
- **Decision:** Not the Prime Minister.
- **Rationale:** Not recorded beyond the note itself — confirm with RA. The
  practical effect is that No10 output is out of scope.
- **Status:** Settled
- **Context:** Relevant to the recycled-quote question (S-03): a joint No10 and
  departmental announcement is attributed to the department.

### R-03 — DBT is the continuing entity; DSIT is merged into it

- **Location:** `[reference/institutions.csv]` — rows `uk-dbt`, `uk-dsit`
- **Decision:** `uk-dbt` is marked `renamed` with the note "Continuing entity:
  renamed DBIST on 2026-07-20 and absorbed DSIT. Collect DBIST output under this
  ID." `uk-dsit` is marked `merged` with `successor_institution_id = uk-dbt`.
- **Rationale:** The reference data takes a position — DBIST is DBT under a new
  name — so that the collection has a default.
- **Status:** Pending PI decision
- **Context:** The harvest takes the opposite position, treating DBIST as a
  separate institution label (H-08) so the choice stays open. The two are
  reconcilable only once the PIs decide. See S-04.

### R-04 — UK Export Finance shares the DBT Secretary of State

- **Location:** `[reference/institutions.csv]` — row `uk-ukef`;
  `[reference/officeholders_2026.csv]` — rows `uk-ukef`
- **Decision:** UKEF has no political head of its own and answers to the Business
  and Trade Secretary. Two spells are recorded — Peter Kyle to 2026-07-20, then
  Jonathan Reynolds — with the note "Consider dropping UKEF as a separate unit of
  observation and folding it into DBT/DBIST to avoid triple-counting the same
  speaker."
- **Rationale:** Keeping UKEF as its own unit while it shares a speaker with DBT
  (and, after the reshuffle, DBIST) means one person's statement could be counted
  three times.
- **Status:** Pending PI decision
- **Context:** This is what B-04's second half exists to handle in the audit. See
  S-05.

### R-05 — USAID is a structural zero, not a missed agency

- **Location:** `[reference/institutions.csv]` — row `us-usaid`
- **Decision:** Marked `dissolved` with `successor_institution_id = us-state` and
  the note "Ceased implementing foreign assistance 2025-07-01. Structural zero in
  the main window — expect and log zero documents."
- **Rationale:** It has no eligible speaker anywhere in the main window. The
  screening log must distinguish this from an agency that was never reached.
- **Status:** Settled
- **Context:** Marco Rubio was acting USAID Administrator from 2025-02-03 to
  2025-07-01, which matters only for the appendix window.

### R-06 — NSF's head is acting and not Senate-confirmed

- **Location:** `[reference/officeholders_2026.csv]` — row `us-nsf`;
  `[reference/institutions.csv]` — row `us-nsf`
- **Decision:** Brian Stone recorded from 2025-04-24 with
  `appointment_status = acting` and `eligible_speaker = yes`. The note reads
  "Chief of Staff 'performing the duties of the Director'. NOT Senate-confirmed.
  Jim O'Neill was nominated 2026-03-02 and referred to Senate HELP; not confirmed
  as at 2026-08-08. Decide explicitly whether a non-confirmed acting head qualifies
  under the Section 3 rule."
- **Rationale:** The provisional `yes` follows the general decision to include
  acting heads (R-08), but the guide's Section 3 rule was written for confirmed
  heads and NSF is a high-value agency for this project.
- **Status:** Pending PI decision
- **Context:** See S-08. Not yet load-bearing — the US collection has not started.

### R-07 — Only the NRC's designated Chairman is an eligible speaker

- **Location:** `[reference/institutions.csv]` — row `us-nrc`
- **Decision:** Other commissioners are out of scope.
- **Rationale:** Not recorded beyond the note — confirm with RA. Presumed to follow
  the Section 3 "head of agency" rule for a multi-member commission.
- **Status:** Settled
- **Context:** The NRC changed head inside the main window, per the workbook's
  churn note.

### R-08 — Acting heads are included, with a status column so they can be filtered out later

- **Location:** `[reference/officeholders_2026.csv]` — `appointment_status`
- **Decision:** Acting heads carry `eligible_speaker = yes` and
  `appointment_status = acting`.
- **Rationale:** Recorded in the source workbook as the RA's instruction. Keeping
  the status column means the PIs can restrict to confirmed heads later as a
  robustness check — worth having, since acting heads make fewer set-piece policy
  speeches.
- **Status:** Settled
- **Context:** Four US agencies changed head inside the main window (DHS, DOJ,
  Labor, NRC); DOJ and Labor are currently headed by acting officials. See R-06 for
  the one case where the general rule is in doubt.

### R-09 — Start dates are swearing-in dates where establishable; UK September 2025 appointments are all dated 2025-09-05

- **Location:** `[reference/officeholders_2026.csv]` — `start_date`
- **Decision:** Confirmation and swearing-in dates sometimes differ by a day; the
  swearing-in date is used where it could be established, and the confirmation date
  otherwise, with the substitution noted per row (for example `us-gsa`). The
  September 2025 UK appointments were announced over 5–7 September and 2025-09-05
  is used throughout.
- **Rationale:** One convention applied consistently, with the exceptions recorded,
  so a boundary case can be traced.
- **Status:** Settled
- **Context:** Statements in the first days of September 2025 should be treated with
  care. Only relevant if the window is extended (S-01).

### R-10 — Two officeholder rows are unverified placeholders

- **Location:** `[reference/officeholders_US_UK_2025-2026.xlsx]` — sheet
  `Appendix_2025_2026`, rows `us-hud` and `us-sba`
- **Decision:** The career officials who served as acting Secretary of HUD
  (2025-01-20 to 2025-02-05) and acting Administrator of the SBA (2025-01-20 to
  2025-02-20) are recorded as `[to verify]` with `eligible_speaker = "no - see
  notes"`. The workbook names these as its weakest rows.
- **Rationale:** An honest placeholder is more useful than a guessed name.
- **Status:** Pending PI decision
- **Context:** They matter only for the appendix window, so they become live only if
  the collection is extended to January 2025 (S-01). Verification route recorded:
  the hud.gov and sba.gov leadership archives. See S-09.

### R-11 — The workbook documents `end_date` as EXCLUSIVE

- **Location:** `[reference/officeholders_US_UK_2025-2026.xlsx]` — sheet `README`,
  "Unit of a row"
- **Decision:** "Match a document to a row by testing start date <= publication
  date < end date."
- **Rationale:** It resolves a same-day handover to exactly one person, which is
  what the churn in this window requires.
- **Status:** Pending PI decision
- **Context:** This is the reference data's own stated contract, and two of the
  three implementations violate it (H-14, D-10). Only `check_queue.py` follows it
  (M-11). See S-07.

### R-12 — Officeholder sources are tertiary, cross-checked, and carry a verification date

- **Location:** `[reference/officeholders_2026.csv]` — `source`, `verified`
- **Decision:** US rows come from Ballotpedia and Wikipedia cabinet trackers
  cross-checked against agency pages (nasa.gov, ssa.gov, opm.gov, nrc.gov) and
  Congress.gov nomination records. UK rows come from GOV.UK ministerial appointment
  press releases, supplemented by contemporaneous reporting for the May and June
  2026 changes. Every one of the 70 rows carries `verified = 2026-08-08`.
- **Rationale:** The workbook is explicit that this is a snapshot: "Re-verify before
  each collection run, and always re-verify anything within a month of
  2026-08-08."
- **Status:** Settled
- **Context:** As of this sweep the snapshot is 17 days old. The `source` column on
  most US rows is a Wikipedia URL, which the PIs may want replaced with a primary
  citation before release.

### R-13 — The JEL taxonomy has been rebuilt from the AEA page: 998 codes

- **Location:** `[reference/jel_codes.csv]`
- **Decision:** The shipped bootstrap (87 codes: 20 majors, 46 subcategories, 21
  detailed) has been replaced with a full scrape: 998 codes — 20 majors, 122
  subcategories, 856 detailed. Uncommitted.
- **Rationale:** The bootstrap existed so the tests could run offline; the guide
  requires the AEA's exact current titles for anything real.
- **Status:** Settled
- **Context:** `README.md` describes the bootstrap as "16 majors, 33 subcategories,
  17 detailed codes", which matches neither the committed file nor the current one
  (see Findings). The `dfe-pilot` run predates the rebuild, so its JEL assignments
  were made against the 87-code bootstrap; `dfe-v2` was built afterwards.

### R-14 — The taxonomy is frozen to a local CSV and the model selects from it

- **Location:** `[build/jel.py:JELTaxonomy]`, `[build/jel.py:fetch_from_aea()]`
- **Decision:** `eps fetch-jel` rebuilds `reference/jel_codes.csv` from
  `https://www.aeaweb.org/econlit/jelCodes.php?view=jel`. The file, not the model's
  memory, is the source of codes and titles. `cmd_fetch_jel` warns if fewer than 18
  majors or 500 detailed codes are parsed.
- **Rationale:** Frozen and local makes invented codes and mangled titles impossible
  instead of merely discouraged, and makes a run reproducible offline.
- **Status:** Settled
- **Context:** The source comments say to verify the output against the live page
  before a production run.

### R-15 — The working AEA parser lives in a script, not in the package

- **Location:** `[reference/fetch_jel_tables.py:parse()]`, `[build/jel.py:fetch_from_aea()]`
- **Decision:** `scripts/fetch_jel_tables.py` parses the AEA page as **tables** —
  a cell that is exactly a JEL code, with the next non-empty cell as its title.
  `jel.py:fetch_from_aea()` still looks for `CODE - Title` on one line.
- **Rationale:** The AEA page uses tables with the code in one cell and the title in
  the next, so a regex expecting a dash matches nothing. That is why `eps fetch-jel`
  reported "No codes parsed" rather than crashing.
- **Status:** Settled
- **Context:** `eps fetch-jel` remains broken (B-13); the current
  `jel_codes.csv` was produced by the script. Anyone following `README.md`'s
  instruction to run `eps fetch-jel` will get zero codes and a non-zero exit.

### R-16 — Three-character codes with no two-character parent fall back to the major letter

- **Location:** `[reference/fetch_jel_tables.py:parse()]`
- **Decision:** For a level-3 code, `parent = code[:2]`; for level 2,
  `parent = code[:1]`. The comment notes that some three-character codes (B00, C00)
  have no two-character parent on the page, and that recording the derived parent is
  preferred to recording one that does not exist.
- **Rationale:** `JELTaxonomy.check()` rejects a detailed code whose parent is not
  the chosen subcategory, so a wrong parent would silently invalidate assignments.
- **Status:** Settled
- **Context:** Derived rather than read from the page structure, so it assumes the
  AEA's codes are strictly prefix-nested. That holds for the current taxonomy.

### R-17 — Where a code appears more than once, the shortest title wins

- **Location:** `[reference/fetch_jel_tables.py:parse()]`, `[build/jel.py:fetch_from_aea()]`
- **Decision:** A code already seen is only replaced when the new title is strictly
  shorter.
- **Rationale:** Avoids nested duplicates where a parent element contains its
  children's text, which would otherwise record a title concatenating a whole
  branch.
- **Status:** Settled
- **Context:** The guide requires the AEA's exact titles, so a page-layout change
  that makes the shortest rendering an abbreviation would silently degrade them.

### B-12 — `tree.iter()` crashed on HTML comments in the AEA page

- **Location:** `[build/jel.py:fetch_from_aea()]`
- **Decision:** `tree.iter()` walks every node including comments and processing
  instructions, and `text_content()` rejects them, so the loop died with
  `ValueError: Input object is not an XML element: HtmlComment` on the first
  comment. Fixed by skipping any node whose `.tag` is not a string — lxml's standard
  way of telling comments apart from elements.
- **Rationale:** n/a — defect.
- **Status:** Settled
- **Context:** Applied by `scripts/patch_jel_comments.py`, uncommitted. The same
  guard is written into `fetch_jel_tables.py:cell_texts()` from the start.

### B-13 — `eps fetch-jel` parses nothing, because the AEA page uses tables

- **Location:** `[build/jel.py:fetch_from_aea()]`
- **Decision:** The regex `^([A-Z]\d{0,2})\s*[-–—:]\s*(.+)$` expects
  `I22 - Educational Finance` on one line. The AEA page puts the code and the title
  in adjacent table cells, so nothing matches and `cmd_fetch_jel` reports "No codes
  parsed" and exits 1.
- **Rationale:** n/a — defect. Fixing it means porting the table logic from
  `fetch_jel_tables.py` into `jel.py`.
- **Status:** Settled *(as a recorded fault; not yet fixed)*
- **Context:** B-12 was fixed in the same function without fixing this, so the
  function now runs to completion and returns an empty list. `README.md` and
  `RUNNING.md` both still tell the reader to run `eps fetch-jel`.

### R-18 — The package's officeholder table is currently empty

- **Location:** `[reference/officeholders.csv]`
- **Decision:** The file holds one line — the header
  `institution,person,role,start_date,end_date,source_url`. The committed version
  held 70 rows under a different schema (`institution_id`, `officeholder`,
  `appointment_status`, `eligible_speaker`, …) that `load_officeholders()` cannot
  read, so it was replaced with an empty file matching the loader's expectations.
- **Rationale:** Not recorded — confirm with RA. `README.md` calls the file a stub
  and says to replace it; `RUNNING.md` explicitly sanctions leaving it empty and
  using `speaker_hint` instead ("Option A").
- **Status:** Settled
- **Context:** This is why both pilots report `speaker_sources: {"manifest": 10}`
  (D-09): **no observation in the repository has passed an eligibility check.** The
  populated table exists as `harvest-code/officeholders_2026.csv`, but its schema
  differs and no conversion script is present. Populating this file is a
  prerequisite for the full run.

## 7. Scope and definitional decisions

Grouped by theme rather than by code, since none of these is implemented in one
place — and several are not implemented at all.

### Coverage

### S-01 — The collection window is 2026-01-01 to 2026-07-31, extendable to January 2025

- **Decision:** Seven months of UK output. The harvest takes `--start`, so
  extending to 2025-01-01 is a re-run rather than new code, and the officeholder
  workbook already carries an appendix covering the wider window.
- **Rationale:** Not recorded — confirm with RA.
- **Status:** Pending PI decision
- **Context:** Extending would make R-10's two unverified rows live, and would
  require editing `check_queue.py`'s hardcoded window (M-12).

### S-10 — Three UK offices returned zero eligible documents

- **Decision:** The Office of the Leader of the House of Commons (1 document
  published, 0 eligible), the Office of the Leader of the House of Lords (0
  published) and the Office of the Advocate General for Scotland (1 published)
  produced nothing. All three are recorded explicitly in the screening log with
  `no_documents_in_window` markers rather than being absent.
- **Rationale:** These offices handle parliamentary business rather than public
  communication, so a genuine zero is the expected result. The reference data
  anticipates it — `uk-oags` carries the note "Very low expected yield of
  economics-relevant statements."
- **Status:** Pending PI decision
- **Context:** What was checked: the harvest resolved a GOV.UK slug for each (H-17
  would otherwise have aborted), searched every slug variant (H-06), and the audit
  reconciled the log against the Search API for all 25 institutions. What remains
  for the PIs: whether three structural zeros are acceptable in the released table,
  or whether these offices should be dropped from the frozen list, or whether their
  ministers' output filed under other organisations should be collected by person
  instead of by department.

### S-11 — Wales Office: nine documents were not retrieved

- **Decision:** The Wales Office GOV.UK organisation record carried no documents in
  the window, while the audit's person-level cross-check (H-23) found 9 documents by
  Jo Stevens and Stephen Kinnock filed under other organisations. Unlike the
  Scotland Office, there is no second slug carrying the content, so the multi-slug
  rule (H-06) does not recover them. 9 documents of 2,672 — 0.3%.
- **Rationale:** Recorded as a known limitation rather than repaired, because
  recovering them means collecting by person rather than by department, which is a
  different sampling frame.
- **Status:** Pending PI decision
- **Context:** For the coverage note. Whether to retrieve them by person is the
  decision.

### S-13 — Social media is excluded and was never retrieved

- **Decision:** No X, LinkedIn or equivalent.
- **Rationale:** Excluded by Section 4 of the field guide.
- **Status:** Settled
- **Context:** Recorded so the absence is a decision rather than a gap.

### S-16 — The US collection has not started

- **Decision:** No US documents have been retrieved. `reference/us_sources.yaml`,
  which the US harvester requires, does not exist.
- **Rationale:** UK first, as a single-jurisdiction pilot of the whole method.
- **Status:** Settled
- **Context:** The US officeholder table is compiled and verified (R-12) and the
  institution list is complete, so the blocking work is the per-agency source
  adapters. The four bugs found during UK development (B-01 to B-04) are recorded
  in `DECISIONS.md` precisely because each is a failure mode that could recur when
  the US collection is built: all four failed silently and produced
  plausible-looking output, and none would have been caught by reading the final
  dataset.

### Units of observation

### S-02 — The unit of observation is the quotation, not the document

- **Decision:** One document may produce several rows; a document producing none is
  still screened. Rows are identified by `doc_id` plus `unit_ids`.
- **Rationale:** A speech can contain several distinct policy claims, and the guide
  asks for the minimum span carrying each claim.
- **Status:** Settled
- **Context:** In the `dfe-v2` run, 6 documents produced 24 kept observations.

### S-03 — Recycled quotes: which document is the observation?

- **Decision:** Not decided. Deduplication currently runs within a single document
  only (D-11), so the same ministerial quotation appearing in three press releases
  produces three rows.
- **Rationale:** Government communications reuse ministerial quotes across
  documents. Earliest publication date is the usual convention, but it has not been
  adopted.
- **Status:** Pending PI decision
- **Context:** This affects the `date` and `url` columns of every affected row, and
  should be settled before the verify step is built. Implementing it means moving
  deduplication above the per-document loop in `pipeline.build()`.

### S-04 — Is DBIST a third unit of observation, or does its material belong to DBT or DSIT?

- **Decision:** Not decided. The harvest treats all three as separate institution
  labels (H-08); the reference data treats DBIST as DBT renamed (R-03).
- **Rationale:** Deferring by collecting all three keeps both answers available.
- **Status:** Pending PI decision
- **Context:** DBT 123 documents, DSIT 120, DBIST 4. DBIST borrows DBT's officeholder
  record because Jonathan Reynolds heads both (H-10). Needs deciding before release.

### S-05 — Should UK Export Finance be a separate unit of observation?

- **Decision:** Not decided. UKEF is currently harvested as its own institution
  while sharing the DBT Secretary of State (R-04).
- **Rationale:** Keeping it separate risks triple-counting one person's statements
  across UKEF, DBT and DBIST.
- **Status:** Pending PI decision
- **Context:** Interacts with S-04: folding DBIST into DBT and keeping UKEF separate
  still leaves double-counting.

### S-14 — The eligible speaker is the departmental head only

- **Decision:** Junior ministers are out of scope. 1,042 of 2,672 documents are
  `linked_mismatch` — GOV.UK names a speaker who is not the eligible officeholder,
  mostly junior ministers — and none of them reaches the queue.
- **Rationale:** Section 3 of the field guide defines eligibility as the head of the
  agency or department.
- **Status:** Settled
- **Context:** This is the single largest exclusion in the pipeline, larger than
  every validator combined. Worth stating plainly in the coverage note: 39% of
  everything retrieved is dropped by this one rule.

### Definitions and labels

### S-06 — The `news_story` label

- **Decision:** Not decided. Currently mapped to `press_release` (H-02); 135 queued
  documents affected.
- **Rationale:** Section 4 names "News story" as eligible but the closed list of
  eight normalised labels has no equivalent.
- **Status:** Pending PI decision
- **Context:** The PIs need to choose between `press_release` (current),
  `other` (inside the spec, less informative) and a ninth label (outside the spec).
  The original type is preserved, so any choice is a relabel rather than a
  re-harvest — but `relabel_doc_types.py`, the tool `DECISIONS.md` names for the
  job, is absent from this repository.

### S-07 — Is `end_date` on an officeholder spell inclusive or exclusive?

- **Decision:** Not decided, and the three implementations disagree. The harvest is
  inclusive and returns every match (H-14); the build stage is inclusive and returns
  the first match in file order (D-10); the pre-flight check is exclusive and cannot
  be switched off (M-11); the reference workbook documents exclusive (R-11).
- **Rationale:** Exclusive resolves a same-day handover to exactly one person, which
  the churn in this window makes necessary. Inclusive is what two of the three code
  paths do.
- **Status:** Pending PI decision
- **Context:** **This is the most consequential open item.** The entire UK cabinet
  was re-formed on 2026-07-20 and four US agencies changed head inside the main
  window; DHSC and MoD each changed twice. Under the current build-stage behaviour a
  handover-day document's speaker depends on CSV row order, silently. Settling it
  means one convention applied in all three places, plus a decision on whether the
  harvest should keep returning both officeholders.

### S-08 — Does a non-Senate-confirmed acting head qualify as an eligible speaker?

- **Decision:** Not decided. Acting heads are provisionally included (R-08); NSF is
  the case where the general rule is in doubt, since Brian Stone is Chief of Staff
  "performing the duties of the Director" and has never been confirmed (R-06).
- **Rationale:** Section 3's rule was written for confirmed heads. NSF is a
  high-value agency for this project.
- **Status:** Pending PI decision
- **Context:** `appointment_status` is recorded on every row, so either answer can
  be applied without re-collecting — and the alternative can be run as a robustness
  check. Not yet load-bearing: the US collection has not started.

### S-09 — Two unverified acting heads in the January–February 2025 interregnum

- **Decision:** Not decided. The acting Secretary of HUD and the acting
  Administrator of the SBA between the 2025 inauguration and their successors'
  swearing-in are recorded as `[to verify]` (R-10).
- **Rationale:** The names could not be established from an official source at
  compilation time.
- **Status:** Pending PI decision
- **Context:** Only matters if the window is extended to January 2025 (S-01).
  Verification route: the hud.gov and sba.gov leadership archives.

### Measurement and method

### S-12 — The relevance score is deferred, and should be computed rather than asked for

- **Decision:** The Section 6 release table ships with eight of its nine columns;
  the 0.00–1.00 relevance score is not built (D-14). When it is added, it should be
  computed from the Section 8 rubric as booleans rather than obtained by asking the
  model for a number.
- **Rationale:** LLM confidence scores cluster on round values, and the 0.60 cutoff
  would inherit that lumpiness — the cutoff would then be doing something other than
  what it appears to do.
- **Status:** Pending PI decision
- **Context:** Until it exists, the released table does not match the specification.
  The PIs should be told this explicitly rather than discovering it from a column
  count.

### S-15 — Publication date is the `date` column

- **Decision:** GOV.UK's `public_timestamp`, not the date a speech was delivered
  (H-15).
- **Rationale:** Delivery date is not available from the Search API.
- **Status:** Settled
- **Context:** The risk is misattribution across a reshuffle. Checked once against
  the July 2026 reshuffle with no misattribution found; the risk remains theoretical
  but unobserved.

### S-17 — Retrieval, extraction and verification are three separate programs

- **Decision:** Harvest is deterministic, extraction is the only model stage, and
  build is deterministic. The corpus is frozen between them and model responses are
  cached.
- **Rationale:** Retrieval was done once and frozen so that prompt iteration does not
  re-download, and so comparisons between prompt versions run against an identical
  document set. It also allows quote fidelity to be enforced by exact string
  matching against the stored text rather than estimated by sampling.
- **Status:** Settled
- **Context:** The practical consequence is that `build` is free and offline, so
  validators can be iterated indefinitely. The replication claim that follows from
  it depends on committing the cache, which has not been done (E-13).

### S-18 — Every validator guards precision; nothing guards recall

- **Decision:** Recorded as a known and accepted asymmetry. A passage the model
  fails to select is invisible to the pipeline — no validator, log or count can
  detect it.
- **Rationale:** Stated explicitly in `README.md`. Only comparison against source
  documents can detect a miss.
- **Status:** Settled
- **Context:** The Section 11 review sampler is the intended mitigation and is not
  built. When it is, the probability each document was drawn with must be recorded,
  because it cannot be reconstructed afterwards. `k`-run stability — running
  extraction several times and keeping units selected in a majority of runs — is
  also listed as not yet built.

## Appendix A — Open items

Every entry with status **Pending PI decision**, in ID order.

| ID | Title | What the PIs need to decide |
|---|---|---|
| H-02 | `news_story` mapped to `press_release` | Confirm `press_release`, or choose `other`, or add a ninth label. 135 queued documents. Same question as S-06. |
| H-08 | DBIST harvested as a 25th department | Whether DBIST is a separate unit of observation. Same question as S-04. |
| H-14 | Harvest treats `end_date` as inclusive | Adopt one convention across all three implementations. Same question as S-07. |
| M-11 | Pre-flight check treats `end_date` as exclusive | As H-14. Also whether the flag should become switchable. |
| D-10 | Build stage is inclusive and returns the first matching row | As H-14. Also whether a handover-day ambiguity should warn rather than resolve silently. |
| R-03 | DBT recorded as the continuing entity for DBIST | Reconcile with H-08: reference data and harvest currently take opposite positions. |
| R-04 | UKEF shares the DBT Secretary of State | Whether UKEF stays a separate unit. Same question as S-05. |
| R-06 | NSF's acting, unconfirmed head | Whether a non-confirmed acting head is an eligible speaker. Same question as S-08. |
| R-10 | Two `[to verify]` officeholder rows | Whether to verify the acting HUD and SBA heads, or leave the appendix window unusable for those agencies. Same question as S-09. |
| R-11 | Workbook documents `end_date` as exclusive | As H-14 — this is the reference data's stated contract, which the code does not follow. |
| S-01 | Collection window | Whether to extend to 2025-01-01 if sample size requires it. |
| S-03 | Recycled quotes | Which document is the observation when the same quotation appears in several. Affects `date` and `url`. |
| S-04 | DBIST as a unit of observation | One unit or two. Needed before release. |
| S-05 | UKEF as a unit of observation | Keep separate, or fold into DBT/DBIST to avoid triple-counting. |
| S-06 | `news_story` labelling | As H-02. |
| S-07 | `end_date` inclusive or exclusive | **Highest priority.** One convention, applied in all three places. |
| S-08 | Acting-head eligibility | Whether Section 3 admits a non-confirmed acting head. |
| S-09 | HUD and SBA interregnum heads | Verify the two names, or accept the gap. |
| S-10 | Three UK offices with zero documents | Accept the structural zeros, drop the offices, or collect their ministers by person. |
| S-11 | Wales Office, 9 documents not retrieved | Whether to recover them by person-level search, changing the sampling frame. |
| S-12 | Relevance score deferred | Whether to release an eight-column table, and confirm the rubric-as-booleans approach when it is built. |
