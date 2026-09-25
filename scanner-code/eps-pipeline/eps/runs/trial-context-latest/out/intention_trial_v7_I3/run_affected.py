"""I3 re-run on the rows its two changes can affect, compared with I1 and I2.

  states_view   every row labelled "States view without action" under I1 or
                I2: the rows the Q3 fix targets, and the genuine value
                judgements it must not dislodge
  cited         the three rows the project lead cited by name
  continuous    rows in the I2 subset whose quote uses "we are" / "we're",
                for the new present-continuous line in Q6

Caveat: the Q3 counter-examples in the prompt are patterns taken from five of
these rows, so their movement is partly in-sample. The value-judgement rows
that should stay put, and the continuous rows, are the cleaner test.

Run from scanner-code/eps-pipeline/eps with ANTHROPIC_API_KEY set:
    python runs/trial-context-latest/out/intention_trial_v7_I3/run_affected.py
"""

from __future__ import annotations

import csv
import json
import pickle
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUN = HERE.parents[1]
sys.path.insert(0, str(RUN.parents[1] / "src"))

from eps.assemble import intention_values  # noqa: E402
from eps.context import quote_id  # noqa: E402
from eps.extract import ResponseCache  # noqa: E402
from eps.intention import IntentionTagger, write_intention_log  # noqa: E402
from eps.models import IntentionResult  # noqa: E402
from eps.providers import get_provider  # noqa: E402

CITED = ("National Youth Strategy", "coordination and preparedness",
         "tackle health inequalities")
CONTINUOUS = re.compile(r"\bwe(?: are|[’']re)\b", re.I)

OUT = RUN / "out"
rows = list(csv.DictReader(open(OUT / "intention_trial_v7" / "observations_internal.csv",
                                encoding="utf-8")))


def load(path: Path) -> dict[str, IntentionResult]:
    return {json.loads(l)["quote_id"]: IntentionResult(**json.loads(l))
            for l in open(path, encoding="utf-8")}


i1 = load(OUT / "intention_trial_v7" / "intention_log.jsonl")
i2 = load(OUT / "intention_trial_v7_I2" / "intention_log.jsonl")
label = lambda res: intention_values(res)["intention"] if res else ""  # noqa: E731

why: dict[str, list[str]] = {}
for r in rows:
    q = quote_id(r)
    reasons = []
    if any(label(x.get(q)).startswith("States view") for x in (i1, i2)):
        reasons.append("states_view")
    if any(c in r["direct_quote"] for c in CITED):
        reasons.append("cited")
    if q in i2 and CONTINUOUS.search(r["direct_quote"]):
        reasons.append("continuous")
    if reasons:
        why[q] = reasons

subset = [r for r in rows if quote_id(r) in why]
print(f"{len(subset)} quotes: {dict(Counter(x for v in why.values() for x in v))}",
      flush=True)

tagger = IntentionTagger(provider=get_provider("anthropic", "claude-sonnet-4-6"),
                         cache=ResponseCache(RUN / "cache"))
results = tagger.run(subset, pickle.load(open(RUN / "documents.pkl", "rb")))
write_intention_log(results, HERE)

with open(HERE / "i1_i2_i3_comparison.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["selected_because", "agency", "direct_quote", "i1_intention",
                "i2_intention", "i3_intention", "changed_from_i2",
                "i1_causal", "i2_causal", "i3_causal", "i3_cue", "i3_rationale",
                "i3_failure_reason", "quote_id"])
    for r, new in zip(subset, results):
        q = new.quote_id
        a, b, c = label(i1.get(q)), label(i2.get(q)), label(new)
        w.writerow([
            " ".join(why[q]), r["agency"], r["direct_quote"], a, b, c,
            "yes" if b and b != c else "",
            intention_values(i1[q])["claims_causal_effect"] if q in i1 else "",
            intention_values(i2[q])["claims_causal_effect"] if q in i2 else "",
            intention_values(new)["claims_causal_effect"],
            new.cue or "", new.rationale or "", new.failure_reason or "", q,
        ])

print(json.dumps(dict(Counter(label(r) for r in results).most_common()), indent=2))
