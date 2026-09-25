# How to run this

A practical guide. Windows commands are given first, macOS/Linux in brackets.

If you only read one thing, read **Every time you open a terminal** below. That's
the step that catches people.

---

## Every time you open a terminal

Two commands, always, before anything else. Closing the terminal undoes both.

```powershell
cd "C:\Users\xavif\OneDrive\Documents\WISE\files\eps-pipeline\eps"
.\.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
cd ~/Documents/eps
. .venv/bin/activate
```

**Check it worked:** your prompt should now start with `(.venv)`.

```
(.venv) PS C:\Users\xavif\...\eps>
```

No `(.venv)` means no `eps` command. That is the cause of nearly every
"is not recognized" error.

---

## First-time setup (once only)

```powershell
cd "path\to\eps"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest -q
```

macOS/Linux: `python3 -m venv .venv` then `. .venv/bin/activate`.

**Expect:** `57 passed`. If you see that, you are installed correctly.

If activating fails with *"running scripts is disabled on this system"*, run this
once and try again:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Answer `Y`. It affects your user account only.

---

## Command cheat sheet

Activate first (see above), then:

| What you want | Command |
|---|---|
| Check install | `pytest -q` |
| Run the worked example | `eps ingest --run-dir runs/example --manifest examples/manifest.csv` then `eps build --run-dir runs/example --skip-context` |
| Scaffold a manifest for your files | `eps ingest --dir mydocs --write-template manifest.csv --country UK` |
| Load your documents | `eps ingest --run-dir runs/test1 --manifest manifest.csv` |
| Run the AI (costs money) | `eps extract --run-dir runs/test1` |
| Run the AI via Mistral instead | `eps extract --run-dir runs/test1 --provider mistral` |
| Add context to the quotes (costs money) | `eps context --run-dir runs/test1` |
| Build the spreadsheet | `eps build --run-dir runs/test1` |
| Rebuild after changing settings | `eps build --run-dir runs/test1` (free, instant) |
| Rebuild the JEL taxonomy | `eps fetch-jel` |
| See all options for a command | `eps ingest --help` |

`extract` and `context` cost money. `ingest` and `build` are free and work
offline.

`build` refuses to write a release until `context` has run, because a
`quote_in_context` that merely repeats its `direct_quote` looks identical
whether the stage ran and added nothing or never ran at all. Pass
`--skip-context` if you genuinely want plain quotes.

---

## The normal working sequence

```powershell
# 1. free: load documents and check them
#    --skip-context because nothing has been extracted yet, so there is
#    nothing to add context to; this pass is only for the screening log
eps ingest --run-dir runs/test1 --manifest manifest.csv
eps build  --run-dir runs/test1 --skip-context

#    open runs\test1\out\screening_log.csv in Excel
#    every row should say eligible = True before you go further

# 2. paid: let the AI select passages
$env:ANTHROPIC_API_KEY = "sk-ant-..."
eps extract --run-dir runs/test1

# 3. paid: name the referents a quote leaves implicit
#    ("Today's action [standardizing grant requirements] ...")
eps context --run-dir runs/test1

# 4. free: write the tables
eps build   --run-dir runs/test1

#    open runs\test1\out\dataset.csv
```

macOS/Linux: `export ANTHROPIC_API_KEY=sk-ant-...`

The API key lasts for that terminal session only, same as activation. It is a
credential — do not put it in any file inside this folder.

---

## Naming the speaker: two ways

Every document needs a speaker. Pick whichever suits you.

**Option A — put it in the manifest** (simplest, good for hand-picked documents).
Fill in the `speaker_hint` column with the person's name. That's it. You can
leave `officeholders.csv` empty.

**Option B — the officeholder table** (better at scale). Add a row per person per
institution with `start_date` and `end_date`. The program then works out who was
in post on each document's date, and rejects documents from anyone else. This is
an *eligibility check*, not just a lookup: it stops a junior minister's speech
slipping in.

If you fill in both, the table wins and you are warned about any disagreement —
which almost always means a wrong date somewhere.

Every row of `screening_log.csv` records `speaker_source`, so you can always see
which route was used.

**Start with Option A.** Move to Option B when you scale up, or when your window
covers a reshuffle.

---

## Where the output goes

Everything lands under `runs\<your-run-name>\out\`:

| File | What it is |
|---|---|
| `dataset.csv` | The deliverable — the Section 6 table |
| `screening_log.csv` | Every document, whether or not it produced anything |
| `rejected.csv` | Candidate quotes the checks threw out, and why |
| `observations_internal.csv` | Same rows as the dataset plus JEL detail and provenance |
| `summary.json` | Counts by institution and by rejection reason |

All open in Excel.

---

## When something breaks

| What you see | What it means | Fix |
|---|---|---|
| `eps : The term 'eps' is not recognized` | Not activated | `.\.venv\Scripts\Activate.ps1` |
| `running scripts is disabled on this system` | PowerShell security | `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser` |
| `No such file or directory: manifest.csv` | Wrong folder | `cd` to the `eps` folder |
| `python is not recognized` | Python missing, or not added to PATH | Reinstall from python.org, tick "Add Python to PATH" |
| `externally-managed-environment` | No virtual environment | Do the first-time setup |
| `manifest validation failed` | Bad row in your manifest | Error names the row number — usually the date format |
| `manifest.csv is missing required columns: ['path']` | Excel saved the file with an invisible marker | Fixed as of this version. If you still see it, re-download the pipeline. |
| `extract` reports `0 candidates` for every document, no errors printed | Fixed as of this version — `extract` only checked `officeholders.csv` and silently skipped documents whose speaker came from `speaker_hint` alone. If you see this, re-download. |
| `eligible = False` in screening log | Officeholder table doesn't match | Compare institution name and dates against `src/eps/reference/officeholders.csv` |
| `kept 0` after only ingest + build | Normal | The AI hasn't run yet; nothing has been selected |
| `authentication_error` from extract | Key missing or wrong | Re-set `$env:ANTHROPIC_API_KEY` |
| `rate_limit_error` | Too many requests too fast | Wait, or add credit to raise your tier |

---

## If activation keeps annoying you

You can skip it permanently by calling the workspace's Python directly:

```powershell
.\.venv\Scripts\python -m eps.cli ingest --run-dir runs/test1 --manifest manifest.csv
```

Substitute `.\.venv\Scripts\python -m eps.cli` anywhere the docs say `eps`.
Longer to type, works from any terminal with no setup.

---

## Two habits worth having

**Glance at your prompt before typing.** `(.venv)` at the front means you are
ready. This one check prevents most errors in the table above.

**Use a fresh run name for a fresh experiment.** `runs/test1`, `runs/test2`, and
so on. Runs are self-contained, so nothing overwrites anything, and you can
compare two runs side by side in Excel.

---

## Where to look next

- **[TESTING.md](TESTING.md)** — the four-phase testing plan. Start here.
- **[README.md](README.md)** — how the program works and why it is built this way.
- **`src/eps/extract.py`** — the criteria the AI applies, lines 37–80. Editable.
