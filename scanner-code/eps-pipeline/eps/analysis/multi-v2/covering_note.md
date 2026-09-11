# Covering note — multi-v2

## Provenance
- Run directory: `runs\multi-v2`
- Git commit: `17d7c3785d3abd29c86f40d628c53fb47194d507` (branch `multi-dept-descriptives`)
  - **Uncommitted changes under `src/eps/reference/` at run time:** scanner-code/eps-pipeline/eps/src/eps/reference/institutions.csv, scanner-code/eps-pipeline/eps/src/eps/reference/officeholders.csv. A fresh checkout of the commit above will not exactly reproduce the officeholder resolution this run used.
- Prompt fingerprint (prompt_version/prompt_sha, from observations_internal.csv — `summary.json` does not carry this field for this run): P6-units-blind/b6931002789d
- Harvest window: 2026-01-01 to 2026-07-31
- Script run date: 2026-08-28 (UTC)

## Required caveats
1. This is a four-department pilot covering 1 January to 31 July 2026, not the full 24-department UK collection. The US collection has not started.
2. JEL classification currently over-assigns residual codes. The topic distribution in Table 2 and Figure 1 reflects that and will change once the classification work concludes.
3. The DfE observations here were harvested, whereas earlier DfE runs were hand-picked from a manifest. These figures are comparable across the departments in this run and are not continuous with the earlier DfE series.
4. Documents excluded by the boundary-date fix: **count not established.** This could not be determined from `runs/multi-v2` alone — if the fix operates upstream of this run's manifest, no exclusion log distinguishing it from other manifest-preparation exclusions exists in this run directory. Flagging as missing rather than guessing a number.
5. *(Added, not in the brief's list)* Two institutions screened in this run — Ministry of Defence and Ministry of Justice — are excluded from every exhibit above at explicit instruction, not the brief's: Ministry of Defence (220 screened, 219 eligible, 0 kept); Ministry of Justice (118 screened, 116 eligible, 0 kept). The brief's own small-N discipline says a zero-observation institution should appear as a full row of zeros / an empty column, because that null result is itself a finding. This run departs from that rule.

## Exhibits not built
- Conditional fifth exhibit (relevance-score bands): dropped. `relevance_score` is not emitted by the pipeline (deferred by design), independent of the >=60-observation gate.

## Judgement calls
1. Institutions with zero kept observations are dropped from every exhibit entirely (constant `DROP_ZERO_OBSERVATION_INSTITUTIONS`), overriding the brief's zero-row convention — done at explicit instruction; see required caveat 5.
2. Figure 2 stacks by JEL major category only if at least two categories clear a pooled total of 10; categories below that are pooled into 'Other' rather than dropped. For this run: stacked.
3. Table 2 Panel B uses `jel_primary_detailed`, the three-character code column, per the brief's literal description.
4. Prompt fingerprint sourced from `observations_internal.csv` (`prompt_version`/`prompt_sha`) rather than `summary.json`, which carries no such field for this run.
5. Output directory is `analysis/<run-name>/`, derived from the run directory's basename, matching the brief's `analysis/multi-v1/` example generalised to any run.
6. 'Distinct speakers' (Table 1) counts only speakers who appear in a kept observation, not every officeholder eligible during the window.
7. Table 1's Total row and 'observations per screened document' use only the included institutions' screened-document counts (393), not the full run's 731 screened documents across all four institutions.
8. Figure 2's month axis is fixed to the brief's stated pilot window (seven calendar months) rather than the data's own min/max date, so an all-zero month at either edge stays visible.

## Things that look wrong, not just small
- officeholders.csv has an overlapping-spell defect (the officeholder table gives 2 eligible speakers for 'Ministry of Housing, Communities and Local Government' on 2026-07-20 ('Steve Reed', 'Angela Rayner') — fix the overlapping spell dates in officeholders.csv) — no kept observations affected.
- 124 of 137 kept observations come from a document where the manifest's speaker string differs from the officeholder table's (mostly honorific/title formatting, e.g. 'The Rt Hon X MP' vs 'X' — the officeholder table's resolution is what was used). Not re-verified name-by-name; the one structural defect above (overlapping spells) is the one checked in full.
