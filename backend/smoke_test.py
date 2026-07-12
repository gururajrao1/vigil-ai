"""Offline end-to-end smoke test of the VigilAI pipeline."""
from app.database import SessionLocal, init_db
from app.ingestion.synthetic import generate_corpus
from app.pipeline import ingest_posts, knowledge_graph, recompute_signals
from app.api.helpers import dashboard_stats

init_db()
db = SessionLocal()

posts = generate_corpus(days=21)
print(f"generated corpus: {len(posts)} posts")

new = ingest_posts(db, posts)
print(f"ingested + processed: {new}")

stats = recompute_signals(db)
print("recompute:", stats)

ds = dashboard_stats(db)
print("ae_rate:", ds["ae_rate"], "signals:", ds["signal_count"], "alerts:", ds["alert_count"],
      "spikes:", ds["spike_count"])
print("strength:", ds["strength_distribution"])
print("severity:", ds["severity_distribution"])
print("top_drugs:", ds["top_drugs"][:5])

from app.models import Signal
top = db.query(Signal).order_by(Signal.prr.desc()).limit(6).all()
print("\nTOP SIGNALS:")
for s in top:
    print(f"  {s.drug:14s} -> {s.symptom:14s} PRR={s.prr:6.2f} chi2={s.chi_square:6.2f} "
          f"n={s.post_count} {s.strength:8s} {s.severity:8s} WHO-UMC={s.who_umc} spike={s.spike_flag}")

# MaxSPRT verification
crossed = db.query(Signal).filter(Signal.maxsprt_crossed.is_(True)).count()
total = db.query(Signal).count()
print(f"\nMaxSPRT: {crossed}/{total} signals crossed the sequential boundary")
sample = db.query(Signal).filter(Signal.maxsprt_crossed.is_(True)).first()
if sample:
    print(f"  Example: {sample.drug} -> {sample.symptom} LLR={sample.maxsprt_llr:.3f}")

kg = knowledge_graph(db)
print(f"\nKG nodes={kg['stats']['node_count']} edges={kg['stats']['edge_count']}")
print("hubs:", [(h['label'], h['centrality']) for h in kg['hubs']])

db.close()
print("\nSMOKE_TEST_OK")
