# VigilAI — Features, Origins & How to Use

> Complete feature catalogue organised by the three reference GitHub projects VigilAI was synthesised from, plus VigilAI-original expansions.  
> **Login:** `admin@vigilai.dev` / `admin123`  
> **Frontend:** http://localhost:5173 · **Backend:** http://127.0.0.1:8001

---

## Table of contents

1. [What VigilAI is](#1-what-vigilai-is)
2. [Quick start](#2-quick-start)
3. [Feature map by GitHub source](#3-feature-map-by-github-source)
4. [A — Algo-Pharma lineage](#4-a--algo-pharma-lineage)
5. [B — pan-IITian / SignalRx lineage](#5-b--pan-iitian--signalrx-lineage)
6. [C — PulseAI lineage](#6-c--pulseai-lineage)
7. [D — VigilAI original (beyond the three)](#7-d--vigilai-original-beyond-the-three)
8. [Page-by-page how to use](#8-page-by-page-how-to-use)
9. [Data sources registry](#9-data-sources-registry)
10. [Optional API keys](#10-optional-api-keys)
11. [Demo tips & slow sources](#11-demo-tips--slow-sources)

---

## 1. What VigilAI is

**VigilAI** is a worldwide pharmacovigilance (PV) platform: ingest patient / news / regulatory chatter → scrub PII → extract clinical entities → detect adverse events → compute disproportionality & causality → corroborate with evidence → export ICSR (E2B / CIOMS).

It merges complementary strengths from three open-source / hackathon PV systems into one FastAPI + React app that runs offline-first (zero keys required; optional keys unlock richer live sources and cloud LLM).

| Reference | Link |
|-----------|------|
| **Algo-Pharma** | https://github.com/Ankur2606/Algo-Pharma |
| **pan-IITian (SignalRx / AyuScout)** | https://github.com/anshumanarchit-crypto/pan-IITian · also https://github.com/Arpit248-3/Pan-IIT |
| **PulseAI** | https://github.com/Pratik-Hack/PulseAI *(private; features taken from project README)* |

---

## 2. Quick start

1. Backend: `cd backend` → `.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001`
2. Frontend: `cd frontend` → `npm run dev` → http://localhost:5173
3. Sign in: `admin@vigilai.dev` / `admin123`
4. Prefer the **existing database** for presentations (do **not** Reset mid-demo).
5. Open ⌘K / Ctrl+K for quick navigation.

Sidebar pages: Overview · Safety Signals · Signal Lifecycle · SMQ · Class Effects · Vaccine · Geo Clusters · Federated/DP · Knowledge Graph · KPIs · Alerts · Live Feed · **Command Center** · Data Forge · Forum Onboarding · Surveillance Net · Sources.

Top bar: multi-select **Sources** dropdown → Fetch selected · Load demo corpus · Stream tick · Reset · Sign out.

---

## 3. Feature map by GitHub source

| Origin | Role in VigilAI |
|--------|-----------------|
| **Algo-Pharma** | NLP truth path: PII, translation, NER, **4-gate AE**, explainability, agentic crawl / forum onboard, thread confidence |
| **pan-IITian / SignalRx** | Product surface: WHO-UMC, openFDA evidence, E2B, Forge synthetic data, JWT auth, self-healing crawler UX, sentiment ≠ severity |
| **PulseAI** | Polyglot connectors (HN, YouTube…), trust/sybil, ⌘K, CIOMS, Copilot, audit chain, AE-yield stats, federation/DP story |
| **VigilAI original** | Devices (MAUDE/MHRA/EUDAMED), life-science RSS pack, Bayesian disproportionality, SMQ/class/vaccine/spatial, GVP lifecycle, Gemini fallback, presentation polish |

---

## 4. A — Algo-Pharma lineage

**Source:** https://github.com/Ankur2606/Algo-Pharma

| Feature in VigilAI | How Algo had it | Where in VigilAI | How to use |
|--------------------|-----------------|------------------|------------|
| **4-gate AE detector** | Drug · symptom · sentiment · negation gates with trace | `backend/app/nlp/ae_detector.py` · Signal Detail | Open any **Safety Signal** → scroll to supporting posts → per-post gate trace |
| **PII scrubbing** | Multi-layer PII (regex + clinical NER) | `nlp/pii.py` + optional Presidio | Automatic on ingest; badges show scrubbed PII types on posts |
| **Cross-lingual path** | Indic → English (Sarvam) | `nlp/translation.py`, `vernacular.py` | Automatic; translated posts show “translated from …” |
| **Transformer / biomedical NER** | OpenMed models | `nlp/transformer_ner.py` (`d4data/biomedical-ner-all`) + lexicon fallback | Always on if health footer shows `NER: transformer` |
| **Agentic forum onboarding** | Firecrawl + LLM selector generation | `/onboarding` · `agentic/forum_onboarding.py` | Sign in → Forum Onboarding → paste URL → **Propose config** or **Analyze + ingest samples** |
| **MCP-lite crawl dispatch** | Groq MCP chat → slot-fill → crawl | `/command` · `agentic/chat_dispatch.py` | Command Center → e.g. `crawl google news about ozempic side effects` → Dispatch |
| **Thread / cohort RAG scoring** | Multi-turn thread confidence Red/Amber/Green | `analytics/thread_score.py` on Signal Detail | Open signal → **Thread / cohort corroboration** card |
| **Relational risk mapping** | Drug–symptom density clusters | Knowledge Graph + Class Effects / SMQ | **Knowledge Graph** / **Class Effects** / **SMQ Syndromes** |

**Not ported as-is (intentional):** Celery/Redis workers, Groq/Nemotron MCP JSON-RPC, OpenMed branded model weights. VigilAI uses an in-process scheduler + Ollama/Gemini and a public biomedical NER model.

---

## 5. B — pan-IITian / SignalRx lineage

**Source:** https://github.com/anshumanarchit-crypto/pan-IITian · https://github.com/Arpit248-3/Pan-IIT

| Feature in VigilAI | How SignalRx had it | Where in VigilAI | How to use |
|--------------------|---------------------|------------------|------------|
| **WHO-UMC causality** | Doctor node scoring | `analytics/causality.py` · badges on Signals / Detail | Safety Signals table + Signal Detail WHO-UMC badge |
| **Sentiment ≠ severity** | Explicit decoupling | Separate AE sentiment vs clinical severity fields | Signal Detail: sentiment on posts · severity badge on signal |
| **openFDA / FAERS corroboration** | FDA service enrichment | `evidence/fda.py`, FAERS live ingest | Signal Detail evidence panel · Sources → FAERS |
| **E2B (R3 / R2) export** | One-click ICSR XML | `evidence/e2b.py` · Signal Detail download | Open signal → Download E2B R3 / R2 |
| **PII before LLM** | PII vault | Scrub-in-place (no vault store) | Automatic; see scrubbed badges |
| **Data Forge** | Agentic synthetic generator + judges | `/forge` · `forge/engine.py` | Sign in → Data Forge → pick drug/condition → Generate |
| **Self-healing crawler** | Vision/selector heal UI | `scheduler.py` retry / quarantine / fallback | Live Feed → Start monitoring → watch 🟢🟡🔴 health chips |
| **JWT auth + roles** | Login / admin | `/login` · `auth.py` | Sign in; analyst role needed for Forge / Onboarding / Command |
| **Alerts feed** | Alerts page | `/alerts` | Alerts → Acknowledge · **Notify** (webhook or simulated) |
| **Trend / spike narrative** | Trend Analysis page | `analytics/trend.py` · spike badges | Signals with spike · Overview trends · Signal Detail trend series |

**Not ported as-is:** Chroma vector store, LangGraph named nodes, Help Center, multi-project wizard, SMTP email. Equivalents: SQL + evidence enrichment, modular pipeline, in-app alerts + optional webhook.

---

## 6. C — PulseAI lineage

**Source:** https://github.com/Pratik-Hack/PulseAI *(private; mapped from README)*

| Feature in VigilAI | PulseAI idea | Where in VigilAI | How to use |
|--------------------|--------------|------------------|------------|
| **Polyglot connector swarm** | Reddit, X, RSS, HN, YouTube, FAERS, PubMed + forums | Sources page · DemoBar · Live Feed modes | Sources dropdown → select → Fetch · or Live Feed mode |
| **HackerNews connector** | Algolia, no key | `crawl_hackernews` | Sources / DemoBar → HackerNews |
| **YouTube videos + comments** | YT Data API comments | `crawl_youtube` (titles, descriptions, tags, comments) | Needs `YOUTUBE_API_KEY` · Sources → YouTube |
| **Live-try → offline fallback** | Fixture fallbacks | Evidence offline knowledge · empty-key graceful degrade | Works without keys; evidence still shows offline stubs |
| **Self-heal swarm** | Retry / quarantine | Same as SignalRx row above | Live Feed chips |
| **PV Copilot** | Structured assessment | `POST /api/signals/{id}/copilot` | Signal Detail → Draft assessment |
| **CIOMS Form I** | 6-section draft | `evidence/cioms.py` · HTML download | Signal Detail → Download CIOMS |
| **Trust / Sybil score** | Cohort authenticity | `analytics/trust.py` | Badges on Signals / Signal Detail |
| **⌘K command palette** | Quick nav | Header / Ctrl+K | Press Ctrl+K → type page name |
| **Per-source AE yield** | Yield bars | `GET /api/sources/stats` · Sources page | Sources → AE rate bars per source |
| **Ed25519 audit chain** | Cryptographic trail | `analytics/audit.py` · Command Center panel · Verify on signal | Signal Detail → Verify chain · Command Center audit panel |
| **Federated / DP** | Privacy story | `/federated` | Federated / DP page |
| **Spike detection** | Real-time spike | EWMA / z-score | Spike badges · Alerts |

---

## 7. D — VigilAI original (beyond the three)

These are **not** simple ports — built to go beyond the refs for a worldwide, presentation-grade PV platform.

> **Full explanations** (what each term means, why it exists, where to click):  
> [`VIGILAI_ORIGINAL_FEATURES.md`](./VIGILAI_ORIGINAL_FEATURES.md)

| Feature | Why it matters | How to use |
|---------|----------------|------------|
| **Life-science news RSS pack** | ScienceDaily, STAT, Nature Medicine, WHO, FiercePharma, Endpoints, GEN, NPR, Medical Xpress | Sources → Life-science news · Live Feed mode |
| **Device vigilance** | MHRA FSNs, FDA MAUDE live, EUDAMED enrichment | Sources → MHRA / MAUDE · device signals · EUDAMED on detail |
| **Bayesian disproportionality** | EBGM / EB05, IC / IC025 + PRR/ROR/χ² + SDR | Signal Detail stats · SDR filter on Signals |
| **SMQ syndromes** | MedDRA-style syndrome roll-ups | **SMQ Syndromes** page |
| **Class effects + ATC / read-across** | Class-level PV | **Class Effects** page |
| **Vaccine AESI / Brighton / SCRI** | Vaccine-specific PV | **Vaccine Safety** page |
| **Spatial clusters (Kulldorff-style)** | Geo hotspots | **Geo Clusters** page |
| **GVP Module IX lifecycle** | Kanban signal governance | **Signal Lifecycle** page |
| **Label gap / boxed warnings / PGx / mechanism** | Clinical overlays | Cards on Signal Detail |
| **MaxSPRT / HR-survival / calibration / benefit–risk / completeness** | Advanced analytics | Signal Detail badges & cards |
| **Gemini LLM fallback** | Cloud when Ollama offline | Set `GEMINI_API_KEY` · restart backend · auto chain Ollama→Gemini→OpenRouter→deterministic |
| **FHIR R4 paste ingest** | EHR AdverseEvent bundles | Sources page FHIR panel |
| **Surveillance Net registry** | Live connectors + honest surrogates | **Surveillance Net** page |
| **Outbound alert notify** | Ops webhook (or simulated) | Alerts → Notify |
| **Demo multi-fetch / Select fast** | One recompute after batch; skip slow sources by default | Top bar Sources → Select fast → Fetch |

---

## 8. Page-by-page how to use

### Overview `/`
KPIs: posts, AE rate, signals, alerts, countries, languages. Sentiment / region / SOC charts.  
**Use for:** opening frame — “worldwide listening already running.”

### Safety Signals `/signals`
Filter by product type (drug/device), SDR-only, strength, search drug/symptom. Sort by EB05 / PRR / post count.  
**Use for:** pick a hero (e.g. isotretinoin → depression) → open detail.

### Signal Detail `/signals/:id`
Centerpiece: 4-gate posts · disproportionality · WHO-UMC · spike · trust · **thread RAG** · evidence (FAERS/MAUDE/DailyMed/PubMed/recalls/EUDAMED) · Copilot · E2B · CIOMS · Verify audit chain · review / lifecycle controls.

### Signal Lifecycle `/lifecycle`
GVP-style Kanban (new → under monitoring → …). Move statuses; set owner/notes.

### SMQ / Class Effects / Vaccine / Geo / Federated / Graph / KPIs
Each is one job: syndromes, ATC class roll-up, vaccine AESI, geo clusters, DP simulation, drug–symptom graph, SPC/KPI ops metrics.

### Alerts `/alerts`
Auto-generated for severity / spike / strong disproportion. **Acknowledge** · **Notify** (pushes to `ALERT_WEBHOOK_URL` or logs simulated delivery).

### Live Feed `/feed`
Choose source mode → Start live monitoring (server-side self-heal). Bootstrap pack resets + Google News + life-science (demo only — avoid mid-presentation Reset).

### Command Center `/command` *(Algo pitch)*
Natural language → slots (source + query) → crawl + ingest. Example:  
`fetch hackernews drug safety` · `crawl youtube about vaccine side effects`.  
Right panel: global Ed25519 audit chain status.

### Data Forge `/forge` *(SignalRx pitch)*
Generate synthetic patient posts with quality judges (Ollama/Gemini/deterministic). Export JSONL/CSV. Does **not** auto-write into live signal vault unless you separately ingest.

### Forum Onboarding `/onboarding` *(Algo + SignalRx)*
Paste forum URL → propose CSS selectors (Firecrawl if keyed, else heuristic) → optionally **ingest scrubbed samples**.

### Surveillance Net `/surveillance`
Catalogue of live vs surrogate PV data sources (honest labelling).

### Sources `/sources`
Registry of all connectors with status · per-source crawl buttons · AE-yield bars.

---

## 9. Data sources registry

| Source ID | Origin lineage | Key? | Notes |
|-----------|----------------|------|-------|
| `google_news` | PulseAI / VigilAI | No | 5 curated PV RSS queries |
| `life_science` | VigilAI original | No | 9 journalistic/pharma RSS outlets |
| `hackernews` | PulseAI | No | Algolia API |
| `youtube` | PulseAI (+ VigilAI video metadata) | Yes `YOUTUBE_API_KEY` | Titles, descriptions, tags + comments |
| `faers_live` | SignalRx / PulseAI | No | openFDA serious ICSRs |
| `pubmed_live` | PulseAI / VigilAI | No | NCBI E-utilities |
| `dailymed_rss` | VigilAI | No | New/revised labels |
| `fda_*` / `fda_rss` | SignalRx / VigilAI | No | MedWatch / recalls / press via news + openFDA |
| `mhra_devices` | VigilAI | No | UK Atom FSNs |
| `maude_live` | VigilAI / Pulse-style | No | Device MDRs |
| `eudamed` | VigilAI | No | Lookup enrichment (not bulk crawl) |
| `reddit` / `reddit_health` | Algo-Pharma | No | Direct RSS (often blocked on corp nets) |
| `reddit_pullpush` | VigilAI workaround | No | **Slowest crawl (~80s+)** — avoid live on stage |
| `twitter` | Algo / PulseAI | Yes `TWITTERAPI_IO_KEY` | |
| `forum` | Algo / SignalRx / PulseAI | Optional Firecrawl | Via Onboarding |
| `fhir` | VigilAI | No | Paste bundle |
| Synthetic / stream | All three demos | No | Offline corpus |

---

## 10. Optional API keys

Edit only: `backend/.env` (**not** `.env.example`). Restart backend after changes.

| Variable | Enables |
|----------|---------|
| `YOUTUBE_API_KEY` | YouTube videos + comments |
| `GEMINI_API_KEY` | LLM when Ollama is down (Forge, narratives, Copilot) |
| `TWITTERAPI_IO_KEY` | X/Twitter crawl |
| `FIRECRAWL_API_KEY` | Richer forum scrape |
| `ALERT_WEBHOOK_URL` | Live Slack/Teams push on Notify |
| `OPENROUTER_API_KEY` | Third LLM fallback |

**LLM chain:** Ollama (local) → Gemini → OpenRouter → deterministic templates.  
Health footer / `/api/health` shows active backend and whether Gemini is configured.

---

## 11. Demo tips & slow sources

**Crawl latency (fetch only, measured):**

1. Reddit Pullpush ~**84s** ← slowest  
2. HackerNews ~25s  
3. FDA RSS pack ~20s  
4. Life-science ~18s  
5. YouTube ~14s  

UI Fetch also runs corpus `recompute_signals` (can add **30–120s** on a large DB).

**Presentation-safe path:**
1. Keep existing ~1.3k posts / ~110 signals  
2. Login → Overview → Sources (show YouTube / Gemini live)  
3. Command Center one crawl **or** Google News + FAERS  
4. Hero Signal Detail (gates, stats, RAG, trust, evidence, E2B/CIOMS)  
5. Device or Vaccine + Geo  
6. Alerts Notify · Lifecycle · Forge (optional)  

**Do not:** Reset mid-demo · run Pullpush live · wait on cold evidence without opening the hero signal once first.

---

## Attribution summary (one slide)

> VigilAI unifies **Algo-Pharma’s** explainable 4-gate NLP & agentic onboarding, **SignalRx’s** WHO-UMC + openFDA + E2B + Forge + self-heal UX, and **PulseAI’s** polyglot connectors, trust defence, Copilot/CIOMS, and cryptographic audit story — then extends them with worldwide device vigilance, Bayesian signal detection, SMQ/class/vaccine/spatial analytics, and offline-first operation.

---

*Document version aligned with VigilAI codebase as of the presentation build. Sibling guides: `DEMO_SCRIPT.md`, `PRESENTER_GUIDE.md`, `FEATURE_USAGE_GUIDE.md` (deeper page walkthroughs), `ARCHITECTURE.md`.*
