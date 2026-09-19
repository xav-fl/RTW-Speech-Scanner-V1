"""Quick pilot run on NSF documents."""
import sys, pickle, shutil, pathlib
sys.path.insert(0, "src")

from eps.pipeline import build, load_officeholders, load_taxonomy, load_active_codes
from eps.extract import Extractor
from eps.providers import AnthropicProvider
from eps.validate import OfficeholderTable

# Load data
print("Loading corpus...")
docs_all = pickle.load(open("runs/us-full/documents.pkl", "rb"))

# Filter to NSF only
docs = [d for d in docs_all if d.institution == "National Science Foundation"]
print(f"  {len(docs)} NSF documents loaded")

# Initialize pipeline
print("Initializing pipeline...")
taxonomy = load_taxonomy()
provider = AnthropicProvider()
extractor = Extractor(
    taxonomy, 
    provider=provider,
    active=load_active_codes(),
    identity_mode="blind"
)
holders = OfficeholderTable([])

# Run extraction and classification
print("Extracting and classifying...")
observations = {}
for i, doc in enumerate(docs, 1):
    if i % 10 == 0:
        print(f"  {i}/{len(docs)}...")
    obs = extractor.extract(doc, doc.speaker_hint or "", run_id="nsf-pilot")
    if obs:
        observations[doc.doc_id] = obs

print(f"  {sum(len(o) for o in observations.values())} observations extracted")

# Build output
print("Building output...")
out = pathlib.Path("runs/nsf-pilot/out")
shutil.rmtree(out, ignore_errors=True)
summary = build(docs, observations, taxonomy, holders, out, run_id="nsf-pilot")

print("\n=== RESULTS ===")
for k, v in summary.items():
    if isinstance(v, dict):
        for k2, v2 in v.items():
            print(f"  {k2}: {v2}")
    else:
        print(f"  {k}: {v}")

print(f"\n✓ Output in: runs/nsf-pilot/out/")
