# Descriptive exhibits — multi-v2

## Table 1 — Sample composition
One row per institution with at least one kept observation; a total row follows.
*Window: 2026-01-01 to 2026-07-31. Institutions: 2. Observations: 137.*
| Institution | Documents screened | Documents w/ obs. | Total obs. | Obs. per screened doc. | Distinct speakers | Earliest obs. | Latest obs. |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Department for Education | 168 | 10 | 35 | 0.21 | 1 | 2026-01-23 | 2026-07-15 |
| Ministry of Housing, Communities and Local Government | 225 | 19 | 102 | 0.45 | 1 | 2026-03-26 | 2026-07-15 |
| Total | 393 | 29 | 137 | 0.35 | 2 | 2026-01-23 | 2026-07-15 |

## Table 2 — Topic distribution
Panel A: share of observations by primary JEL major category. Panel B: most frequent 3-character primary codes.
*Window: 2026-01-01 to 2026-07-31. Institutions: 2. Observations: 137.*
**Panel A**
| Major | Title | Count (share) |
| --- | --- | --- |
| H | Public Economics | 43 (31%) |
| R | Urban, Rural, Regional, Real Estate, and Transportation Economics | 40 (29%) |
| I | Health, Education, and Welfare | 35 (26%) |
| J | Labor and Demographic Economics | 8 (6%) |
| L | Industrial Organization | 6 (4%) |
| K | Law and Economics | 3 (2%) |
| M | Business Administration and Business Economics • Marketing • Accounting • Personnel Economics | 2 (1%) |

**Panel B**
| Code | Title | Count (share) |
| --- | --- | --- |
| H77 | Intergovernmental Relations • Federalism • Secession | 27 (20%) |
| R38 | Government Policy | 26 (19%) |
| I28 | Government Policy | 15 (11%) |
| I22 | Educational Finance • Financial Aid | 9 (7%) |
| I38 | Government Policy • Provision and Effects of Welfare Programs | 8 (6%) |
| R52 | Land Use and Other Regulations | 5 (4%) |
| R58 | Regional Development Planning and Policy | 5 (4%) |
| H72 | State and Local Budget and Expenditures | 5 (4%) |
| H76 | State and Local Government: Other Expenditure Categories | 4 (3%) |
| K25 | Real Estate Law | 3 (2%) |

## Figure 1 — Primary JEL major category by institution
Cross-tab of raw counts; no plotting library is installed in this environment, so the underlying table is the exhibit.
*Window: 2026-01-01 to 2026-07-31. Institutions: 2. Observations: 137.*
| Institution | H | I | J | K | L | M | R |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Department for Education | 0 | 32 | 2 | 0 | 1 | 0 | 0 |
| Ministry of Housing, Communities and Local Government | 43 | 3 | 6 | 3 | 5 | 2 | 40 |
*Figure could not be rendered — no plotting library installed; see figure1_jel_major_by_institution.csv.*

## Figure 2 — Observations by month
Monthly counts across the full pilot window, stacked by JEL major category. Every month in the window is shown, including zero-observation months.
*Window: 2026-01-01 to 2026-07-31. Institutions: 2. Observations: 137.*
| Month | H | I | R | Other |
| --- | --- | --- | --- | --- |
| 2026-01 | 0 | 1 | 0 | 0 |
| 2026-02 | 0 | 6 | 0 | 0 |
| 2026-03 | 2 | 7 | 2 | 0 |
| 2026-04 | 0 | 1 | 11 | 3 |
| 2026-05 | 6 | 8 | 4 | 4 |
| 2026-06 | 12 | 2 | 6 | 7 |
| 2026-07 | 23 | 10 | 17 | 5 |
*Figure could not be rendered — no plotting library installed; see figure2_observations_by_month.csv.*

## Conditional fifth exhibit — relevance-score bands
Dropped. `relevance_score` is not a column this pipeline emits (assemble.py notes it is "deferred by design"), so the field guide's cut points (0.60-0.74, 0.75-0.89, 0.90-1.00) have nothing to bin. This is a schema gap, not a function of the >=60-observation gate — 137 observations survived, comfortably over that threshold.
