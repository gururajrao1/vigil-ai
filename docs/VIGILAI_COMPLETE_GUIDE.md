# VigilAI — Complete Guide (Merged)

> **Single ordered reference** merged from `README.md`, `ARCHITECTURE.md`, `FEATURES_BY_SOURCE.md`, `VIGILAI_ORIGINAL_FEATURES.md`, `FEATURE_USAGE_GUIDE.md`, `DEMO_SCRIPT.md`, and `PRESENTER_GUIDE.md`.  
> Use this as the primary handout; the separate docs remain for deep detail.  
>
> **UI:** http://localhost:5173 · **API:** http://127.0.0.1:8001 · **Login:** `admin@vigilai.dev` / `admin123`

---

## Table of contents

1. [What VigilAI is](#1-what-vigilai-is)
2. [Elevator pitch](#2-elevator-pitch)
3. [Credentials & roles](#3-credentials--roles)
4. [Quick start (local)](#4-quick-start-local)
5. [Architecture](#5-architecture)
6. [Feature origins (3 GitHubs + ours)](#6-feature-origins-3-githubs--ours)
7. [VigilAI original features (explained)](#7-vigilai-original-features-explained)
8. [Data sources](#8-data-sources)
9. [NLP pipeline](#9-nlp-pipeline)
10. [Signal detection methods](#10-signal-detection-methods)
11. [Medical device vigilance](#11-medical-device-vigilance)
12. [Self-healing crawler](#12-self-healing-crawler)
13. [Pages & features (map)](#13-pages--features-map)
14. [How to use each page](#14-how-to-use-each-page)
15. [Live demo script (~8–10 min)](#15-live-demo-script-810-min)
16. [Demo tips & slow sources](#16-demo-tips--slow-sources)
17. [Deploy (Docker · Railway · Vercel)](#17-deploy-docker--railway--vercel)
18. [Configuration & API keys](#18-configuration--api-keys)
19. [API reference (summary)](#19-api-reference-summary)
20. [Project structure](#20-project-structure)
21. [Limitations & disclaimers](#21-limitations--disclaimers)
22. [Source doc index](#22-source-doc-index)

---

## 1. What VigilAI is

**VigilAI** is a worldwide pharmacovigilance (PV) platform:

**Ingest** patient / news / regulatory chatter → **scrub PII** → **extract clinical entities** → **detect adverse events** → **compute disproportionality & causality** → **corroborate with evidence** → **export ICSR** (E2B / CIOMS).

It runs **offline-first** (zero required API keys). Optional keys unlock YouTube, Twitter, richer forum scrape, and cloud LLM (Gemini).

Built by synthesising three reference projects, then extending them:

| Reference | Link |
|-----------|------|
| **Algo-Pharma** | https://github.com/Ankur2606/Algo-Pharma |
| **pan-IITian / SignalRx** | https://github.com/anshumanarchit-crypto/pan-IITian |
| **PulseAI** | https://github.com/Pratik-Hack/PulseAI *(private; features from README)* |

---

## 2. Elevator pitch

> Pre-market trials are small and short — rare or late harms slip through. **VigilAI** listens to real patients and regulatory chatter worldwide, turns messy text into **explainable safety signals** for **drugs, vaccines, and devices**, runs regulator-shaped stats (PRR/ROR, EBGM, BCPNN), grades WHO-UMC causality, corroborates with openFDA / DailyMed / PubMed / MAUDE / EUDAMED, and exports **E2B + CIOMS** — offline-first, zero keys required.

**One-line problem:** Serious AEs surface in conversation long before many ICSRs; we need to listen, extract, and surface them with traceable evidence.

---

## 3. Credentials & roles

| Role | Email | Password | Can do |
|------|-------|----------|--------|
| **Admin** | `admin@vigilai.dev` | `admin123` | Everything (users, ingest, reset) |
| **Analyst** | `analyst@vigilai.dev` | `analyst123` | Analytics, review, lifecycle, Forge, Onboarding, Command |
| **Viewer** | `viewer@vigilai.dev` | `viewer123` | Read-only signals / analytics / exports |

Roles enforced in UI and JWT middleware.

---

## 4. Quick start (local)

### Prerequisites
- Python 3.11+ · Node.js 18+  
- Optional: [Ollama](https://ollama.ai) → `ollama pull llama3.2:3b`  
- Optional: `GEMINI_API_KEY` in `backend/.env` for cloud LLM fallback  

### Backend
```powershell
cd vigil-ai/backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# Prefer: .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

### Frontend
```powershell
cd vigil-ai/frontend
npm install
npm run dev
```

Open **http://localhost:5173**. Footer should show backend online. Prefer **existing DB** for presentations — do **not** Reset mid-demo.

### First demo actions (top bar)
1. **Demo corpus** (if empty) — seeds posts + signals; evidence pre-warms in background (~20–30s)  
2. **Sources** → Select fast / Google News + Life-science + FAERS → **Fetch**  
3. Open one hero signal once so FAERS/DailyMed/PubMed cache before the talk  

---

## 5. Architecture

### Pipeline (left → right)

1. **Sources** — news, social, FAERS, devices, FHIR, forums, synthetic stream  
2. **Ingest** — dedupe · PII scrub · language detect · translate → English  
3. **NLP** — lexicon + optional transformer NER · MedDRA/ATC/IMDRF · 4-gate AE  
4. **Analytics** — disproportionality · spike/trend · WHO-UMC · SMQ/class/vaccine/geo…  
5. **Evidence** — FAERS / MAUDE / DailyMed / PubMed / recalls / EUDAMED (lazy, cached)  
6. **Dashboard** — React UI · alerts · lifecycle · E2B/CIOMS exports  

### Stack

| Layer | Tech |
|-------|------|
| Frontend | React + Vite + Tailwind · Recharts · force-graph · 3D DNA |
| Backend | FastAPI · SQLAlchemy · Uvicorn |
| DB | SQLite (local) · PostgreSQL (prod / Railway) |
| NLP | VADER · biomedical NER · Presidio · deep-translator |
| LLM | Ollama → Gemini → OpenRouter → deterministic |
| Stats | SciPy (EBGM, BCPNN, spatial, Cox, MaxSPRT) |
| Deploy | Docker · Railway · Vercel |

### Where data lives
- **Local:** `backend/vigilai.db` (SQLite on your machine)  
- **Cloud:** Railway **Postgres** via `DATABASE_URL` — **not** on user phones  
- Users of a public link never hold your API keys; the **server** does  

---

## 6. Feature origins (3 GitHubs + ours)

| Origin | Role in VigilAI |
|--------|-----------------|
| **Algo-Pharma** | 4-gate AE, PII, translation, NER, forum onboard, Command chat, thread confidence |
| **SignalRx / pan-IITian** | WHO-UMC, openFDA evidence, E2B, Forge, JWT, self-heal UX, sentiment ≠ severity |
| **PulseAI** | Polyglot connectors (HN, YouTube…), trust/Sybil, ⌘K, CIOMS, Copilot, audit chain, AE yield, federation story |
| **VigilAI original** | Life-science RSS, devices, Bayesian/SMQ/class/vaccine/geo/GVP, clinical overlays, Gemini chain, FHIR, Surveillance Net, Notify, demo batching |

### Attribution (one slide)
> VigilAI unifies Algo-Pharma’s explainable NLP & agentic onboarding, SignalRx’s WHO-UMC + openFDA + E2B + Forge + self-heal, and PulseAI’s polyglot connectors, trust, Copilot/CIOMS, and audit story — then extends them with device vigilance, Bayesian detection, SMQ/class/vaccine/spatial analytics, and offline-first cloud-ready LLM fallback.

**Intentional skips:** Celery, LangGraph, Chroma vault, Help Center, multi-project wizard, SMTP.

---

## 7. VigilAI original features (explained)

Features **beyond** simple ports. Each block: meaning → used for → where.

### 7.1 Life-science news RSS pack
Nine feeds (ScienceDaily, STAT, Nature Medicine, WHO, NPR Health, Medical Xpress, Fierce Pharma, Endpoints, GEN). Editorial/agency headlines — not forums.  
**Use:** demo without Reddit; news context next to social.  
**Find:** Sources dropdown · Data Sources · Live Feed · `POST /api/ingest/life-science`

### 7.2 Device vigilance (MHRA · MAUDE · EUDAMED)
UK FSNs, US device MDRs, EU registry enrichment. Same pipeline, `product_type=device`.  
**Find:** Sources → MHRA / MAUDE · filter device on Signals · EUDAMED on detail

### 7.3 Bayesian disproportionality (EBGM/EB05 · IC/IC025 · SDR)
Shrinkage & information-component metrics + **SDR** flag for triage (not only raw counts).  
**Find:** Signals sort/filter · Signal Detail stats strip

### 7.4 SMQ syndromes
MedDRA-*style* syndrome roll-ups (related PTs).  
**Find:** `/smq` · Signals syndrome filter  
**Limit:** not licensed MedDRA SMQ content

### 7.5 Class effects / ATC / read-across
Class-level PV: molecule vs class effect.  
**Find:** `/class-effects` · Signal Detail analogs

### 7.6 Vaccine AESI / Brighton / SCRI
AESI watchlist; Brighton certainty *surrogate*; SCRI risk-interval *surrogate*.  
**Find:** `/vaccine`

### 7.7 Geo clusters (Kulldorff-style)
Reports concentrate in a region beyond expectation → geographic hypothesis.  
**Find:** `/spatial` · geo badge on signals

### 7.8 GVP Module IX–style lifecycle
Kanban: detect → assess → monitor → close with owner/notes.  
**Find:** `/lifecycle` · Signal Detail lifecycle controls

### 7.9 Clinical overlays
Label gap · boxed warning · PGx · mechanism on Signal Detail.

### 7.10 Advanced stats suite
MaxSPRT · HR/survival · calibration · benefit–risk · completeness (research illustrations).  
**Find:** Signal Detail badges/cards

### 7.11 Gemini LLM fallback
`Ollama → Gemini → OpenRouter → templates`. Cloud LLM when laptop Ollama is off.  
**Find:** `/api/health` · set `GEMINI_API_KEY` in `backend/.env`

### 7.12 FHIR R4 paste ingest
Paste EHR AdverseEvent bundles → same PV pipeline.  
**Find:** `/sources` FHIR panel · `POST /api/ingest/fhir`

### 7.13 Surveillance Net
Honest **live vs surrogate** source catalogue.  
**Find:** `/surveillance`

### 7.14 Outbound alert Notify
Webhook (`ALERT_WEBHOOK_URL`) or simulated ops handoff.  
**Find:** `/alerts` → Notify

### 7.15 Demo multi-fetch / Select fast
One corpus recompute after batch; **Select fast** skips Reddit/YouTube/Twitter by default (avoids 15+ min hangs).  
**Find:** Top bar Sources → Fetch · `POST /api/recompute`

---

## 8. Data sources

### Social & news

| Source | Key? | Notes |
|--------|------|-------|
| Google News (5 PV queries) | No | Works on corp networks |
| Life-science pack | No | 9 outlets |
| HackerNews | No | Algolia |
| YouTube videos + comments | `YOUTUBE_API_KEY` | Titles/descriptions/tags + comments |
| Reddit Pullpush (29 subs) | No | **Slowest (~80s+)** — avoid on stage |
| Reddit direct / health | No | Often blocked on corp nets |
| X / Twitter | `TWITTERAPI_IO_KEY` | |
| Forums (any URL) | Firecrawl optional | Via Onboarding |
| Synthetic stream | No | Demo only |

### Regulatory — drugs
FAERS live · DailyMed RSS · PubMed · FDA RSS / recalls · openFDA corroboration on detail

### Regulatory — devices
MHRA FSNs · MAUDE live · EUDAMED lookup

### Clinical
FHIR R4 paste · Forum onboard

### 29 health subreddits (Pullpush / reddit_health)
AskDocs, medical, medicine, nursing, pharmacy, Health, AdverseEffects, mentalhealth, depression, anxiety, ADHD, bipolar, epilepsy, diabetes, thyroid, MultipleSclerosis, CrohnsDisease, rheumatoid, psoriasis, Fibromyalgia, ChronicPain, cancer, breastcancer, vaccines, CovidVaccinated, birthcontrol, Pregnancy, SkincareAddiction, accutane

---

## 9. NLP pipeline

```
Raw text (any language)
  → PII scrub (Presidio / regex)
  → Language detect + translate → English
  → Entities (transformer NER + lexicon)
       Drug: RxNorm/ATC · MedDRA PT/SOC
       Device: GMDN · IMDRF failure modes
  → 4-gate AE: drug/device · symptom/failure · negative sentiment · not negated
  → Signal recompute (corpus disproportionality)
```

**Coverage:** 200+ drugs · 150+ AE PTs · conditions for causality · 14 device types · 15 IMDRF failure modes

---

## 10. Signal detection methods

| Method | Meaning | Typical interest rule |
|--------|---------|----------------------|
| **PRR** | Proportional Reporting Ratio | ≥ 2, N ≥ 3 |
| **ROR** | Reporting Odds Ratio | 95% CI lower > 1 |
| **χ²** | Yates-corrected | ≥ 4 |
| **EB05** | MGPS Empirical Bayes lower bound | ≥ 2 |
| **IC025** | BCPNN IC lower bound | > 0 |
| **SDR** | Disproportionate reporting flag | Triage filter |
| **MaxSPRT** | Sequential boundary | Continuous monitoring |
| **HR** | Time-to-event surrogate | Onset narrative |
| **EWMA spike** | Z-score vs baseline | Spike badges / alerts |
| **Kulldorff scan** | Geo clustering | Geo Clusters page |
| **SCRI / Brighton** | Vaccine designs | Vaccine page |
| **PGx / class / calibration** | Modifiers & QA | Signal Detail |

Also: WHO-UMC causality · completeness · benefit–risk · trust/Sybil · thread RAG score · Ed25519 audit chain

---

## 11. Medical device vigilance

Same signal engine as drugs, plus:

- **Entity:** 14 device types + brand synonyms  
- **IMDRF failure codes** (malfunction, battery, overinfusion, …)  
- **Detail:** GMDN · FDA class I/II/III · EUDAMED UDI/CE · MAUDE evidence (not FAERS)  
- **Sources:** MHRA · MAUDE live · EUDAMED enrichment  

---

## 12. Self-healing crawler

1. Retry with exponential back-off  
2. Quarantine after repeated failures  
3. Fallback chains (e.g. Twitter → Pullpush → Google News → Synthetic)  
4. Live Feed chips: 🟢 healthy · 🟡 failing · 🔴 quarantined · `⚡ self-heal`  

Worker is **server-side** — keeps running if the browser tab closes.

---

## 13. Pages & features (map)

| Route | Page | One job |
|-------|------|---------|
| `/` | Overview | KPIs, charts, worldwide snapshot |
| `/signals` | Safety Signals | Triage queue, filters, SDR |
| `/signals/:id` | Signal Detail | Full analytics + evidence + exports |
| `/lifecycle` | Signal Lifecycle | GVP Kanban governance |
| `/smq` | SMQ Syndromes | Syndrome roll-ups |
| `/class-effects` | Class Effects | ATC / read-across |
| `/vaccine` | Vaccine Safety | AESI / Brighton / SCRI |
| `/spatial` | Geo Clusters | Hotspots |
| `/graph` | Knowledge Graph | Drug–symptom network |
| `/kpis` | KPIs & SPC | Ops metrics / control charts |
| `/alerts` | Alerts | Ack + Notify |
| `/feed` | Live Feed | Continuous monitor + health chips |
| `/sources` | Data Sources | Crawl buttons · FHIR · AE yield |
| `/command` | Command Center | NL → crawl dispatch + audit |
| `/onboarding` | Forum Onboarding | Paste URL → selectors (+ samples) |
| `/surveillance` | Surveillance Net | Live vs surrogate honesty |
| `/forge` | Data Forge | Synthetic AE corpus + judges |
| `/federated` | Federated / DP | Privacy simulation |
| `/login` | Login | JWT |

**Global:** Ctrl+K / ⌘K command palette · top **Sources / Fetch / Demo corpus / Reset** · health footer (LLM / NER)

---

## 14. How to use each page

Condensed from the full usage guide. For step-by-step clicks see `docs/FEATURE_USAGE_GUIDE.md`.

### Overview `/`
Land here first. Stat cards (posts, AE rate, signals, alerts, countries, languages) + charts. Pitch: “worldwide listening already running.”

### Safety Signals `/signals`
Filter product type / SDR / strength / region / SMQ; sort EB05 or PRR. Pick a **hero** (e.g. isotretinoin → depression) → open detail.

### Signal Detail `/signals/:id`
Show in order: 4-gate posts → PRR/ROR/EB05/IC025 → WHO-UMC → spike/trust/thread RAG → clinical overlays → evidence → Copilot → **E2B / CIOMS** → Verify audit. For devices: GMDN / IMDRF / MAUDE / EUDAMED.

### Lifecycle `/lifecycle`
Move a signal across Kanban; set owner/notes. Story: “detection isn’t closure.”

### SMQ / Class / Vaccine / Geo / Graph / KPIs / Federated
One page = one story. Don’t tour all unless judges ask — pick 1–2 extras after the hero signal.

### Alerts `/alerts`
Auto-created on severity/spike/SDR. **Acknowledge** · **Notify** (webhook or simulated).

### Live Feed `/feed`
Pick mode → Start monitoring. Show 🟢🟡🔴 chips. Avoid Reset from bootstrap mid-talk.

### Sources `/sources`
Show connector badges + AE-yield bars; crawl one source; optional FHIR paste.

### Command Center `/command`
Example: `crawl google news about ozempic side effects` → Dispatch. Show audit chain panel.

### Forge `/forge`
Generate synthetic posts with quality scores; export JSONL/CSV (does not auto-inject into vault unless you ingest separately). Needs analyst login.

### Forum Onboarding `/onboarding`
Paste forum URL → Propose config → optional **Analyze + ingest samples**.

### Surveillance Net `/surveillance`
Honesty slide inside the product (live vs surrogate).

---

## 15. Live demo script (~8–10 min)

**Before:** Keep existing DB. Optional: Fetch Google News + Life-science + FAERS once. Open hero signal once for evidence cache.

| Time | Step | What to do |
|------|------|------------|
| 20s | Framing | Patient voice before ICSRs; drugs+devices; offline-first |
| 40s | Overview | KPIs, regions, languages |
| 45s | Sources | Live badges; Fetch default three **or** Command one-liner |
| 30s | Command | NL crawl + audit panel *(Algo beat)* |
| 90s | Hero signal | Gates · stats · RAG · trust · evidence · E2B/CIOMS · Copilot |
| 45s | Extras | Device **or** Vaccine **or** Geo + SMQ/Class (quick) |
| 40s | Ops | KPIs · Alerts Notify · Lifecycle · (Forge optional) |
| 20s | Onboard | Optional forum URL |
| 15s | Close | Voice → grounded signal → ICSR export |

**If Wi-Fi dies:** stay offline — lexicon path, stats, exports, Forge deterministic still work. Skip live crawls.

**YouTube IP note:** If 0 posts + IP restriction, add your **IPv6** to the Google key allowlist (or relax app restriction; keep YouTube Data API only).

---

## 16. Demo tips & slow sources

**Crawl latency (fetch only, approx.):**
1. Reddit Pullpush ~**84s** ← avoid live on stage  
2. HackerNews ~25s  
3. FDA RSS ~20s  
4. Life-science ~18s  
5. YouTube ~14s  

Corpus **recompute** after ingest can add 30–120s on a large DB — DemoBar now does **one** recompute at end of batch.

**Do:** Select fast / default three · keep seeded DB · pre-open hero signal  
**Don’t:** Reset mid-demo · Select all slow sources · wait cold on uncached evidence  

---

## 17. Deploy (Docker · Railway · Vercel)

### Local Docker
```powershell
cd vigil-ai
docker-compose up --build
```
Frontend http://localhost:5173 · Backend http://localhost:8000

### Cloud (recommended easy path)

**Railway (backend + Postgres):**
1. Deploy GitHub → Root = `backend`  
2. Add PostgreSQL (`DATABASE_URL` automatic)  
3. Set secrets: `JWT_SECRET`, `GEMINI_API_KEY`, optional YouTube/Twitter…  
4. Lean flags: `USE_TRANSFORMER_NER=false`, `USE_PRESIDIO=false`  
5. No Ollama on cloud — rely on Gemini  

**Vercel (frontend):**
1. Root = `frontend`  
2. `VITE_API_BASE=https://your-railway-url.railway.app`  
3. Share the Vercel URL — users use **your** server keys & **your** Postgres  

**Others:** Render (API+DB), Fly.io, Cloud Run — more work. AWS possible but heavier. Laptop+ngrok is not a real deploy.

**Shared DB caveat:** One public deploy = one shared corpus; Restrict **Reset** to admins in real share scenarios.

---

## 18. Configuration & API keys

Edit **`backend/.env`** only (not `.env.example`). Restart uvicorn after changes.

| Variable | Enables |
|----------|---------|
| `YOUTUBE_API_KEY` | YouTube videos + comments |
| `GEMINI_API_KEY` | Cloud LLM when Ollama down |
| `OPENROUTER_API_KEY` | Third LLM fallback |
| `TWITTERAPI_IO_KEY` | X crawl |
| `FIRECRAWL_API_KEY` | Richer forum scrape |
| `ALERT_WEBHOOK_URL` | Live Notify destination |
| `OPENFDA_API_KEY` / `NCBI_API_KEY` | Higher rate limits |
| `DATABASE_URL` | SQLite default · Postgres for prod |
| `JWT_SECRET` | Change in production |

**Feature flags:** `USE_TRANSFORMER_NER`, `USE_PRESIDIO`, `USE_RXNORM`, `USE_ONLINE_TRANSLATION`, `USE_LLM`

**LLM chain:** Ollama → Gemini → OpenRouter → deterministic templates

---

## 19. API reference (summary)

Prefix: `/api/`

**Ingest:**  
`/ingest/seed` · `google-news` · `life-science` · `hackernews` · `youtube` · `fda-rss` · `faers-live` · `dailymed-rss` · `pubmed-live` · `reddit` · `reddit-health` · `reddit-pullpush` · `twitter` · `fhir` · `mhra-devices` · `maude-live`  
Batch helper: `POST /recompute` · many ingest routes accept `recompute=true|false`

**Devices:** `GET /device/eudamed?device=`

**Stream:** `/stream/tick` · `/stream/start` · `/stream/stop` · `/stream/status`

**Signals:** `GET /signals` · `GET /signals/:id` · narrative · copilot · e2b · e2b-r2 · cioms

**Analytics:** `/smq` · `/class-effect` · `/vaccine` · `/spatial` · `/knowledge-graph` · `/kpis` · `/surveillance/sources` · …

Interactive docs when backend is up: `http://127.0.0.1:8001/docs`

---

## 20. Project structure

```
vigil-ai/
├── docker-compose.yml
├── README.md
├── docs/
│   ├── VIGILAI_COMPLETE_GUIDE.md   ← this file
│   ├── VIGILAI_ORIGINAL_FEATURES.md
│   ├── FEATURES_BY_SOURCE.md
│   ├── FEATURE_USAGE_GUIDE.md      ← deepest page click-paths
│   ├── DEMO_SCRIPT.md
│   ├── PRESENTER_GUIDE.md
│   └── ARCHITECTURE.md
├── backend/   (FastAPI, analytics/, evidence/, ingestion/, nlp/, agentic/, forge/)
└── frontend/  (React pages, DemoBar, api.js)
```

---

## 21. Limitations & disclaimers

- Brighton / SCRI / SMQ / GMDN / calibration / HR are research **surrogates** where noted — not licensed clinical databases or adjudicated cases  
- EUDAMED is live public data but may lag  
- Federated/DP is a **simulation** over local partitions  
- MAUDE has reporting lag  
- Signal detection is for **research / hypothesis generation**, not a validated regulatory system of record  

---

## 22. Source doc index

| Doc | Best for |
|-----|----------|
| **This file** | One ordered brief for humans / judges |
| [`FEATURES_EXPLAINED.md`](./FEATURES_EXPLAINED.md) | **Every feature in plain language** (teach / presenter dictionary) |
| `README.md` | Repo landing + API tables |
| `ARCHITECTURE.md` | Design / brief alignment |
| `FEATURES_BY_SOURCE.md` | Provenance vs 3 GitHubs |
| `VIGILAI_ORIGINAL_FEATURES.md` | Deep “ours only” explanations |
| `FEATURE_USAGE_GUIDE.md` | Exhaustive click-by-click |
| `DEMO_SCRIPT.md` | Timed stage script |
| `PRESENTER_GUIDE.md` | Rehearsal narrative |

---

*Merged presentation-build guide for VigilAI. Prefer this file for reading; keep sibling docs for depth and provenance.*
