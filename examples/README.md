# Worked example

Two invented documents so you can confirm the install works before using real
data. Nothing here is a real government document.

From the repository root:

```bash
cp examples/officeholders_example.csv src/eps/reference/officeholders.csv
eps ingest --run-dir runs/example --manifest examples/manifest.csv
eps build  --run-dir runs/example
```

Expected: `2 documents, 10 units (7 selectable)`, then a build reporting
`screened 2`, `kept 0`. Zero kept is correct — `extract` has not run, so nothing
has been selected yet.

Restore your real `officeholders.csv` afterwards.
