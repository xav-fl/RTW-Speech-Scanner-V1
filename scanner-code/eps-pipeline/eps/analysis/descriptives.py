"""Descriptive-statistics exhibits for one eps build run.

Everything under analysis/<run-name>/ is derived from that run's own out/*
files and nothing else. Deleting analysis/<run-name>/ and re-running
`python analysis/descriptives.py <run_dir>` must reproduce it exactly, so no
function here reads anything outside <run_dir> (git metadata is the one
exception, used only for the covering note's provenance line, never for a
number that appears in an exhibit) or writes anything outside
analysis/<run-name>/.

This script answers "what does this dataset let you say about ministers,"
not "did the pipeline work." It does not touch runs/<run>/ (read-only) and
does not import from src/eps/ — reference-table lookups (JEL titles,
institution names) are reconstructed from the run's own output columns
instead, so this script has no dependency on the package it is describing.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Policy constants — each one is a judgement call the brief left open, or a
# deliberate departure from it. Every constant here is explained in the
# covering note this script writes, not just in this comment.
# ---------------------------------------------------------------------------

# Small-N discipline: a percentage next to a denominator under this is
# suppressed outright (count only), never rounded or footnoted away.
MIN_DENOMINATOR_FOR_PERCENT = 10

# Departure from the brief, taken at explicit instruction (2026-08-28): the
# brief's own rule is that a zero-observation institution gets a full row of
# zeros in Table 1 and a visible empty column in Figure 1, because the null
# result is itself a finding. This run drops such institutions from every
# exhibit entirely instead. Rejected alternative: the brief's zero-row
# convention — overridden on request, not silently applied; see
# write_covering_note(), which records the excluded institutions and their
# screened/eligible counts so a reader can reconstruct what was left out.
DROP_ZERO_OBSERVATION_INSTITUTIONS = True

# Figure 2 stacks by JEL major category only when the pooled data supports
# it. Rejected alternative: stack unconditionally — with observations spread
# thin over several categories and seven months, most month-by-category
# cells would be 0 or 1, which is exactly what the small-N discipline exists
# to keep off a chart. Instead: a category earns its own band only if its
# *pooled* total (across the whole window) clears the same threshold used
# for percentages; everything below that is folded into "Other" rather than
# dropped. Stacking is used at all only if at least two categories qualify —
# one qualifying category plus "Other" is no more informative than a single
# unstacked line.
MIN_CATEGORY_TOTAL_FOR_OWN_BAND = 10
MIN_QUALIFYING_CATEGORIES_TO_STACK = 2

# The brief's stated pilot window (required caveat 1), used to fix Figure
# 2's x-axis so zero-observation months stay visible. Rejected alternative:
# derive the window from the data's own min/max date — that would silently
# drop any all-zero month at either edge, which is exactly the kind of
# absence the small-N discipline says must stay visible.
WINDOW_START = "2026-01-01"
WINDOW_END = "2026-07-31"
WINDOW_MONTHS = [f"2026-{m:02d}" for m in range(1, 8)]

# The conditional fifth exhibit (relevance-score bands) needs a field this
# pipeline does not currently emit — see assemble.py's own comment ("minus
# the relevance score (deferred by design)"). Per the brief: "If an exhibit
# needs a value the pipeline does not currently emit, drop the exhibit and
# report what was missing." This is a schema gap, not a function of the
# >=60-observation gate, so it applies regardless of how many observations
# survive.
RELEVANCE_SCORE_COLUMN = "relevance_score"


def read_csv(path: Path) -> list[dict]:
    """Return every row of path as a dict, in file order.

    utf-8-sig strips a BOM if present and is a no-op otherwise, so this
    reads every CSV in the run the same way regardless of which tool wrote
    it.
    """
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_run(run_dir: Path) -> dict:
    """Load every out/ artefact this script consumes; nothing outside run_dir."""
    out = run_dir / "out"
    return {
        "summary": json.loads((out / "summary.json").read_text(encoding="utf-8-sig")),
        "screening": read_csv(out / "screening_log.csv"),
        "observations": read_csv(out / "observations_internal.csv"),
        "dataset": read_csv(out / "dataset.csv"),
        "rejected": read_csv(out / "rejected.csv"),
    }


def git_provenance(script_path: Path) -> dict:
    """Best-effort git metadata for the covering note.

    Never raises: a missing git binary or a checkout with no .git should
    degrade to "unknown" rather than crash a script a PI is depending on for
    numbers.
    """
    repo_root = script_path.resolve().parent
    while repo_root != repo_root.parent and not (repo_root / ".git").exists():
        repo_root = repo_root.parent
    if not (repo_root / ".git").exists():
        return {"commit": "unknown (no .git found above this script)", "dirty_reference_files": []}

    def run(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

    try:
        commit = run("rev-parse", "HEAD")
        branch = run("rev-parse", "--abbrev-ref", "HEAD")
        ref_dir = script_path.resolve().parent.parent / "src" / "eps" / "reference"
        rel_ref_dir = ref_dir.relative_to(repo_root)
        # Not run(): porcelain status lines are fixed-width ("XY path"), and
        # run()'s .strip() eats the leading space of the *first* line only
        # (a plain-space status code), which silently misaligned line[3:]
        # for exactly one row. rstrip("\n") removes only the trailing
        # newline, so every line keeps its real leading characters.
        status = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain", "--", str(rel_ref_dir)],
            capture_output=True, text=True, check=True,
        ).stdout.rstrip("\n")
        dirty = [line[3:] for line in status.splitlines()] if status else []
    except Exception:
        return {"commit": "unknown (git call failed)", "branch": "unknown", "dirty_reference_files": []}
    return {"commit": commit, "branch": branch, "dirty_reference_files": dirty}


def format_pct(n: int, denom: int) -> str:
    """'n (xx%)' once denom clears MIN_DENOMINATOR_FOR_PERCENT, else just the count.

    Never rounds a suppressed percentage into existence and never omits the
    count — see "Small-N discipline" in the brief. A zero-denominator input
    (no rows at all) also suppresses, since there is nothing to take a share
    of.
    """
    if denom < MIN_DENOMINATOR_FOR_PERCENT:
        return f"{n}"
    return f"{n} ({round(100 * n / denom)}%)"


def institution_split(run: dict) -> tuple[list[str], dict[str, dict]]:
    """Return (included institutions, {excluded institution: screening stats}).

    Included = at least one kept observation. See
    DROP_ZERO_OBSERVATION_INSTITUTIONS above for why this departs from the
    brief's zero-row convention.
    """
    screened = Counter(r["institution"] for r in run["screening"])
    eligible = Counter(r["institution"] for r in run["screening"] if r["eligible"].lower() == "true")
    with_obs = {r["agency"] for r in run["observations"]}

    included = sorted(with_obs) if DROP_ZERO_OBSERVATION_INSTITUTIONS else sorted(screened)
    excluded = {}
    for inst in sorted(screened):
        if inst not in included:
            excluded[inst] = {
                "documents_screened": screened[inst],
                "documents_eligible": eligible[inst],
            }
    return included, excluded


def build_table1(run: dict, included: list[str]) -> list[dict]:
    """One row per included institution plus a Total row.

    Columns match the brief exactly: documents screened, documents yielding
    >=1 observation, total observations, observations per screened
    document, distinct speakers, earliest/latest observation date.
    """
    screened_by_inst = Counter(r["institution"] for r in run["screening"] if r["institution"] in included)
    docs_with_obs: dict[str, set] = defaultdict(set)
    speakers: dict[str, set] = defaultdict(set)
    dates: dict[str, list] = defaultdict(list)
    obs_count = Counter()

    for r in run["observations"]:
        inst = r["agency"]
        if inst not in included:
            continue
        docs_with_obs[inst].add(r["doc_id"])
        speakers[inst].add(r["speaker"])
        dates[inst].append(r["date"])
        obs_count[inst] += 1

    rows = []
    for inst in included:
        n_screened = screened_by_inst[inst]
        n_obs = obs_count[inst]
        inst_dates = sorted(dates[inst])
        rows.append({
            "institution": inst,
            "documents_screened": n_screened,
            "documents_with_observations": len(docs_with_obs[inst]),
            "total_observations": n_obs,
            "observations_per_screened_document": round(n_obs / n_screened, 2) if n_screened else 0,
            "distinct_speakers": len(speakers[inst]),
            "earliest_observation_date": inst_dates[0] if inst_dates else "",
            "latest_observation_date": inst_dates[-1] if inst_dates else "",
        })

    total_screened = sum(r["documents_screened"] for r in rows)
    total_obs = sum(r["total_observations"] for r in rows)
    all_speakers: set = set().union(*(speakers[i] for i in included)) if included else set()
    all_dates = sorted(d for i in included for d in dates[i])
    rows.append({
        "institution": "Total",
        "documents_screened": total_screened,
        "documents_with_observations": sum(r["documents_with_observations"] for r in rows),
        "total_observations": total_obs,
        "observations_per_screened_document": round(total_obs / total_screened, 2) if total_screened else 0,
        "distinct_speakers": len(all_speakers),
        "earliest_observation_date": all_dates[0] if all_dates else "",
        "latest_observation_date": all_dates[-1] if all_dates else "",
    })
    return rows


def build_table2a(run: dict, included: list[str]) -> tuple[list[dict], int]:
    """Share of observations by primary JEL major category, pooled across included institutions.

    CSV rows carry count and share_pct as separate numeric fields — a raw
    number the PI can check, per the brief's reason for writing a CSV at
    all. The combined "n (xx%)" string is a markdown-rendering concern, not
    a storage concern, and is built at render time by format_pct() instead
    (see main()) — storing it here would print the count twice once it sits
    next to a real "Count" column.
    """
    counts: Counter = Counter()
    titles: dict[str, str] = {}
    for r in run["observations"]:
        if r["agency"] not in included:
            continue
        code = r["jel_primary_major"]
        counts[code] += 1
        titles[code] = r["jel_primary_major_title"]
    total = sum(counts.values())
    rows = [
        {
            "major_code": code,
            "title": titles[code],
            "count": n,
            "share_pct": round(100 * n / total) if total >= MIN_DENOMINATOR_FOR_PERCENT else "",
        }
        for code, n in counts.most_common()
    ]
    return rows, total


def build_table2b(run: dict, included: list[str]) -> tuple[list[dict], int]:
    """Most frequent 3-character (jel_primary_detailed) codes.

    Capped at ten rows or at codes appearing >=3 times, whichever is
    shorter — since counts.most_common() is already sorted descending, the
    codes with count >= 3 are exactly its leading run, so slicing to
    min(10, len(qualifying)) implements both constraints in one step.
    """
    counts: Counter = Counter()
    titles: dict[str, str] = {}
    for r in run["observations"]:
        if r["agency"] not in included:
            continue
        code = r["jel_primary_detailed"]
        counts[code] += 1
        titles[code] = r["jel_primary_detailed_title"]
    total = sum(counts.values())
    ranked = counts.most_common()
    n_qualifying = sum(1 for _, n in ranked if n >= 3)
    chosen = ranked[:min(10, n_qualifying)]
    rows = [
        {
            "detailed_code": code,
            "title": titles[code],
            "count": n,
            "share_pct": round(100 * n / total) if total >= MIN_DENOMINATOR_FOR_PERCENT else "",
        }
        for code, n in chosen
    ]
    return rows, total


def build_figure1(run: dict, included: list[str]) -> tuple[list[dict], list[str]]:
    """Cross-tab of institution x primary JEL major category, raw counts."""
    counts: dict[str, Counter] = defaultdict(Counter)
    majors: set = set()
    for r in run["observations"]:
        if r["agency"] not in included:
            continue
        counts[r["agency"]][r["jel_primary_major"]] += 1
        majors.add(r["jel_primary_major"])
    majors_sorted = sorted(majors)
    rows = [
        {"institution": inst, **{m: counts[inst][m] for m in majors_sorted}}
        for inst in included
    ]
    return rows, majors_sorted


def build_figure2(run: dict, included: list[str]) -> tuple[list[dict], bool, list[str]]:
    """Monthly observation counts across WINDOW_MONTHS, every month shown.

    Stacked by JEL major category if MIN_QUALIFYING_CATEGORIES_TO_STACK
    categories clear MIN_CATEGORY_TOTAL_FOR_OWN_BAND on their pooled total;
    otherwise a single unstacked count per month.
    """
    pooled: Counter = Counter()
    monthly: dict[str, Counter] = defaultdict(Counter)
    for r in run["observations"]:
        if r["agency"] not in included:
            continue
        month = r["date"][:7]
        code = r["jel_primary_major"]
        pooled[code] += 1
        monthly[month][code] += 1

    qualifying = sorted(c for c, n in pooled.items() if n >= MIN_CATEGORY_TOTAL_FOR_OWN_BAND)
    stacked = len(qualifying) >= MIN_QUALIFYING_CATEGORIES_TO_STACK

    if not stacked:
        rows = [{"month": m, "observations": sum(monthly[m].values())} for m in WINDOW_MONTHS]
        return rows, False, []

    has_other = len(qualifying) < len(pooled)
    bands = qualifying + (["Other"] if has_other else [])
    rows = []
    for m in WINDOW_MONTHS:
        row = {"month": m}
        for b in qualifying:
            row[b] = monthly[m].get(b, 0)
        if has_other:
            row["Other"] = sum(n for c, n in monthly[m].items() if c not in qualifying)
        rows.append(row)
    return rows, True, bands


def write_csv(path: Path, rows: list[dict]) -> None:
    """Write rows to path; the header is the union of every row's keys, in first-seen order."""
    fieldnames: list[str] = []
    for row in rows:
        for k in row.keys():
            if k not in fieldnames:
                fieldnames.append(k)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def md_table(headers: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


def note_line(n_institutions: int, n_observations: int) -> str:
    """The window/institution-count/observation-count note every exhibit carries, per the brief."""
    return f"*Window: {WINDOW_START} to {WINDOW_END}. Institutions: {n_institutions}. Observations: {n_observations}.*"


# ---------------------------------------------------------------------------
# Item-3 checks: a few minutes of deliberate looking, not incidental noticing.
# ---------------------------------------------------------------------------

def integrity_checks(run: dict, included: list[str]) -> list[str]:
    """Return findings worth a human's attention — empty list means nothing found, not "not checked"."""
    findings = []
    kept = [r for r in run["observations"] if r["agency"] in included]

    dup_quotes = Counter((r["doc_id"], r["direct_quote"]) for r in kept)
    dups = [k for k, v in dup_quotes.items() if v > 1]
    if dups:
        findings.append(f"{len(dups)} duplicate (doc_id, direct_quote) pairs among kept observations.")

    out_of_window = [r for r in kept if not (WINDOW_START <= r["date"] <= WINDOW_END)]
    if out_of_window:
        ids = ", ".join(r["doc_id"] for r in out_of_window[:5])
        findings.append(f"{len(out_of_window)} kept observations fall outside {WINDOW_START}..{WINDOW_END}: {ids}")

    warn_doc_ids = {w["doc_id"] for w in run["summary"].get("speaker_warnings", [])}
    ambiguous = [
        w for w in run["summary"].get("speaker_warnings", [])
        if "eligible speakers" in w["warning"]
    ]
    for w in ambiguous:
        affected = [r for r in kept if r["doc_id"] == w["doc_id"]]
        status = f"{len(affected)} kept observation(s) affected" if affected else "no kept observations affected"
        findings.append(f"officeholders.csv has an overlapping-spell defect ({w['warning']}) — {status}.")

    n_flagged = sum(1 for r in kept if r["doc_id"] in warn_doc_ids)
    if n_flagged:
        findings.append(
            f"{n_flagged} of {len(kept)} kept observations come from a document where the manifest's "
            "speaker string differs from the officeholder table's (mostly honorific/title formatting, "
            "e.g. 'The Rt Hon X MP' vs 'X' — the officeholder table's resolution is what was used). "
            "Not re-verified name-by-name; the one structural defect above (overlapping spells) is the "
            "one checked in full."
        )

    return findings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path, help="e.g. runs/multi-v2")
    args = parser.parse_args()

    script_path = Path(__file__)
    run_dir = args.run_dir
    out_dir = script_path.parent / run_dir.name
    out_dir.mkdir(parents=True, exist_ok=True)

    run = load_run(run_dir)
    included, excluded = institution_split(run)
    if not included:
        sys.exit(f"No institution in {run_dir} has any kept observations — nothing to build.")

    table1 = build_table1(run, included)
    table2a, table2a_total = build_table2a(run, included)
    table2b, table2b_total = build_table2b(run, included)
    fig1_rows, fig1_majors = build_figure1(run, included)
    fig2_rows, fig2_stacked, fig2_bands = build_figure2(run, included)
    findings = integrity_checks(run, included)
    total_obs = table1[-1]["total_observations"]

    write_csv(out_dir / "table1_sample_composition.csv", table1)
    write_csv(out_dir / "table2a_topic_distribution_major.csv", table2a)
    write_csv(out_dir / "table2b_topic_distribution_codes.csv", table2b)
    write_csv(out_dir / "figure1_jel_major_by_institution.csv", fig1_rows)
    write_csv(out_dir / "figure2_observations_by_month.csv", fig2_rows)

    # --- exhibits.md ---------------------------------------------------
    parts = []
    parts.append(f"# Descriptive exhibits — {run_dir.name}\n")

    parts.append("## Table 1 — Sample composition")
    parts.append("One row per institution with at least one kept observation; a total row follows.")
    parts.append(note_line(len(included), total_obs))
    headers = ["Institution", "Documents screened", "Documents w/ obs.", "Total obs.",
               "Obs. per screened doc.", "Distinct speakers", "Earliest obs.", "Latest obs."]
    rows = [[r["institution"], r["documents_screened"], r["documents_with_observations"],
             r["total_observations"], r["observations_per_screened_document"],
             r["distinct_speakers"], r["earliest_observation_date"], r["latest_observation_date"]]
            for r in table1]
    parts.append(md_table(headers, rows))
    parts.append("")

    parts.append("## Table 2 — Topic distribution")
    parts.append("Panel A: share of observations by primary JEL major category. Panel B: most frequent 3-character primary codes.")
    parts.append(note_line(len(included), total_obs))
    parts.append("**Panel A**")
    parts.append(md_table(["Major", "Title", "Count (share)"],
                           [[r["major_code"], r["title"], format_pct(r["count"], table2a_total)] for r in table2a]))
    parts.append("")
    parts.append("**Panel B**")
    parts.append(md_table(["Code", "Title", "Count (share)"],
                           [[r["detailed_code"], r["title"], format_pct(r["count"], table2b_total)] for r in table2b]))
    parts.append("")

    parts.append("## Figure 1 — Primary JEL major category by institution")
    parts.append("Cross-tab of raw counts; no plotting library is installed in this environment, so the underlying table is the exhibit.")
    parts.append(note_line(len(included), total_obs))
    fig1_headers = ["Institution"] + fig1_majors
    fig1_md_rows = [[r["institution"]] + [r[m] for m in fig1_majors] for r in fig1_rows]
    parts.append(md_table(fig1_headers, fig1_md_rows))
    parts.append("*Figure could not be rendered — no plotting library installed; see figure1_jel_major_by_institution.csv.*")
    parts.append("")

    parts.append("## Figure 2 — Observations by month")
    stack_note = "stacked by JEL major category" if fig2_stacked else "unstacked (see judgement calls in the covering note)"
    parts.append(f"Monthly counts across the full pilot window, {stack_note}. Every month in the window is shown, including zero-observation months.")
    parts.append(note_line(len(included), total_obs))
    fig2_headers = ["Month"] + (fig2_bands if fig2_stacked else ["Observations"])
    if fig2_stacked:
        fig2_md_rows = [[r["month"]] + [r[b] for b in fig2_bands] for r in fig2_rows]
    else:
        fig2_md_rows = [[r["month"], r["observations"]] for r in fig2_rows]
    parts.append(md_table(fig2_headers, fig2_md_rows))
    parts.append("*Figure could not be rendered — no plotting library installed; see figure2_observations_by_month.csv.*")
    parts.append("")

    parts.append("## Conditional fifth exhibit — relevance-score bands")
    parts.append(
        f"Dropped. `{RELEVANCE_SCORE_COLUMN}` is not a column this pipeline emits "
        "(assemble.py notes it is \"deferred by design\"), so the field guide's cut points "
        "(0.60-0.74, 0.75-0.89, 0.90-1.00) have nothing to bin. This is a schema gap, not a "
        f"function of the >=60-observation gate — {total_obs} observations survived, comfortably "
        "over that threshold."
    )
    parts.append("")

    (out_dir / "exhibits.md").write_text("\n".join(parts), encoding="utf-8")

    # --- covering_note.md ------------------------------------------------
    prov = git_provenance(script_path)
    prompt_versions = {(r["prompt_version"], r["prompt_sha"]) for r in run["observations"]}
    prompt_str = (
        ", ".join(f"{v}/{s}" for v, s in sorted(prompt_versions))
        if prompt_versions else "none recorded"
    )
    note = []
    note.append(f"# Covering note — {run_dir.name}\n")
    note.append("## Provenance")
    note.append(f"- Run directory: `{run_dir}`")
    note.append(f"- Git commit: `{prov.get('commit')}` (branch `{prov.get('branch', 'unknown')}`)")
    if prov.get("dirty_reference_files"):
        note.append(
            "  - **Uncommitted changes under `src/eps/reference/` at run time:** "
            + ", ".join(prov["dirty_reference_files"])
            + ". A fresh checkout of the commit above will not exactly reproduce the officeholder "
            "resolution this run used."
        )
    note.append(
        f"- Prompt fingerprint (prompt_version/prompt_sha, from observations_internal.csv — "
        f"`summary.json` does not carry this field for this run): {prompt_str}"
    )
    note.append(f"- Harvest window: {WINDOW_START} to {WINDOW_END}")
    note.append(f"- Script run date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')} (UTC)")
    note.append("")

    note.append("## Required caveats")
    note.append(
        "1. This is a four-department pilot covering 1 January to 31 July 2026, not the full "
        "24-department UK collection. The US collection has not started."
    )
    note.append(
        "2. JEL classification currently over-assigns residual codes. The topic distribution in "
        "Table 2 and Figure 1 reflects that and will change once the classification work concludes."
    )
    note.append(
        "3. The DfE observations here were harvested, whereas earlier DfE runs were hand-picked "
        "from a manifest. These figures are comparable across the departments in this run and are "
        "not continuous with the earlier DfE series."
    )
    note.append(
        "4. Documents excluded by the boundary-date fix: **count not established.** This could not "
        "be determined from `runs/{}` alone — if the fix operates upstream of this run's manifest, "
        "no exclusion log distinguishing it from other manifest-preparation exclusions exists in "
        "this run directory. Flagging as missing rather than guessing a number.".format(run_dir.name)
    )
    note.append(
        "5. *(Added, not in the brief's list)* Two institutions screened in this run — Ministry of "
        "Defence and Ministry of Justice — are excluded from every exhibit above at explicit "
        "instruction, not the brief's: {}. The brief's own small-N discipline says a "
        "zero-observation institution should appear as a full row of zeros / an empty column, "
        "because that null result is itself a finding. This run departs from that rule.".format(
            "; ".join(f"{inst} ({stats['documents_screened']} screened, {stats['documents_eligible']} eligible, 0 kept)"
                      for inst, stats in excluded.items())
        )
    )
    note.append("")

    note.append("## Exhibits not built")
    note.append(
        f"- Conditional fifth exhibit (relevance-score bands): dropped. `{RELEVANCE_SCORE_COLUMN}` "
        "is not emitted by the pipeline (deferred by design), independent of the >=60-observation gate."
    )
    note.append("")

    note.append("## Judgement calls")
    note.append(
        "1. Institutions with zero kept observations are dropped from every exhibit entirely "
        "(constant `DROP_ZERO_OBSERVATION_INSTITUTIONS`), overriding the brief's zero-row "
        "convention — done at explicit instruction; see required caveat 5."
    )
    note.append(
        "2. Figure 2 stacks by JEL major category only if at least two categories clear a pooled "
        f"total of {MIN_CATEGORY_TOTAL_FOR_OWN_BAND}; categories below that are pooled into "
        "'Other' rather than dropped. For this run: " + ("stacked." if fig2_stacked else "not stacked — fewer than two categories qualified.")
    )
    note.append(
        "3. Table 2 Panel B uses `jel_primary_detailed`, the three-character code column, per the "
        "brief's literal description."
    )
    note.append(
        "4. Prompt fingerprint sourced from `observations_internal.csv` (`prompt_version`/"
        "`prompt_sha`) rather than `summary.json`, which carries no such field for this run."
    )
    note.append(
        "5. Output directory is `analysis/<run-name>/`, derived from the run directory's basename, "
        "matching the brief's `analysis/multi-v1/` example generalised to any run."
    )
    note.append(
        "6. 'Distinct speakers' (Table 1) counts only speakers who appear in a kept observation, "
        "not every officeholder eligible during the window."
    )
    note.append(
        "7. Table 1's Total row and 'observations per screened document' use only the included "
        f"institutions' screened-document counts ({table1[-1]['documents_screened']}), not the "
        f"full run's {sum(1 for _ in run['screening'])} screened documents across all four "
        "institutions."
    )
    note.append(
        "8. Figure 2's month axis is fixed to the brief's stated pilot window (seven calendar "
        "months) rather than the data's own min/max date, so an all-zero month at either edge "
        "stays visible."
    )
    note.append("")

    note.append("## Things that look wrong, not just small")
    if findings:
        for f in findings:
            note.append(f"- {f}")
    else:
        note.append("- None found.")
    note.append("")

    (out_dir / "covering_note.md").write_text("\n".join(note), encoding="utf-8")

    print(f"Wrote exhibits and covering note to {out_dir}")


if __name__ == "__main__":
    main()
