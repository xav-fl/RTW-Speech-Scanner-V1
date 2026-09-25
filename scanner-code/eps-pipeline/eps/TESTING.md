# Testing brief

For install and command syntax, see **[RUNNING.md](RUNNING.md)**. Activate your
environment before any command below.

A run-through in four phases. The first three cost nothing. Do them in order —
each one rules out a class of problem, so if something breaks later you know
where it isn't.

Budget roughly two hours for phases 0–2 the first time, most of it spent filling
in the officeholder table.

---

## Phase 0 — Install and confirm it runs (10 minutes)

```bash
git clone <your-repo-url>
cd eps
pip install -e ".[dev]"
python -m pytest tests/ -q
```

**Expect:** `53 passed`.

If the tests fail, stop here — that's an install problem, not a data problem,
and nothing else will work until it's fixed.

Now run the worked example, which uses two invented documents:

```bash
cp examples/officeholders_example.csv src/eps/reference/officeholders.csv
eps ingest --run-dir runs/example --manifest examples/manifest.csv
eps build  --run-dir runs/example --skip-context
```

**Expect:** `2 documents, 10 units (7 selectable)`, then `screened 2, kept 0`.

**`kept 0` is the correct answer.** You haven't run the AI step yet, so nothing
has been selected. If you got this far, the machinery works.

---

## Phase 1 — Your own documents, no AI, no cost (60–90 minutes)

### 1a. Collect 5–10 real documents

Save them into a folder. Accepted: `.txt`, `.md`, `.html`, `.pdf`, `.docx`.

Pick deliberately, not randomly. A good starting set:

- 2 substantive speeches you'd expect to yield several statements
- 1 press release (tests the attribution logic)
- 1 ceremonial or near-empty document you'd expect to yield **nothing**
- 1 PDF, if you'll be using PDFs at all

That fourth one matters. A pipeline that never returns an empty result is
miscalibrated, and you can't discover that with only promising documents.

For HTML, "Save page as" from your browser is fine.

### 1b. Build the manifest

```bash
eps ingest --dir mydocs/ --write-template manifest.csv --country UK
```

This writes a spreadsheet with one row per file and blank columns. Open it in
Excel and fill in, for each row:

| Column | What to put | Notes |
|---|---|---|
| `institution` | e.g. `Department for Education` | Must match `officeholders.csv` **exactly** |
| `country` | `UK` or `US` | |
| `url` | the public web address | Goes straight into the dataset |
| `title` | the document's title | |
| `doc_type` | `speech`, `press_release`, `statement`, `testimony`, `letter`, `op_ed`, `interview_transcript`, `other` | Changes how attribution is handled |
| `date` | `2026-03-04` format | Decides which minister was in post |
| `delivery_status` | `as_delivered`, `as_prepared`, `unknown` | Leave `unknown` if unsure |

Save as CSV, not `.xlsx`.

### 1c. Name the speakers

**Quickest:** fill in the `speaker_hint` column of your manifest with each
speaker's name, and skip the rest of this step. Good enough for a trial set.

**Or, the fuller version — the officeholder table**

Open `src/eps/reference/officeholders.csv`, delete the two placeholder rows, and
add a real row for each institution in your manifest:

```csv
institution,person,role,start_date,end_date,source_url
Department for Education,Jane Smith,Secretary of State for Education,2026-01-14,,https://www.gov.uk/government/ministers
```

Leave `end_date` blank if they're still in post. If someone was replaced
mid-window, add a row each with the correct dates.

The table adds something the manifest can't: it checks the speaker was actually
the department head *on that date*, so an ineligible speech gets rejected rather
than quietly included. That check is the whole reason for the dates. If you don't
need it yet, use `speaker_hint` and move on.

### 1d. Run it

```bash
eps ingest --run-dir runs/test1 --manifest manifest.csv
eps build  --run-dir runs/test1 --skip-context
```

### 1e. Check three things

Open `runs/test1/out/screening_log.csv` in Excel.

1. **Is every document listed?** If one is missing, ingest rejected it — the
   error was printed in the terminal.
2. **Is `eligible` `True` everywhere?** `False` means the officeholder table
   didn't match. Usually the institution name is spelled differently in the two
   files, or the date falls outside the range you entered.
3. **Does `selectable` look right?** From the ingest output. For speeches, every
   sentence should be selectable. For press releases, only the quoted ones.

To eyeball the sentence splitting:

