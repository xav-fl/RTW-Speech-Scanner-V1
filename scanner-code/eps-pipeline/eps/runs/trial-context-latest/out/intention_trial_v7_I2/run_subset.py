"""I2 trial on a targeted subset of the v7 quotes, compared row by row with I1.

A full re-run costs ~221 calls. The I2 rule changes can only move certain rows,
so this re-tags those plus a random control drawn from the rest:

  targeted  every row outside the four big labels (commits: pledges/announces,
            reports: completed/ongoing) -- the categories whose rules changed
  ctx_cue   every row whose I1 label cue was only in the context (rule 1)
  cited     the rows the project lead cited by name
  control   a seeded random draw from the big four, to show whether I2 moves
            rows its rule changes should not touch (and the causal flag)

Run from scanner-code/eps-pipeline/eps with ANTHROPIC_API_KEY set:
    python runs/trial-context-latest/out/intention_trial_v7_I2/run_subset.py
Responses go through the run's cache, so a re-run replays them for free.
"""

from __future__ import annotations

import csv
import json
import pickle
import random
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUN = HERE.parents[1]
sys.path.insert(0, str(RUN.parents[1] / "src"))

from eps.assemble import intention_label, intention_values  # noqa: E402
from eps.context import quote_id  # noqa: E402
from eps.extract import ResponseCache  # noqa: E402
from eps.intention import IntentionTagger, cue_in_input, write_intention_log  # noqa: E402
from eps.models import IntentionResult  # noqa: E402
from eps.providers import get_provider  # noqa: E402

SEED = 20260925
CONTROL_N = 15
BIG_FOUR = {
    "Commits to action: pledges future action",
    "Commits to action: announces decision",
    "Reports existing action: completed action",
    "Reports existing action: ongoing implementation",
}
CITED = ("National Youth Strategy", "coordination and preparedness",
         "tackle health inequalities")

I1 = RUN / "out" / "intention_trial_v7"
rows = list(csv.DictReader(open(I1 / "observations_internal.csv", encoding="utf-8")))
i1 = {json.loads(l)["quote_id"]: json.loads(l)
      for l in open(I1 / "intention_log.jsonl", encoding="utf-8")}
docs = pickle.load(open(RUN / "documents.pkl", "rb"))

why: dict[str, list[str]] = {}
for r in rows:
    q, old = quote_id(r), i1[quote_id(r)]
    reasons = []
    if r["intention"] not in BIG_FOUR:
        reasons.append("targeted")
    if old["status"] == "tagged" and old["broad"] != "unclear" and not cue_in_input(
            old["cue"] or "", r["direct_quote"]):
        reasons.append("ctx_cue")
    if any(c in r["direct_quote"] for c in CITED):
        reasons.append("cited")
    if reasons:
        why[q] = reasons
rest = [r for r in rows if quote_id(r) not in why]
for r in random.Random(SEED).sample(rest, CONTROL_N):
    why[quote_id(r)] = ["control"]

subset = [r for r in rows if quote_id(r) in why]
print(f"{len(subset)} of {len(rows)} quotes: "
      f"{dict(Counter(x for v in why.values() for x in v))}", flush=True)

tagger = IntentionTagger(provider=get_provider("anthropic", "claude-sonnet-4-6"),
                         cache=ResponseCache(RUN / "cache"))
results = tagger.run(subset, docs)
write_intention_log(results, HERE)


def flags(res) -> tuple[str, str]:
    v = intention_values(res)
    return v["has_quantified_target"], v["claims_causal_effect"]


with open(HERE / "i1_vs_i2_comparison.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["selected_because", "agency", "speaker", "date", "direct_quote",
                "i1_intention", "i2_intention", "label_changed",
                "i1_secondary", "i2_secondary",
                "i1_target", "i2_target", "i1_causal", "i2_causal", "causal_changed",
                "i2_cue", "i2_causal_cue", "i2_rationale", "i2_failure_reason",
                "quote_id"])
    for r, new in zip(subset, results):

        old = IntentionResult(**i1[new.quote_id])
        a, b = intention_values(old)["intention"], intention_values(new)["intention"]
        (ot, oc), (nt, nc) = flags(old), flags(new)
        w.writerow([
            " ".join(why[new.quote_id]), r["agency"], r["speaker"], r["date"],
            r["direct_quote"], a, b, "yes" if a != b else "",
            intention_label(old.secondary_broad, old.secondary_sub),
            intention_label(new.secondary_broad, new.secondary_sub),
            ot, nt, oc, nc, "yes" if oc != nc else "",
            new.cue or "", new.causal_cue or "", new.rationale or "",
            new.failure_reason or "", new.quote_id,
        ])

s = Counter(intention_values(r)["intention"] for r in results)
print(json.dumps({"quotes": len(results),
                  "not_tagged": dict(Counter(r.failure_reason for r in results
                                             if r.status == "failed")),
                  "labels": dict(s.most_common())}, indent=2))
