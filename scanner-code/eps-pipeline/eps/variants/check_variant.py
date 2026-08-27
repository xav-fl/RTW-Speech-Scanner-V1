"""Offline checks for one variant: no network, no API key."""
import csv, json, sys, tempfile
from pathlib import Path
sys.path.insert(0, "src")
from eps.extract import Extractor, JEL_SYSTEM, PROMPT_VERSION, prompt_fingerprint
from eps.pipeline import load_documents, load_taxonomy, load_officeholders, build
from eps.providers import FakeProvider
from eps.validate import resolve_speaker

docs = load_documents("runs/dfe-v2/documents.pkl")
tax, offs = load_taxonomy(), load_officeholders()
doc = docs[0]
speaker, _, _ = resolve_speaker(doc, offs)
unit = next(u for u in doc.units if u.attributable)
seen = {}

def responder(system, user, *a):
    if "DOCUMENT UNITS" in user:
        return json.dumps({"observations": [{"unit_ids": [unit.unit_id], "anchor": None,
                                             "reason": "CANARY-REASON"}]})
    if "MAJOR CATEGORIES" in user:
        seen["stage1_jel"] = user
        return json.dumps({"primary": "J", "secondary": []})
    seen["stage2"] = user
    return json.dumps({"mechanism": "teacher recruitment incentive",
                       "sub": "J24", "detailed": ""})

obs = Extractor(tax, provider=FakeProvider(responder)).extract(doc, speaker, run_id="check")
with tempfile.TemporaryDirectory() as td:
    build([doc], {doc.doc_id: obs}, tax, offs, td, run_id="check")
    row = list(csv.DictReader(open(Path(td, "observations_internal.csv"), encoding="utf-8")))[0]
    rel = list(csv.DictReader(open(Path(td, "dataset.csv"), encoding="utf-8")))[0]

s1, s2 = seen["stage1_jel"], seen["stage2"]
s1_head = s1.split("MAJOR CATEGORIES:")[0]
s2_head = s2.split("AVAILABLE CODES:")[0]
order = [s2.find(x) for x in ("QUOTATION:", "AVAILABLE CODES:", 'Return {')]
print(f"PROMPT_VERSION      {PROMPT_VERSION}")
print(f"prompt_sha          {prompt_fingerprint()}")
print(f"stage-1 JEL prompt  {len(s1)} chars, {s1.count(chr(10))+1} lines, "
      f"~{len(s1)//4} tokens")
print(f"  subcategories shown: {'  ' in s1.split('MAJOR CATEGORIES:')[1]}")
print(f"  3-char codes shown : {any(len(l.strip().split(' ')[0])==3 for l in s1.split('MAJOR CATEGORIES:')[1].splitlines() if l.strip())}")
print(f"stage-2 prompt      {len(s2)} chars; order quote<codes<return: {order == sorted(order)}")
print(f"mechanism asked     {'mechanism' in s2_head}")
print(f"csv model_mechanism {row['model_mechanism']!r}")
print(f"csv model_reason    {row['model_reason']!r}")
print(f"mechanism in release csv: {'model_mechanism' in rel}")
print(f"stage-1 reason leaked into stage 2 / stage-1 JEL: "
      f"{'CANARY-REASON' in s2} / {'CANARY-REASON' in s1}")
bad = [t for t in ("Government Policy", "General", "I28", "I38", "L40")
       if t in JEL_SYSTEM or t in s1_head or t in s2_head]
print(f"residual code names in instruction text: {bad or 'none'}")
print(f"jel primary: {row['jel_primary_major']}/{row['jel_primary_sub']}/{row['jel_primary_detailed']}")