```bash
python -c "
from eps.pipeline import load_documents
for d in load_documents('runs/test1/documents.pkl')[:1]:
    for u in d.units[:15]:
        print('[x]' if u.attributable else '[ ]', u.unit_id, '|', u.text[:90])
"
```

`[x]` means selectable. Read a few and check the sentences break where you'd
expect, especially in PDFs.

**Do not go to Phase 3 until all three checks are clean.** Every one of these
problems would otherwise cost you money to discover.

---

## Phase 2 — Common problems

| Symptom | Cause | Fix |
|---|---|---|
| `manifest validation failed` | Bad date, missing column, file not found | Error names the row number |
| `eligible = False` | Name mismatch or date outside range | Compare manifest to `officeholders.csv` character by character |
| PDF text is garbled | Scanned image, not real text | Needs OCR, or find an HTML version |
| Sentences split mid-abbreviation | Unrecognised abbreviation | Add it to `_ABBREV` in `src/eps/normalise.py` |
| Press release has 0 selectable | Quotes not marked with `"` | See `mark_attribution` in `normalise.py` |
| `no such command: eps` | Install didn't complete | Re-run `pip install -e ".[dev]"` |

---

## Phase 3 — Turn on the AI (30 minutes, small cost)

### 3a. Get a key

Go to **console.anthropic.com** and create an account. This is separate from a
Claude.ai subscription and billed separately — a Claude subscription does not
include API access.

Add a small amount of credit, and **set a spending limit** while you're there.

Ideally this should be an institutional account rather than your personal card.

### 3b. Run on a handful of documents first

```bash
export ANTHROPIC_API_KEY=sk-ant-...
eps extract --run-dir runs/test1
eps context --run-dir runs/test1
eps build   --run-dir runs/test1
```

Start with 5–10 documents, not your whole corpus. Responses are cached, so
re-running `build` afterwards is free and instant.

### 3c. Read the output against the sources

Open `runs/test1/out/dataset.csv` next to the original documents and check, for
every row:

- **Is the quote real?** Search for it in the source. It should be exact. (This
  is guaranteed by construction — if it ever fails, tell me, it's a bug.)
- **Should it be there?** This is the real question. The program cannot check it.
- **Did it miss anything?** Read the source and look for passages that should
  have been picked up and weren't. **Nothing in the program detects this** —
  every check guards against false positives; none guards against omissions.
- **Are the JEL codes defensible?** Expect major categories to be reliable and
  three-character codes to be weaker.

Then open `rejected.csv`. If it's dominated by `not attributable` or `too short`,
that's my code being too strict, not the model being wrong — tell me and I'll
adjust the thresholds.

Finally, check your deliberately-empty document produced nothing. If it produced
a row, the criteria are too loose.

---

## Phase 4 — Before scaling up

Two experiments worth running while the corpus is small:

**Does the speaker's identity change the answer?**

```bash
eps extract --run-dir runs/test1 --identity-mode full
eps context --run-dir runs/test1
eps build   --run-dir runs/test1
```

Compare against the default `blind` run. If selections differ, the model is
responding to who is speaking rather than what was said. Worth knowing, and
worth reporting.

**Does a prompt change help or hurt?** Edit `EXTRACT_SYSTEM` in
`src/eps/extract.py`, re-run `extract` and `build`, and compare. That is all —
the prompt text is part of the cache key, so an edit takes effect on its own.

Every row records `prompt_sha`, a hash of the prompt text, so you can always tell
which wording produced which rows even while iterating quickly. Only bother
setting `PROMPT_VERSION` and archiving into `prompts/` when a version is about to
leave your machine.

---

## Checklist

- [ ] `pytest` passes: 53 tests
- [ ] Worked example runs
- [ ] 5–10 real documents collected, including one expected to yield nothing
- [ ] Manifest filled in and saved as CSV
- [ ] `officeholders.csv` has real rows
- [ ] `ingest` accepts every document
- [ ] `eligible = True` for every row in the screening log
- [ ] Sentence splitting and attribution look right
- [ ] API key obtained, spending limit set
- [ ] `extract` run on 5–10 documents
- [ ] Every quote checked against its source
- [ ] Every source checked for missed passages
- [ ] Empty document produced nothing
- [ ] `rejected.csv` reviewed

---

## What to tell me

When you report back, the useful things are: how many documents in and rows out,
anything in `rejected.csv` that looks like my code being wrong, and — most
useful — one or two examples of passages it picked that it shouldn't have, or
missed that it should have caught. Those are what the prompt gets tuned against.
