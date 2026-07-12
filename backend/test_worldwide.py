"""End-to-end worldwide pipeline test (offline-capable)."""
import json
import sys

# Windows consoles default to cp1252, which can't encode clinical glyphs like the
# chi-square symbol used in narratives; force UTF-8 so prints never crash.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.database import SessionLocal, init_db
from app.ingestion.synthetic import generate_corpus
from app.pipeline import ingest_posts, knowledge_graph, recompute_signals
from app.api.helpers import dashboard_stats, signal_to_dict
from app.models import Signal
from app import llm
from app.nlp.entities import extract_entities
from app.nlp.pii import scrub

print("LLM:", llm.status())

# entity extraction sanity (also warms transformer NER)
ents = extract_entities("Started Accutane for acne and got terrible depression and hair loss.")
print("ENTITIES drugs:", [(d['normalized'], d.get('atc')) for d in ents['drugs']])
print("ENTITIES symptoms:", [(s['normalized'], s.get('soc')) for s in ents['symptoms']])

# PII sanity (worldwide)
scrubbed, found = scrub("Contact me at john.doe@gmail.com or +1 415 555 0132, SSN 123-45-6789, Aadhaar 1234 5678 9012")
print("PII scrubbed:", scrubbed)
print("PII found:", found)

init_db()
db = SessionLocal()
posts = generate_corpus(days=4)
print("corpus size:", len(posts))
new = ingest_posts(db, posts)
print("ingested:", new)
stats = recompute_signals(db)
print("recompute:", stats)

ds = dashboard_stats(db)
print("regions:", ds["region_distribution"])
print("languages:", ds["language_distribution"])
print("translated:", ds["translated_posts"], "countries:", ds["country_count"])
print("soc:", ds["soc_distribution"])

top = db.query(Signal).order_by(Signal.prr.desc()).first()
if top:
    d = signal_to_dict(top)
    print("TOP SIGNAL:", d["drug"], "->", d["meddra"]["pt"], "| PRR", d["prr"],
          "| SOC", d["meddra"]["soc"], "| ATC", d["drug_atc"],
          "| WHO", d["who_umc"], "| sev", d["severity"], "| spike", d["spike_flag"])
    print("NARRATIVE(", d["narrative_source"], "):", (d["narrative"] or "")[:200])

kg = knowledge_graph(db)
print("KG nodes/edges:", kg["stats"])
db.close()
print("=== TEST OK ===")
