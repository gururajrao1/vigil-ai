# VigilAI — Live Demo Script (~8–10 minutes)

Login: **admin@vigilai.dev / admin123**  
Backend `http://127.0.0.1:8001` · Frontend `http://localhost:5173`

> **Before you present:** Prefer the existing DB (don't Reset mid-demo). Optionally run
> **Sources → Google News + Life-science + FAERS** once. Open one rich signal
> (isotretinoin / device) so evidence is cached.

---

## 0. Framing (20s)
> "Post-market patients talk online long before many ICSRs land. VigilAI listens worldwide
> — drugs, vaccines, and devices — with statistical rigor, explainability, and regulator-ready export.
> Most sources need no API key; YouTube/X/Firecrawl are optional enhancers."

## 1. Overview (40s)
KPI cards, region/language/platform, AE rate. "Every number traces to scrubbed posts."

## 2. Polyglot sources (45s)
**Sources** page — show live badges (YouTube should be `live` if key set).
DemoBar: **Google News + Life-science + FAERS** (or **Command Center** one-liner below).
Mention self-heal: Live Feed chips 🟢🟡🔴.

## 3. Command Center (30s) — *Algo differentiator*
**Command Center** → `crawl google news about ozempic side effects` → Dispatch.
Show slot-fill badges + ingested count. Audit chain panel on the right.

## 4. Safety Signals hero (90s)
SDR filter → open a strong drug signal:
- 4-gate AE · PRR/ROR/χ²/EB05/IC025 · WHO-UMC · spike
- **Thread corroboration RAG** (Red/Amber/Green)
- Trust / Sybil badge · Verify Ed25519 chain
- Evidence FAERS/DailyMed/PubMed · **E2B** + **CIOMS** download
- Copilot assessment

## 5. Devices / vaccine / geo (45s)
Device signal (MAUDE/EUDAMED) · Vaccine AESI · Geo Clusters · SMQ / Class Effects (quick)

## 6. Ops / compliance (40s)
KPIs & SPC · Alerts → **Notify** (simulated webhook) · Lifecycle Kanban · Federated/DP · Forge

## 7. Forum onboard (20s, optional)
**Forum Onboarding** → Propose config → **Analyze + ingest samples**

## Close (15s)
> "From patient voice → grounded signal → ICSR export — explainable, offline-first, worldwide."

---

## YouTube note
If YouTube returns 0 posts with a "IP address restriction" note, Google is seeing your
**IPv6** egress. In Cloud Console → API key → Application restrictions, add that IPv6
(or set Application restrictions = None; keep YouTube Data API v3 only).

## If Wi-Fi fails
Offline-first stack still runs (lexicon NER path, stats, exports, Forge deterministic).
Skip live crawls; use existing corpus + synthetic stream.
