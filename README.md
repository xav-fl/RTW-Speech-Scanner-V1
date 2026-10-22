# Economics policy statements (speeches)

A dataset of economics-relevant policy statements by the heads of UK
ministerial departments and US federal agencies, and the code that builds it.
It is one half of a study comparing what economists research with what
policymakers say they care about. The other half, papers cited in policy
documents, is in [RTW-Overton-Analysis](https://github.com/xav-fl/RTW-Overton-Analysis).

## Start here

| I want to… | Go to |
|---|---|
| **Use the final dataset** | [`datasets/speeches_jul2026.csv`](datasets/speeches_jul2026.csv), 311 statements (172 UK, 139 US), July 2026. Columns are explained in [`datasets/README.md`](datasets/README.md) |
| Understand the `intention` labels | [`docs/INTENTION_CODEBOOK.md`](docs/INTENTION_CODEBOOK.md) |
| See why the data looks the way it does | [`docs/DECISIONS.md`](docs/DECISIONS.md), the numbered log of every design decision |
| Run the pipeline myself | [`scanner-code/eps-pipeline/eps/RUNNING.md`](scanner-code/eps-pipeline/eps/RUNNING.md) |
| Run it through my own Codex agent | The `codex-native` branch (see below) |
| Add context to quotes in another dataset | [`quote-context-kit/`](quote-context-kit) |

## What's in this repository

```
datasets/                 Final data, with a column guide
docs/                     Decision log, intention codebook, intention reports
harvest-code/             Step 1: collect speeches and press releases
  uk-harvest/               GOV.UK documents and screening logs
  us-harvest/               US agency documents and screening logs
  us-harvest-2026-07/       The July 2026 US collection
scanner-code/eps-pipeline/eps/
                          Step 2: pick out the economics statements, code
                          them (JEL topics, intention) and build the dataset
  src/eps/                  The pipeline itself
  runs/                     Every run's inputs and outputs. jul2026-uk and
                            jul2026-us produced the final dataset; the rest
                            are pilots and trials kept for the record
  tests/                    Test suite
quote-context-kit/        Stand-alone version of the "quote in context" step
```

## How the dataset is built

1. **Harvest.** Collect every speech, press release and statement published
   by each department or agency in the period.
2. **Extract.** A model reads each document and points to the passages that
   state an economic policy position. It returns pointers into the document,
   never text, so every quote is verbatim by construction.
3. **Classify.** Each statement gets one to three JEL codes from the official
   AEA list, and an intention label (commits to action, reports existing
   action, calls on others, …).
4. **Context.** Where a quote refers to something it doesn't name ("this
   investment"), a short bracketed insertion is added in `quote_in_context`,
   checked word for word against the source.
5. **Build.** Code-only validation and assembly into the final CSV.

## Branches

| Branch | What it is |
|---|---|
| `main` | The main pipeline and the final dataset. Start here |
| `jel-v2` | Work in progress: JEL classification protocol v2.0 (unordered codes with a status and rationale). Not yet used for the published data |
| `codex-native` | A variant that runs the pipeline through someone else's own Codex agent (OpenAI models). Packaged bundles are tagged `codex-bundle-v1` to `codex-bundle-v4`; v4 is the latest. Its output is not directly comparable with the main dataset, because a different model makes every judgement |
| `codex-native-jel-v2` | `codex-native` with the JEL v2.0 changes applied |
