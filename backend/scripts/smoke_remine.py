"""Smoke-test the remine lab HTTP surface end to end."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

c = TestClient(app)

r = c.get("/api/remine/lab?limit=5")
print("GET /api/remine/lab ->", r.status_code)
d = r.json()
print(" eligible", d["total_eligible"], "matching", d["total_matching"],
      "cards", len(d["cards"]), "has_more", d["has_more"])
print(" facets", {k: v for k, v in d["facets"].items() if v})
print(" method keys", sorted(d["method"].keys()))
print(" products", len(d["products"]), "events", len(d["events"]))

for qs in ["?q=warfarin", "?only=actionable", "?only=unmasked&sort=coreporting",
           "?limit=10&offset=10", "?sort=risk", "?only=devices", "?q=zzznotfound",
           "?limit=999", "?only=bogus&sort=bogus", "?offset=-5"]:
    rr = c.get("/api/remine/lab" + qs)
    print("  ", qs, "->", rr.status_code, "n=", len(rr.json().get("cards", [])))

top = d["cards"][0]
params = [("drug", top["drug"]), ("event", top["event"])]
params += [("exclude_drugs", m) for m in top["maskers"]]
rp = c.get("/api/remine/run", params=params)
print("GET /api/remine/run ->", rp.status_code)
j = rp.json()
print(" outcome", j["outcome"], "| MR", j["masking_ratio"],
      "| co", j["coreporting_ratio"], "| comp", j["comparator_ratio"])

sid = top.get("signal_id")
if sid:
    ru = c.get("/api/signals/%d/unmask" % sid)
    print("GET /signals/%d/unmask ->" % sid, ru.status_code, ru.json()["outcome"])
    rm = c.get("/api/signals/%d/masking" % sid)
    m = rm.json()
    print("GET /signals/%d/masking ->" % sid, rm.status_code,
          "can_remine", m["can_remine"], "suggested", m["suggested_exclude"])

# a pair with no persisted signal row must still remine
orphan = next((x for x in c.get("/api/remine/lab?limit=200").json()["cards"]
               if not x["signal_id"]), None)
if orphan:
    p = [("drug", orphan["drug"]), ("event", orphan["event"])]
    p += [("exclude_drugs", m) for m in orphan["maskers"]]
    ro = c.get("/api/remine/run", params=p)
    print("orphan pair (%s / %s) ->" % (orphan["drug"], orphan["event"]),
          ro.status_code, ro.json()["outcome"])
else:
    print("no orphan pairs — every card resolves to a signal row")
