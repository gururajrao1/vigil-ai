# VigilAI

> **Worldwide pharmacovigilance & device-vigilance platform**  
> Social listening → clinical NLP → explainable AE gates → regulator-shaped signal detection → workflow → export  
> **Offline-first · zero required API keys · drugs, vaccines, and devices**

**Live app:** https://vigil-ai-eight.vercel.app  
**API:** Railway (`/api` proxied from Vercel) · wake `/api/health` once after idle (~30–60s cold start)  
**Corpus (production Postgres):** ~1.3k unique posts across projects · default **General PV** workspace shows ~1.1k (project filter, not a smaller DB)

Deeper handouts: [`docs/VIGILAI_COMPLETE_GUIDE.md`](docs/VIGILAI_COMPLETE_GUIDE.md) · [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) · [`docs/DEPLOY_FREE.md`](docs/DEPLOY_FREE.md)

---

## Table of contents (slide map)

| # | Slide / section | Use in deck |
|---|-----------------|-------------|
| 1 | [One-liner & problem](#1-one-liner--the-problem) | Title + why we exist |
| 2 | [What VigilAI does](#2-what-vigilai-does) | Product scope |
| 3 | [Value props](#3-value-props-for-stakeholders) | Benefits |
| 4 | [Architecture](#4-architecture-at-a-glance) | System diagram |
| 5 | [End-to-end pipeline](#5-end-to-end-pipeline) | How data flows |
| 6 | [Repo map](#6-where-everything-lives-repo-map) | KT / onboarding |
| 7 | [UI navigation](#7-ui-navigation-hubs--tabs) | Product tour |
| 8 | [Feature catalog](#8-feature-catalog-what-each-thing-does) | Feature deep-dive |
| 9 | [Signal science](#9-signal-detection-science) | Stats / PV rigor |
| 10 | [NLP & 4-gate AE](#10-nlp--4-gate-ae-engine) | Explainability |
| 11 | [Data sources](#11-data-sources--network-registry) | Ingest honesty |
| 12 | [Workflow & alerts](#12-workflow--alerts) | Ops story |
| 13 | [How to run](#13-how-to-run) | Setup + live URLs |
| 14 | [Config & roles](#14-configuration--roles) | Auth / RBAC |
| 15 | [Disclaimers](#15-disclaimers) | Compliance |

---

## 1. One-liner & the problem

**One-liner**

> VigilAI listens to patient and regulatory chatter worldwide, turns unstructured text into **explainable drug / vaccine / device safety signals**, and manages them through a GVP-shaped workflow — offline-first.

**The problem (slide bullets)**

- Pre-market trials are small and short → rare / late harms slip through  
- Serious AEs often appear in **conversation** before structured ICSRs  
- Social / forum / news text is noisy, multilingual, and full of PII  
- Regulators expect **disproportionality**, **causality**, **audit**, **export** — not dashboards alone  

**The answer**

Ingest → scrub → extract → 4-gate AE → PRR/ROR/EBGM/BCPNN → WHO-UMC → corroborate (openFDA…) → Workflow → E2B/CIOMS

---

## 2. What VigilAI does

| Capability | In plain language |
|------------|-------------------|
| **Social + regulatory listening** | Reddit, news, FAERS, PubMed, labels, devices, optional YouTube/X |
| **Clinical NLP** | Drugs→generic/ATC, symptoms→MedDRA-style PT/SOC, devices→GMDN/IMDRF |
| **AE validation** | Explainable **4-gate** engine (drug · symptom · negative sentiment · non-negated) |
| **Signal detection** | PRR, ROR, Yates χ², EBGM/EB05, BCPNN IC025, SDR, spikes, MaxSPRT |
| **Analytic lenses** | SMQ, class effects, vaccine AESI, geo clusters, vs FAERS |
| **Evidence** | Knowledge graph, story mode, term glossary |
| **Ops** | Priority score, GVP-style lifecycle, alert inbox, KPIs / SPC |
| **Export** | ICH E2B R2/R3 (demo), CIOMS I (demo) |

**Product types:** drugs · vaccines · medical devices / combination products  

**Design rule:** every network / LLM / transformer path **degrades** to a deterministic offline fallback. No feature may hard-require a key.

---

## 3. Value props (for stakeholders)

| Audience | What to say |
|----------|-------------|
| **PV / safety scientist** | Traceable gates, disproportionality with CIs, WHO-UMC cues, MedDRA-style coding |
| **Device vigilance** | MAUDE + MHRA FSNs + GMDN/IMDRF failure coding |
| **Engineering / KT** | Modular FastAPI + React; clear repo map; offline-first |
| **Leadership / demo** | End-to-end story in ~10 minutes without paid APIs |
| **Compliance mindset** | Audit trail, lifecycle ownership, honest “surrogate” labels for licensed networks |

---

## 4. Architecture at a glance

```
┌──────────────────────────────────────────────────────────────┐
│  FRONTEND  React + Vite                                      │
│  Hubs (tabs) · ⌘K palette · project switcher · theme         │
└────────────────────────────┬─────────────────────────────────┘
                             │ REST  /api/*
┌────────────────────────────▼─────────────────────────────────┐
│  BACKEND  FastAPI + SQLAlchemy                               │
│  ingest → NLP → AE gates → recompute_signals → analytics     │
│  scheduler / stream worker · JWT roles · audit log           │
└────────────────────────────┬─────────────────────────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
         SQLite/Postgres   openFDA/etc.   Ollama/Gemini
         (local default)   (optional)     (optional LLM)
```

| Layer | Tech | Role |
|-------|------|------|
| UI | React 18, Vite, Tailwind | Hubs, charts, graph, workflow |
| API | FastAPI | Routes, auth, jobs |
| Persistence | SQLAlchemy · SQLite (dev) / Postgres (Docker) | Posts, signals, alerts, audit |
| NLP | Lexicons + optional transformer NER · VADER · negation windows | Entities + AE flag |
| Analytics | `app/analytics/*` | DMA, lifecycle, completeness, HR surrogate, MaxSPRT |
| Evidence | openFDA FAERS/MAUDE, DailyMed, PubMed, RxNorm | Corroboration |

---

## 5. End-to-end pipeline

```
Raw text (crawl / forge / FAERS / forum)
        │
        ▼
 PII scrub  →  translate (optional)  →  repair scrape artifacts
        │
        ▼
 Entity extract (drug / symptom / device / condition)
        │
        ▼
 Content-hash dedupe (cross-platform clones collapse)
        │
        ▼
 4-Gate AE engine  →  ae_flag + explainability.gate_1…4
        │
        ▼
 recompute_signals  →  2×2 PRR/ROR · EBGM · BCPNN · strength · SDR
        │
        ▼
 Causality · severity · priority · lenses · KG edges
        │
        ▼
 Alerts (spike / strong / high severity)  →  Workflow / Escalate
        │
        ▼
 Signal Detail · E2B / CIOMS export
```

**Invariant — 4-gate AE**

| Gate | Rule |
|------|------|
| 1 | ≥1 **unique** drug/device **concept** (brand+generic collapsed) |
| 2 | ≥1 symptom / event |
| 3 | Negative / adverse sentiment |
| 4 | ≥1 **non-negated** symptom (`no` / `not` / `without` / `denies`…) |

`ae_confidence = min(0.99, |sentiment| × 0.9 + 0.1)` when all gates pass.

---

## 6. Where everything lives (repo map)

```
vigil-ai/
├── README.md                 ← you are here (KT + GitHub)
├── docker-compose.yml        ← Postgres + backend + frontend (+ SearXNG)
├── backend/
│   ├── app/
│   │   ├── main.py           ← FastAPI app entry
│   │   ├── config.py         ← env / offline-first flags
│   │   ├── models.py         ← RawPost, ProcessedPost, Signal, Alert…
│   │   ├── pipeline.py       ← ingest + recompute_signals
│   │   ├── api/routes.py     ← REST surface
│   │   ├── nlp/              ← entities, ae_detector, negation, PII…
│   │   ├── analytics/        ← DMA, lifecycle, completeness, survival HR…
│   │   ├── ingestion/        ← crawlers + source registry adapters
│   │   ├── evidence/         ← openFDA corroboration + surveillance registry
│   │   ├── agentic/          ← Command Center chat → crawl dispatch
│   │   ├── projects/         ← workspaces, pathfinder, KG RDF, divergence
│   │   ├── forge/            ← synthetic data generator
│   │   ├── biotech_homepage/ ← public homepage layout schema
│   │   ├── rbac.py           ← admin / analyst / viewer write gates
│   │   └── scheduler.py      ← background / stream ticks
│   ├── tests/                ← disproportionality + AE detector suites
│   ├── scripts/              ← SQLite→Postgres merge (unique posts, no wipe)
│   └── .env.example
├── frontend/
│   └── src/
│       ├── App.jsx           ← shell, role-aware nav, demo bar, routes
│       ├── api.js            ← client (wake + auth retries)
│       ├── roles.js          ← role helpers for UI gates
│       ├── biotech/          ← public homepage (Login CTA · boot loader)
│       ├── pages/            ← hubs + UsersAdmin + feature pages
│       └── components/       ← UI primitives, story sidebar, etc.
└── docs/                     ← deep guides (see bottom)
```

### Backend modules → “what to open when…”

| If you need… | Open |
|--------------|------|
| AE gate logic | `backend/app/nlp/ae_detector.py` |
| Ingest bouncer | `backend/app/nlp/ingest_gateway.py` |
| Hybrid MedDRA match (RapidFuzz / SapBERT·BioBERT / cosine) | `backend/app/nlp/hybrid_resolver.py` |
| Stage-4 embedding cosine map | `backend/app/nlp/stage4_meddra_embed.py` |
| Open MedDRA-style PT/SOC thesaurus | `backend/app/nlp/meddra.py` |
| CUI / UMLS-style IDs | `backend/app/nlp/stage3_ner_cui.py` |
| Brand→generic / ATC | `backend/app/nlp/lexicons.py`, `drug_norm.py` |
| PRR / EBGM / SDR | `backend/app/analytics/disproportionality.py` |
| Lifecycle transitions | `backend/app/analytics/lifecycle.py` |
| Alert → workflow | `backend/app/analytics/alert_actions.py` |
| Slack/Teams notify | `backend/app/analytics/outbound.py` |
| Live vs surrogate networks | `backend/app/evidence/registry.py` |
| Crawl implementations | `backend/app/ingestion/sources.py` |
| KG / story | `backend/app/projects/rdf_graph.py`, `kg_story.py` |

---

## 7. UI navigation (hubs & tabs)

Sidebar is intentionally **small**. Related views are **tabs inside hubs**.

### Public

| Surface | Route | Purpose |
|---------|-------|---------|
| **Homepage** | `/` | Biotech marketing stage · single **Login** CTA (waits for API wake) |
| **Sign in / Register** | `/login` | Blank credential form · public register → **viewer** |

### Core (after login)

| Hub | Route | Tabs | Purpose |
|-----|-------|------|---------|
| **Dashboard** | `/dashboard` | Corpus metrics · Ops KPIs & SPC | Volume, AE rate, triage quality |
| **Safety Signals** | `/signals` | Detect · Workflow · Alert inbox | Find → manage → escalate |
| **Analytic Lenses** | `/lenses` | SMQ · Class · Vaccine · Geo · vs FAERS | Overlays on core DMA |
| **Evidence Explorer** | `/graph` | Drug↔AE graph · Compare story · Glossary | Relationships & narrative |

### Workspace

| Hub | Route | Who | Purpose |
|-----|-------|-----|---------|
| **Projects** | `/projects` | Analyst+ | Therapeutic workspaces (PV / oncology / vaccine…) |
| **Source Discovery** | `/source-queue` | Analyst+ | Pathfinder queue · Manual forum URL |
| **Data Sources** | `/sources` | All roles (read) | Catalog · Live stream · Network registry · Agent chat |
| **Data Forge** | `/forge` | Analyst+ | Synthetic (fictional) patient posts |
| **Users** | `/users` | **Admin only** | List / create accounts · change roles |

**Shortcuts:** `⌘K` / `Ctrl+K` command palette · header **Sources → Fetch** (analyst+) · **Reset** (admin only) · project dropdown scopes the workspace.

Legacy URLs (`/lifecycle`, `/alerts`, `/smq`, …) **redirect** into the hubs above.

---

## 8. Feature catalog (what each thing does)

### Dashboard

| Tab | Does | KT tip |
|-----|------|--------|
| **Corpus metrics** | Posts, AE rate, platforms, top drugs/events, charts | Click AE bars → deep-link into Signals |
| **Ops KPIs** | Review backlog, time-to-decision, completeness, SPC-style alert frequency | Show “ops quality,” not just science |

### Safety Signals

| Tab | Does | KT tip |
|-----|------|--------|
| **Detect** | Ranked drug→event table (PRR, EB05, IC025, SDR, filters, profiles) | Hero path for demos |
| **Workflow** | Kanban: Inbox → Looking into it → … → Done / Not a concern | Same states as Signal Detail |
| **Alert inbox** | Spike / strong / high-severity pings · Escalate / Investigate / False alarm | Escalate ≠ Workflow assign alone |

**Signal Detail** (click any row): gates, DMA, WHO-UMC, completeness (vigiGrade-style), HR surrogate, evidence, thread score, E2B/CIOMS, workflow panel.

### Analytic Lenses

| Lens | Question it answers |
|------|---------------------|
| **SMQ** | Do member PTs pool into a syndrome signal? |
| **Class effects** | Same event across an ATC class? |
| **Vaccine** | AESI / Brighton-style vaccine focus? |
| **Geo clusters** | Spatially concentrated beyond expected share? |
| **vs FAERS** | Social signal vs openFDA FAERS pattern? |

Lenses are **overlays** — they do not replace PRR/SDR.

### Evidence Explorer

| Tab | Does |
|-----|------|
| **Drug ↔ AE graph** | Filterable force graph + inspector + **Signal Story Mode** (isolate → contrast) |
| **Compare story** | Guided A-vs-B validation narrative for an event |
| **Term glossary** | Patient slang → MedDRA-style PT |

### Data Sources

| Tab | Does |
|-----|------|
| **Source catalog** | One-click crawls + AE-yield view |
| **Live stream** | Timed continuous ingest (runs server-side) |
| **Network registry** | Live connectors vs licensed **surrogates** + VigiLyze-style explorer on *our* signals |
| **Agent chat** | NL → crawl dispatch (login required) |

**Surrogates (VigiBase, Sentinel, NESTcc…)** = architecture honesty / roadmap slots — **not** open bulk ingest.

### Projects · Discovery · Forge

| Feature | Does |
|---------|------|
| **Projects** | Separate surveillance campaigns; header switcher scopes data |
| **Pathfinder** | Suggest communities for the active project |
| **Forum onboarding** | Paste URL → propose selectors → sample ingest |
| **Data Forge** | Synthetic realistic posts + quality scoring (analyst+) |

---

## 9. Signal detection science

| Method | Meaning (demo language) |
|--------|-------------------------|
| **PRR / ROR** | Reporting rate / odds vs rest of corpus (Haldane–Anscombe +0.5) |
| **χ² (Yates)** | Independence on 2×2; ≥4 supports signal |
| **EB05 (MGPS)** | Bayesian shrinkage 5% lower bound (≥2 ≈ signal) |
| **IC025 (BCPNN)** | Information component lower bound (>0 ≈ signal) |
| **SDR** | Signal of Disproportionate Reporting (composite flag) |
| **Strength** | STRONG / MODERATE / WEAK tiers |
| **Spike** | Daily z-score ≥ 2 vs history |
| **MaxSPRT** | Sequential boundary (type-I control over repeated looks) |
| **WHO-UMC** | Deterministic causality cues (temporal, de/rechallenge…) |
| **Priority 0–100** | Strength × severity × novelty × velocity × MaxSPRT… |

**Strength tiers (core):**

- **STRONG:** PRR ≥ 2, χ² ≥ 4, count ≥ 3  
- **MODERATE:** PRR ≥ 1.5, count ≥ 2  
- else **WEAK**

---

## 10. NLP & 4-gate AE engine

| Stage | Location | Behavior |
|-------|----------|----------|
| Sanitize / scrape repair | `nlp/stage1_sanitize.py` | Fix broken compounds for highlighting |
| Entities | `nlp/entities.py` | Lexicon + optional transformer NER |
| Drug concepts | `nlp/drug_norm.py` + Gate 1 dedupe | **Lyrica + Pregabalin = 1 concept** |
| Sentiment | `nlp/sentiment.py` | VADER + clinical nudge |
| Negation | `nlp/negation.py` | Sliding-window cues |
| AE decision | `nlp/ae_detector.py` | `explainability.gate_1…gate_4` |
| Content dedupe | `nlp/content_dedupe.py` | Same narrative across platforms → one row |
| Ingest bouncer | `nlp/ingest_gateway.py` | Pre-DB drop of verb/negated/unmapped spans |

**UI:** Signal Detail → supporting posts → gate ✓/✕ with counts & items.

**Tests:** `backend/tests/test_ae_detector.py`

### Normalization & MedDRA mapping — where each technique lives

Orchestrator: `backend/app/nlp/text_normalize.py` (4-stage pipeline).  
Heavy matching: **`backend/app/nlp/hybrid_resolver.py`** (3-pass hybrid).  
PT/SOC catalog (open MedDRA-style surrogate, **not licensed MedDRA/UMLS**): `backend/app/nlp/meddra.py`.

| Technique | File(s) | Role in VigilAI |
|-----------|---------|-----------------|
| **RapidFuzz** (token_sort / token_set / partial — Levenshtein-family edit ratios) | `nlp/hybrid_resolver.py` Pass 1 · also `nlp/condition_norm.py` | Morphological collapse onto catalog PT when combined score ≥ 85 |
| **Token Jaccard** (n-gram / set overlap) | `nlp/hybrid_resolver.py` Pass 1 | Order-invariant overlap; blended 50/50 with RapidFuzz edit score |
| **Levenshtein-style edit distance** | via RapidFuzz scorers above (fallback: `difflib.SequenceMatcher`) | Spelling / plural / token-order drift |
| **Jaro–Winkler** | *Not a separate scorer today* — same Pass 1 uses RapidFuzz token ratios (Levenshtein-based). Add `rapidfuzz.distance.JaroWinkler` only if you want JW explicitly | — |
| **SapBERT / BioBERT / MiniLM** dense embeddings | `nlp/hybrid_resolver.py` Pass 2 (`_SapBertFaissIndex`) · model preference: SapBERT → BioBERT-NLI → MiniLM | Zero-character-overlap synonyms (e.g. layman ↔ PT) |
| **Faiss ANN** (Inner Product) + numpy argmax fallback | `nlp/hybrid_resolver.py` Pass 2 | Fast nearest neighbor over vocabulary embeddings |
| **Cosine similarity ≥ 0.85** | `nlp/stage4_meddra_embed.py` (MiniLM or n-gram cosine) · Pass 2 vector threshold in `hybrid_resolver.py` | Layman → MedDRA-style PT semantic map |
| **spaCy / scispaCy contextual re-rank** | `nlp/hybrid_resolver.py` Pass 3 · also bouncer gates in `ingest_gateway.py` | Drop conversational verbs; keep clinical phenotypes |
| **UMLS / CUI-style IDs** (surrogate namespaces, not a live UMLS API) | `nlp/stage3_ner_cui.py` (`assign_cui`) · ICD-10-CM-inspired codes + RxNorm when available | Stable concept IDs on entities |
| **Open MedDRA-style thesaurus** (PT → SOC map) | `nlp/meddra.py` (`map_term`, `_PT_MAP`) | Regulator-shaped coding without redistributing licensed MedDRA |
| **Synonym / vernacular thesaurus** | `nlp/stage2_synonyms.py` · `nlp/vernacular.py` · seeds in `hybrid_resolver._SEMANTIC_SEEDS` | Brand/alias/slang → canonical surface before fuzzy/vector passes |
| **Brand → INN + ATC / RxNorm** | `nlp/lexicons.py` · `nlp/drug_norm.py` | Product normalization |
| **Event inflection collapse** | `nlp/event_collapse.py` | Near-duplicate PT folding |

**Pass summary (hybrid resolver)**

1. Morphological Jaccard + RapidFuzz edit → PT if score ≥ 85  
2. SapBERT/BioBERT/MiniLM + Faiss (cosine / IP ≥ 0.85) → PT for semantic matches  
3. spaCy POS / clinical-relevance filter → discard non-phenotypes  

Offline-first: every optional package (rapidfuzz, faiss, transformers, spacy) has a deterministic fallback. Diagnostics: `GET /api/nlp/resolver-status`.

---

## 11. Data sources & network registry

### Crawl connectors (examples)

| Source | Key? | Notes |
|--------|------|-------|
| Google News · life-science RSS · HN | No | Demo-safe |
| FAERS live · PubMed · DailyMed · FDA RSS | No | Regulatory / literature |
| MAUDE · MHRA devices | No | Device vigilance |
| Reddit Pullpush | No | Slow — avoid mid-demo |
| YouTube · X/Twitter | Optional keys | Enrichment |

### Network registry split

| Type | Meaning |
|------|---------|
| **Live connector** | VigilAI actually queries (FAERS, MAUDE, RxNorm…) |
| **Surrogate** | Licensed / distributed (VigiBase, Sentinel…) — modeled only |

**VigiLyze-style explorer** = disproportionality drill-down over **VigilAI’s own** signals (not UMC VigiBase).

---

## 12. Workflow & alerts

### Workflow (GVP Module IX under the hood)

Plain labels: **Inbox → Looking into it → Looks real → High priority → Written up → Done** · **Not a concern**

| Action | What happens |
|--------|----------------|
| Assign owner + notes on Signal Detail / board | **DB only** — owner, status, audit (no email by itself) |
| Alert **Escalate** | Webhook ping (`ALERT_WEBHOOK_URL`) **or simulated** + open Workflow + Ops confirm |
| Investigate / False alarm / Seen | Inbox actions wired to lifecycle + review state |

**Where to find it:** `/signals?tab=lifecycle` · Signal Detail “Workflow status” · `/signals?tab=alerts`

### Surrogate panels on Signal Detail (say the disclaimer)

| Panel | Real meaning |
|-------|--------------|
| **Hazard ratio** | Illustrative Cox-style timing on **posts**, not clinical HR |
| **vigiGrade-style completeness** | Documentation quality of text fields — **not** “association is true” |

---

## 13. How to run

### Live (production)

| Piece | URL |
|-------|-----|
| **App** | https://vigil-ai-eight.vercel.app |
| **Login** | https://vigil-ai-eight.vercel.app/login |
| **API health** | https://vigil-ai-eight.vercel.app/api/health (Vercel → Railway) |
| **API (direct)** | https://api-production-87a1.up.railway.app/api/health |

Frontend: Vercel · Backend: Railway (Postgres) · `frontend/vercel.json` rewrites `/api/*` to the Railway API.

**Same URLs after each deploy** — the production aliases do not change. Corpus lives on Railway Postgres (persistent). Homepage **Data integrity** section documents live vs surrogate sources (no “biotech honesty” label).

**Project switcher vs total posts**

| Workspace | What the dashboard shows |
|-----------|--------------------------|
| General Pharmacovigilance (default) | ~1.1k posts (scoped) |
| Oncology / Vaccine | Smaller area-specific counts |
| All workspaces combined | ~1.3k unique posts |

New crawls append into the same DB; content-hash / `external_id` dedupe skips true clones without wiping history. To merge a local `backend/vigilai.db` into Railway without truncate, use `backend/scripts/merge_sqlite_into_pg.py` with `DATABASE_PUBLIC_URL`.

After a large merge, run `POST /api/recompute` as analyst/admin (alerts are deleted before signals to satisfy FKs).

### Prerequisites (local)

- Python 3.11+ · Node.js 18+  
- Optional: [Ollama](https://ollama.ai) → `ollama pull llama3.2:3b`  
- Optional keys in `backend/.env` (see §15)

### Backend (local)

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

> Dev frontend proxies to **8010**. Docker Compose exposes backend on **8000**. Prefer **one** uvicorn process (SQLite locks if duplicated).

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

### Docker (full stack)

```powershell
docker-compose up --build
```

- UI http://localhost:5173 · API http://localhost:8000/docs

### Default users (seeded)

| Role | Email | Password |
|------|-------|----------|
| Admin | `admin@vigilai.dev` | `admin123` |
| Analyst | `analyst@vigilai.dev` | `analyst123` |
| Viewer | `viewer@vigilai.dev` | `viewer123` |

---

**Do not mid-demo:** Reset DB · Reddit Pullpush · wait on cold full recompute with openFDA for every source.

**Prefer:** existing corpus · Google News / FAERS / life-science · header Fetch with `recompute` once at the end.

---

## 14. Configuration & roles

### Optional env (`backend/.env`)

| Variable | Enables |
|----------|---------|
| `YOUTUBE_API_KEY` | YouTube videos + comments |
| `TWITTERAPI_IO_KEY` | X / Twitter |
| `GEMINI_API_KEY` | Cloud LLM if Ollama down |
| `FIRECRAWL_API_KEY` | Richer forum scrape |
| `TAVILY_API_KEY` / `EXA_API_KEY` | Pathfinder discovery (optional) |
| `ALERT_WEBHOOK_URL` | Live Slack/Teams on Escalate |
| `OPENROUTER_API_KEY` | Extra LLM fallback |
| `DATABASE_URL` | Postgres in prod (Railway / Docker); SQLite locally |

**LLM chain:** Ollama → Gemini → OpenRouter → deterministic templates.

### Roles (RBAC)

Hierarchy: **admin (3) > analyst (2) > viewer (1)**. Enforced in UI and on mutating API routes (`backend/app/rbac.py` + `require_role`).

| Capability | Viewer | Analyst | Admin |
|------------|:------:|:-------:|:-----:|
| Browse dashboard / signals / lenses / evidence | ✓ | ✓ | ✓ |
| Fetch sources · demo corpus · stream / recompute | ✗ | ✓ | ✓ |
| Projects · Source Discovery · Data Forge · agentic | ✗ | ✓ | ✓ |
| Signal review / alert actions | ✗ | ✓ | ✓ |
| **Users** page — list / create / change role | ✗ | ✗ | ✓ |
| **Reset** database | ✗ | ✗ | ✓ |

**How roles are assigned**

| Path | Role |
|------|------|
| Public **Register** on `/login` | Always **viewer** |
| First user in an empty DB | **admin** (bootstrap only) |
| Admin **Users** page (`/users`) | Choose viewer / analyst / admin on create or role dropdown |

Login form is blank (no demo-credential autofill). Homepage **Login** waits for API wake and clears any stale session so it is not a dashboard bypass.

---

## 15. Disclaimers

- Prototype / research UX — **not for clinical decision-making**  
- Synthetic Forge data is **fictional**  
- openFDA = **US FAERS / MAUDE** only  
- MedDRA coding = **open surrogate**, not a licensed MedDRA install  
- E2B / CIOMS = **demo templates**, not validated submission packages  
- HR panel = **social-listening surrogate**, not a clinical hazard ratio  
- Completeness = **documentation quality**, not causality  
- VigiBase / Sentinel / NESTcc = **surrogate cards**, not ingested warehouses  

---

## License / status

Prototype research platform. See disclaimers above before any external distribution or clinical claim.
