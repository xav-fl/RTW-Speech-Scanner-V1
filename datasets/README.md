# Datasets

## `speeches_jul2026.csv`: the final speeches dataset

Economics-relevant policy statements by heads of UK ministerial departments
and US federal agencies, July 2026 (1–31 July).

| | UK | US | Total |
|---|---|---|---|
| Documents screened | 319 | 644 | 963 |
| Documents with at least one statement | 59 | 89 | 148 |
| **Statements (rows)** | **172** | **139** | **311** |

The first 172 rows are UK and the remaining 139 are US. The file is UTF-8 with a
byte-order mark, so it opens correctly in Excel. Quotes that spanned several
paragraphs are joined onto one line, and dates are written `dd/mm/yyyy`.

### Columns

| Column | What it holds |
|---|---|
| `agency` | UK department or US agency that published the document |
| `speaker` | The head of that department or agency on that date |
| `document_title` | Title of the source page |
| `document_type` | `speech`, `press_release`, `statement`, `interview_transcript` or `other` |
| `date` | Publication date |
| `url` | Link to the source page |
| `direct_quote` | The statement, verbatim. Copied character for character from the source by code; a model never writes this column |
| `quote_in_context` | The same quote with short bracketed insertions naming things it leaves implicit (e.g. "This investment [£80m for ...]"). Identical to `direct_quote` where nothing was needed |
| `intention` | What the speaker is doing with the statement, e.g. `Commits to action: pledges future action`. 17 possible values; definitions in [`docs/INTENTION_CODEBOOK.md`](../docs/INTENTION_CODEBOOK.md) |
| `economics_topics` | One to three JEL codes with titles, at the most specific level assigned (e.g. `I21 – Analysis of Education`) |
| `jel_major_categories` | The same codes rolled up to the one-letter JEL category |
| `jel_subcategories` | The same codes rolled up to the two-character JEL subcategory |

### How it was made

Built by the main pipeline in [`scanner-code/eps-pipeline/eps`](../scanner-code/eps-pipeline/eps)
using Anthropic models (JEL protocol v1, intention prompt I3). Every design and
coding decision is logged in [`docs/DECISIONS.md`](../docs/DECISIONS.md).

The unflattened per-country outputs, with the audit trail (rejected statements
and the reasons, context and intention logs, internal columns such as
`doc_id` and model IDs), are in:

- `scanner-code/eps-pipeline/eps/runs/jul2026-uk/out/`
- `scanner-code/eps-pipeline/eps/runs/jul2026-us/out/`
