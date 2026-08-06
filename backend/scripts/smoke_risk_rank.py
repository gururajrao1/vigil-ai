from app.database import SessionLocal
from app.analytics.risk_ranking import rank_high_risk_populations
from app.analytics.risk_strata import list_candidate_pairs

db = SessionLocal()
pairs = list_candidate_pairs(db, limit=5)["pairs"]
print("pairs", pairs[:3])
if pairs:
    p, a = pairs[0]["product_id"], pairs[0]["target_ae_pt"]
    r = rank_high_risk_populations(db, p, a, top_n=5, include_exploratory=True)
    print("verdict", r["verdict"])
    print("n_exposed", r.get("n_drug_exposed"), "baseline", r.get("baseline_p_ae"), "domain", r.get("product_domain"))
    for x in r["ranked"][:5]:
        print(
            " REM=", x["risk_elevation_multiplier"],
            "chi2=", x["chi_square_yates"],
            "gates=", x["passes_gates"],
            "|", x["label"],
        )
        print("  mit:", x["mitigation"]["trigger"])
        if x.get("attribution_narrative"):
            print(" ", x["attribution_narrative"][:120])
else:
    print("no pairs")
db.close()
