# VigilAI

> **Worldwide pharmacovigilance & device-vigilance platform**  
> Social listening → clinical NLP → explainable AE gates → regulator-shaped signal detection → workflow → export  
> **Offline-first · zero required API keys · drugs, vaccines, and devices**

**Live app:** https://vigil-ai-eight.vercel.app  
**API:** Render (`/api` proxied from Vercel) · wake `/api/health` once after idle (~30–60s cold start on free tier)  
**UI:** Clair PRP design system (`@clairlabs-ai/prp-ui`) · glass / gradient chrome · light/dark via `data-mode`  
**Corpus (production Postgres):** ~2.3k unique posts across projects · default **General PV** workspace shows ~1.1k (project filter, not a smaller DB)

Deeper handouts: **[`docs/VIGILAI_APPLICATION_HANDBOOK.md`](docs/VIGILAI_APPLICATION_HANDBOOK.md)** (full where/how/what/why + architecture diagrams + keyword packs) · [`docs/VIGILAI_COMPLETE_GUIDE.md`](docs/VIGILAI_COMPLETE_GUIDE.md) · [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) · [`docs/DEPLOY_FREE.md`](docs/DEPLOY_FREE.md)

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
| 15 | [Data honesty notes](#15-data-honesty-notes) | Provenance |

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

Ingest → scrub → extract → 4-gate AE → PRR/ROR/EBGM/BCPNN → remine / DDI / pregnancy overlays → WHO-UMC → corroborate (openFDA…) → Workflow → SAR / E2B / CIOMS

---

## 2. What VigilAI does

| Capability | In plain language |
|------------|-------------------|
| **Social + regulatory listening** | Reddit, news, FAERS, VAERS, PubMed / Europe PMC / Semantic Scholar / Cochrane, labels, devices, optional YouTube/X |
| **Clinical NLP** | Drugs→generic/ATC/RxNorm, symptoms→MedDRA-style PT/SOC, devices→GMDN/IMDRF · hybrid RapidFuzz + SapBERT/FAISS |
| **AE validation** | Explainable **4-gate** engine (drug · symptom · negative sentiment · non-negated) |
| **Signal detection** | PRR, ROR, Yates χ², EBGM/EB05, BCPNN IC025, SDR, spikes, MaxSPRT |
| **Omni-Search + OMOP SPA** | Brand→chemical gateway · Universe vs Subset · shared RxCUI clinical context · `GET /api/v1/signals/{rxcui}` |
| **Terminology hub** | Offline ontology engine (LLT→SOC, ATC/ChEBI, GMDN/EMDN) · Deep MCN (SapBERT + geo aliases) |
| **GVP Modules 1–4** | Label filter / Weber · WHO-UMC + Naranjo draft · triangulation · **Signal Register** |
| **Analytic lenses** | Predictive intel · Remine lab · Risk populations / REM · DDI · pregnancy · SMQ · class · vaccine · geo · vs FAERS |
| **Competition-bias remine** | Case-level unmasking of competitor products → recompute PRR/ROR/χ² (read-only; does **not** overwrite stored SDR) |
| **Governance frontiers** | Inspection readiness · COU / Credibility Index · PGx · PrOACT/BRAT · lot clustering · ATMP longitudinal |
| **Evidence** | Knowledge graph, story mode, term glossary, casefile trajectory, SAR / PBRER |
| **Ops** | Priority score, GVP-style lifecycle, alert inbox, KPIs / SPC · Clair UI shell |
| **ETL** | Streaming FAERS→OMOP · SIDER in-label baseline · Athena vocab seed · MCN F1 gate |
| **Export** | ICH E2B R2/R3 (demo), CIOMS I (demo), SAR PDF/Markdown, PBRER draft |

**Product types:** drugs · vaccines · medical devices / combination products  

**Design rule:** every network / LLM / transformer path **degrades** to a deterministic offline fallback. No feature may hard-require a key.

---

## 3. Value props (for stakeholders)

| Audience | What to say |
|----------|-------------|
| **PV / safety scientist** | Traceable gates, disproportionality with CIs, WHO-UMC cues, MedDRA-style coding, Register queue |
| **Device vigilance** | MAUDE + MHRA FSNs + GMDN/IMDRF failure coding |
| **Medical informatics** | OMOP CDM v5.4 staging · Omni-Search brand harmonisation · MCN dual map |
| **Engineering / KT** | Modular FastAPI + React; Clair design system; clear repo map; offline-first |
| **Leadership / demo** | End-to-end story in ~10 minutes without paid APIs |
| **Compliance mindset** | Audit trail, lifecycle ownership, honest “surrogate / local cache” labels for licensed networks |

---

## 4. Architecture at a glance

```
┌──────────────────────────────────────────────────────────────┐
│  FRONTEND  React + Vite + @clairlabs-ai/prp-ui               │
│  Hubs (tabs) · ⌘K palette · project switcher · data-mode     │
└────────────────────────────┬─────────────────────────────────┘
                             │ REST  /api/*
┌────────────────────────────▼─────────────────────────────────┐
│  BACKEND  FastAPI + SQLAlchemy                               │
│  ingest → NLP → AE gates → recompute_signals → analytics     │
│  OMOP staging · ETL · ontology / MCN · scheduler · JWT RBAC  │
└────────────────────────────┬─────────────────────────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
         SQLite/Postgres   openFDA/etc.   Ollama/Gemini
         (local default)   (optional)     (optional LLM)
```

| Layer | Tech | Role |
|-------|------|------|
| UI | React 19, Vite, Tailwind, Clair PRP UI | Hubs, charts, graph, workflow |
| API | FastAPI (`app/api/routes/*`) | Routes, auth, jobs, ETL, OMOP SPA |
| Persistence | SQLAlchemy · SQLite (dev) / Postgres (Neon) | Posts, signals, alerts, OMOP tables, audit |
| NLP | Lexicons + optional transformer NER · VADER · negation · SapBERT/FAISS MCN | Entities + AE flag |
| Analytics | `app/analytics/*` | DMA, remine, DDI, pregnancy, SAR, register, MaxSPRT |
| Ontology / search | `nlp/ontology_engine`, `search_engine`, `normalization` | Terminology identity + Omni-Search |
| Evidence | openFDA FAERS/MAUDE, DailyMed, PubMed, RxNorm | Corroboration |
| ETL | `app/etl_pipeline` | FAERS / SIDER / Athena → OMOP |

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
 Causality · severity · priority · lenses · KG edges · OMOP staging
        │
        ▼
 Alerts (spike / strong / high severity)  →  Workflow / Escalate / Register
        │
        ▼
 Signal Detail · E2B / CIOMS / SAR / PBRER export
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
│   │   ├── api/routes/       ← REST package (_core, signals, etl, …)
│   │   ├── nlp/              ← entities, ae_detector, hybrid_resolver, ontology_engine…
│   │   ├── analytics/        ← DMA, remine, DDI, pregnancy, SAR, register…
│   │   ├── search_engine/    ← Omni-Search brand→chemical + Universe/Subset
│   │   ├── etl_pipeline/     ← FAERS / SIDER / Athena → OMOP
│   │   ├── db/               ← OMOP CDM models + mapper
│   │   ├── ingestion/        ← crawlers + source registry adapters
│   │   ├── evidence/         ← openFDA corroboration + surveillance registry
│   │   ├── agentic/          ← Command Center chat → crawl dispatch
│   │   ├── projects/         ← workspaces, pathfinder, KG RDF, divergence
│   │   ├── forge/            ← synthetic data generator
│   │   ├── biotech_homepage/ ← public homepage layout schema
│   │   ├── rbac.py           ← admin / analyst / viewer write gates
│   │   └── scheduler.py      ← background / stream ticks
│   ├── tests/
│   ├── scripts/              ← SQLite→Postgres merge (unique posts, no wipe)
│   └── .env.example
├── frontend/
│   ├── clairlabs-ai-prp-ui-*.tgz  ← vendored Clair design system (Vercel builds)
│   └── src/
│       ├── App.jsx           ← shell, role-aware nav, demo bar, routes
│       ├── api.js            ← client (wake + auth retries)
│       ├── theme.jsx         ← data-mode light/dark
│       ├── biotech/          ← Clair-styled public homepage
│       ├── hubs/             ← ontology / governance / frontier panels
│       ├── modules/          ← Omni-Search, MCN, normalization UI
│       ├── pages/            ← hubs + feature pages
│       └── components/       ← ui.jsx wrappers over prp-ui + PV widgets
└── docs/                     ← handbook + deep guides
```

### Backend modules → “what to open when…”

| If you need… | Open |
|--------------|------|
| AE gate logic | `backend/app/nlp/ae_detector.py` |
| Ingest bouncer | `backend/app/nlp/ingest_gateway.py` |
| Hybrid MedDRA match (RapidFuzz / SapBERT · Faiss) | `backend/app/nlp/hybrid_resolver.py` |
| Ontology engine (PT/SOC · ATC · GMDN) | `backend/app/nlp/ontology_engine/` |
| Deep MCN + geo aliases | `backend/app/normalization/` · MCN routes |
| Omni-Search gateway | `backend/app/search_engine/` |
| OMOP CDM + SPA | `backend/app/db/omop_*.py` · `GET /api/v1/signals/{rxcui}` |
| FAERS/SIDER ETL | `backend/app/etl_pipeline/` |
| PRR / EBGM / SDR | `backend/app/analytics/disproportionality.py` |
| Competition-bias masking / remine | `backend/app/analytics/masking.py`, `corpus.py`, `remine_lab.py` |
| DDI · pregnancy · risk populations | `ddi.py`, `pregnancy.py`, `risk_strata.py` / REM ranking |
| Label filter · triangulation · register | `label_filter.py`, `triangulation.py`, GVP register routes |
| SAR / PBRER / casefile | `sar.py`, `reports/pbrer.py`, `casefile.py` |
| Lifecycle / alerts | `lifecycle.py`, `alert_actions.py` |
| Live vs surrogate networks | `backend/app/evidence/registry.py` |
| Crawl implementations | `backend/app/ingestion/sources.py` |
| KG / story | `backend/app/projects/rdf_graph.py`, `kg_story.py` |

---

## 7. UI navigation (hubs & tabs)

Sidebar is intentionally **small**. Related views are **tabs inside hubs**.

### Public

| Surface | Route | Purpose |
|---------|-------|---------|
| **Homepage** | `/` | Clair-styled biotech stage · gradient Login CTA (waits for API wake) |
| **Sign in / Register** | `/login` | Clair Card / Input form · public register → **viewer** |

### Core (after login)

| Hub | Route | Tabs | Purpose |
|-----|-------|------|---------|
| **Dashboard** | `/dashboard` | Corpus metrics · Ops KPIs · **Inspection & COU** | Volume, AE rate, triage · governance frontiers |
| **Safety Signals** | `/signals` | **Detect** (incl. Omni-Search) · **Register** · Workflow · Alert inbox | Find → track → manage → escalate |
| **Terminology** | `/terminology` | Ontology · MCN | Terminology identity + deep concept normalization |
| **Analytic Lenses** | `/lenses` | Predictive intel · Remine · Risk populations · DDI · Pregnancy · SMQ · Class · Vaccine · Geo · vs FAERS | Sensitivity + overlays on core DMA |
| **Evidence Explorer** | `/graph` | Drug↔AE graph · Compare story · Glossary | Relationships & narrative |

### Workspace

| Hub | Route | Who | Purpose |
|-----|-------|-----|---------|
| **Projects** | `/projects` | Analyst+ | Therapeutic workspaces (PV / oncology / vaccine…) |
| **Source Discovery** | `/source-queue` | Analyst+ | Pathfinder queue · Manual forum URL |
| **Data Sources** | `/sources` | All roles (read) | Catalog · Live stream · Network registry · Agent chat |
| **Data Forge** | `/forge` | Analyst+ | Synthetic (fictional) patient posts |
| **Users** | `/users` | **Admin only** | List / create accounts · change roles |

**Shortcuts:** `⌘K` / `Ctrl+K` command palette · header **Sources → Fetch** (analyst+) · **Reset** (admin only) · project dropdown scopes the workspace · theme Light/Dark (`data-mode`).

Legacy URLs (`/lifecycle`, `/alerts`, `/smq`, `/omni`, `/ontology`, `/mcn`, …) **redirect** into the hubs above.

---

## 8. Feature catalog (what each thing does)

### Dashboard

| Tab | Does | KT tip |
|-----|------|--------|
| **Corpus metrics** | Posts, AE rate, platforms, top drugs/events, charts | Click AE bars → deep-link into Signals |
| **Ops KPIs** | Review backlog, time-to-decision, completeness, SPC-style alert frequency | Show “ops quality,” not just science |
| **Inspection & COU** | Inspection readiness SLA · COU / Credibility Index · frontiers strip · sample PrOACT | Governance story for leadership demos |

### Safety Signals

| Tab | Does | KT tip |
|-----|------|--------|
| **Detect** | Ranked product→event table (PRR, EB05, IC025, SDR, filters, jump search, pagination) + **Omni-Search** brand→chemical / Universe vs Subset | Hero path for demos |
| **Register** | GVP Module IX tracking register (paginated) · label / triangulation columns · SAR/PBRER hooks | Operational queue |
| **Workflow** | Kanban: Inbox → Looking into it → … → Done / Not a concern | Same states as Signal Detail |
| **Alert inbox** | Spike / strong / high-severity pings · Escalate / Investigate / False alarm | Escalate ≠ Workflow assign alone |

**Signal Detail** (click any row): plain-English **briefing** + conclusions, gates, DMA, WHO-UMC + Naranjo draft, label filter / Weber, triangulation matrix, completeness (vigiGrade-style), Cox PH timing estimate, PGx / PrOACT / lot / ATMP when relevant, evidence, thread score, **competition-bias masking**, **casefile trajectory**, **SAR** PDF/MD + GVP preview, E2B/CIOMS, workflow panel.

### Terminology

| Tab | Does |
|-----|------|
| **Ontology** | MedDRA-style LLT→SOC tree · ATC/ChEBI/SMILES · GMDN/EMDN/SaMD · SOC roll-up disproportionality |
| **MCN** | SapBERT + FAISS UMLS-style link → MedDRA/SNOMED dual map · synonym cohort N · GeoNames city aliases for Omni retrieval |

### Analytic Lenses

| Lens | Question it answers |
|------|---------------------|
| **Predictive intel** | Feature matrix, 4-gate playground, OMOP staging peek, privacy hygiene, BioIE adapters |
| **Remine lab** | If we hide competitor products for this event, does the pair cross the signalling threshold? Screens **every** eligible pair — searchable, filterable, paged |
| **Risk populations / REM** | Which strata elevate risk (REM ranking + logistic segments)? |
| **DDI findings** | Which drug pairs co-mention the same AE more than chance — and which look clinically risky? |
| **Pregnancy** | Exposure + congenital / pregnancy-context events; fixture blend when the live cohort is thin |
| **SMQ** | Do member PTs pool into a syndrome signal? |
| **Class effects** | Same event across an ATC class? |
| **Vaccine** | AESI / Brighton-style vaccine focus? |
| **Geo clusters** | Spatially concentrated beyond expected share? |
| **vs FAERS** | Social signal vs openFDA FAERS pattern? |

Lenses are **overlays / sensitivity analyses** — they do **not** replace or overwrite stored PRR/SDR on the Detect table. Remine shows before→after in the lab / masking panel only.

**Reading a remine card.** Unmasking is applied at **case level** (whole reports mentioning a masker are dropped, as a spontaneous reporting system would), then the masking ratio is decomposed exactly:

```
MR = PRR_after / PRR_before = coreporting_term × comparator_term
```

The **comparator term** is the classical masking effect and is *shared by every product reporting that event*, so a raw PRR rise ranks nothing — it happens to almost every pair once the comparator arm shrinks. The **co-reporting term** is pair-specific and moves only when the target's own cases overlap the masker's. The actionable outcome is a **threshold crossing** (`unmasked`). Cards are tiered by evidence: `evaluable` (≥3 cases, Evans criterion), `provisional` (2), `exploratory` (1).

| Outcome | Meaning |
|---------|---------|
| `unmasked` | Crosses the signalling threshold after unmasking — escalate |
| `co_reported` | Target's own cases overlap the masker's — review for confounding |
| `vanished` | Pair disappears; association carried entirely by shared cases |
| `attenuated` | Drops below threshold / weakens |
| `amplified` | PRR up by the shared comparator factor only — no action |
| `stable` | Competition bias does not drive this pair |

**Demo seed:** Data Sources → **Load PV demo pack** (`POST /api/ingest/pv-demo`) loads VAERS + FAERS bulk samples so Remine / DDI / Pregnancy have peers and co-mentions.

### Evidence Explorer

| Tab | Does |
|-----|------|
| **Drug ↔ AE graph** | Filterable force graph + inspector + **Signal Story Mode** (isolate → contrast) |
| **Compare story** | Guided A-vs-B validation narrative for an event |
| **Term glossary** | Patient slang → MedDRA-style PT |

### Data Sources

| Tab | Does |
|-----|------|
| **Source catalog** | One-click crawls + AE-yield view (includes VAERS / FAERS bulk sample + **Load PV demo pack** + literature abstracts) |
| **Live stream** | Timed continuous ingest (runs server-side) |
| **Network registry** | Live connectors vs licensed **surrogates** + VigiLyze-style explorer on *our* signals |
| **Agent chat** | NL → crawl dispatch (login required) |

**Surrogates (VigiBase, Sentinel, NESTcc…)** = architecture honesty / roadmap slots — **not** open bulk ingest. Comparative registry math uses **local reference caches**.

### Projects · Discovery · Forge · ETL

| Feature | Does |
|---------|------|
| **Projects** | Separate surveillance campaigns; header switcher scopes data |
| **Pathfinder** | Suggest communities for the active project (skips known paywalls) |
| **Forum onboarding** | Paste URL → propose selectors → sample ingest |
| **Data Forge** | Synthetic realistic posts + quality scoring (analyst+) |
| **ETL sync** | `GET /api/etl/sync/*` · FAERS→OMOP · SIDER baselines · Athena vocab · FastMCP `trigger_dataset_sync` |

### UI system (Clair)

| Piece | Does |
|-------|------|
| `@clairlabs-ai/prp-ui` | Shared Button / Card / Badge / Tabs / Dialog / Select / AppHeader primitives |
| `components/ui.jsx` | Thin VigilAI wrappers (domain Badge tones, PaginationBar, Spinner) |
| Homepage | Clair AppHeader · gradient CTAs · glass cards · orb atmosphere |
| Theme | `data-mode` dark/light (SegmentedControl) · tokens bridged from `--cds-*` |

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
| **Competition-bias remine** | Mask peer products for the same event → recompute 2×2 (read-only; stored Detect row unchanged) |
| **REM ranking** | Subpopulation Risk Elevation Multiplier |
| **Label filter / Weber** | In-label vs novel vs boxed; launch/media noise gate |
| **Triangulation** | Social DMA × FAERS/MAUDE × OMOP staging |
| **WHO-UMC + Naranjo** | Deterministic causality draft |
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
| Ontology / MCN | `nlp/ontology_engine/`, normalization + search | Terminology identity + consumer-slang map |

**UI:** Signal Detail → supporting posts → gate ✓/✕ with counts & items.

**Tests:** `backend/tests/test_ae_detector.py`

### Normalization & MedDRA mapping — where each technique lives

Orchestrator: `backend/app/nlp/text_normalize.py` (4-stage pipeline).  
Heavy matching: **`backend/app/nlp/hybrid_resolver.py`** (3-pass hybrid).  
PT/SOC catalog (open MedDRA-style coding cache): `backend/app/nlp/meddra.py`.

| Technique | File(s) | Role in VigilAI |
|-----------|---------|-----------------|
| **RapidFuzz** (token_sort / token_set / partial — Levenshtein-family edit ratios) | `nlp/hybrid_resolver.py` Pass 1 · also `nlp/condition_norm.py` | Morphological collapse onto catalog PT when combined score ≥ 85 |
| **Token Jaccard** (n-gram / set overlap) | `nlp/hybrid_resolver.py` Pass 1 | Order-invariant overlap; blended 50/50 with RapidFuzz edit score |
| **Levenshtein-style edit distance** | via RapidFuzz scorers above (fallback: `difflib.SequenceMatcher`) | Spelling / plural / token-order drift |
| **Jaro–Winkler** | *Not a separate scorer today* — same Pass 1 uses RapidFuzz token ratios (Levenshtein-based). Add `rapidfuzz.distance.JaroWinkler` only if you want JW explicitly | — |
| **SapBERT / BioBERT / MiniLM** dense embeddings | `nlp/hybrid_resolver.py` Pass 2 (`_SapBertFaissIndex`) · model preference: SapBERT → BioBERT-NLI → MiniLM | Zero-character-overlap synonyms (e.g. layman ↔ PT) |
| **Faiss ANN** (Inner Product) + numpy argmax fallback | `nlp/hybrid_resolver.py` Pass 2 · MCN path | Fast nearest neighbor over vocabulary embeddings |
| **Cosine similarity ≥ 0.85** | `nlp/stage4_meddra_embed.py` (MiniLM or n-gram cosine) · Pass 2 vector threshold in `hybrid_resolver.py` | Layman → MedDRA-style PT semantic map |
| **spaCy / scispaCy contextual re-rank** | `nlp/hybrid_resolver.py` Pass 3 · also bouncer gates in `ingest_gateway.py` | Drop conversational verbs; keep clinical phenotypes |
| **UMLS / CUI-style IDs** (offline namespaces) | `nlp/stage3_ner_cui.py` (`assign_cui`) · ICD-10-CM-inspired codes + RxNorm when available | Stable concept IDs on entities |
| **Open MedDRA-style thesaurus** (PT → SOC map) | `nlp/meddra.py` (`map_term`, `_PT_MAP`) | Regulator-shaped coding without redistributing licensed MedDRA |
| **Synonym / vernacular thesaurus** | `nlp/stage2_synonyms.py` · `nlp/vernacular.py` · seeds in `hybrid_resolver._SEMANTIC_SEEDS` | Brand/alias/slang → canonical surface before fuzzy/vector passes |
| **Brand → INN + ATC / RxNorm** | `nlp/lexicons.py` · `nlp/drug_norm.py` · `search_engine/` | Product normalization + Omni-Search |
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
| FAERS live · PubMed · Europe PMC · Semantic Scholar · Cochrane | No | Regulatory / literature abstracts |
| DailyMed · FDA RSS | No | Labels / alerts |
| VAERS sample · FAERS bulk sample | No | Offline fixtures + optional openFDA download; use **Load PV demo pack** for Remine/DDI/Pregnancy demos |
| MAUDE · MHRA devices · device news / recalls | No | Device vigilance |
| Reddit Pullpush | No | Slow — avoid mid-demo |
| YouTube · X/Twitter | Optional keys | Enrichment |

### Network registry split

| Type | Meaning |
|------|---------|
| **Live connector** | VigilAI actually queries (FAERS, MAUDE, RxNorm…) |
| **Surrogate / local cache** | Licensed or distributed infra (VigiBase, Sentinel…) — modeled for architecture fidelity |

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

**Where to find it:** `/signals?tab=lifecycle` · `/signals?tab=register` · Signal Detail “Workflow status” · `/signals?tab=alerts`

### Timing & completeness panels on Signal Detail

| Panel | Meaning |
|-------|---------|
| **Cox PH timing** | Social-listening time-to-event estimate on **posts** (anchor = earliest mention) |
| **vigiGrade-style completeness** | Documentation quality of text fields — not “association is true” |

---

## 13. How to run

### Live (production)

| Piece | URL |
|-------|-----|
| **App** | https://vigil-ai-eight.vercel.app |
| **Login** | https://vigil-ai-eight.vercel.app/login |
| **API health** | https://vigil-ai-eight.vercel.app/api/health (Vercel → Render) |
| **API (direct)** | https://vigil-ai-api.onrender.com/api/health |

Frontend: Vercel · Backend: Render + Neon Postgres · `frontend/vercel.json` rewrites `/api/*` to the Render API.

**Ship both sides:** `git push origin main` (Render API) **and** `cd frontend && npx vercel --prod` (Git push alone often does **not** refresh the Vercel alias).

**Same URLs after each deploy** — the production aliases do not change. Corpus lives on **Neon Postgres** (persistent across Render free-tier sleep). Homepage **Data integrity** section documents live pipeline vs local reference caches.

**Project switcher vs total posts**

| Workspace | What the dashboard shows |
|-----------|--------------------------|
| General Pharmacovigilance (default) | ~1.1k posts (scoped) |
| Oncology / Vaccine | Smaller area-specific counts |
| All workspaces combined | ~2.3k unique posts |

New crawls append into the same DB; content-hash / `external_id` dedupe skips true clones without wiping history. To merge a local `backend/vigilai.db` into Neon without truncate, use `backend/scripts/merge_sqlite_into_pg.py` with `DATABASE_URL` set to Neon.

After a large merge, run `POST /api/recompute` as analyst/admin (alerts are deleted before signals to satisfy FKs).

### Prerequisites (local)

- Python 3.11+ · Node.js 18+  
- Optional: [Ollama](https://ollama.ai) → `ollama pull llama3.2:3b`  
- Optional keys in `backend/.env` (see §14)

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
| `DATABASE_URL` | Postgres in prod (Neon via Render); SQLite locally |

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

## 15. Data honesty notes

- Synthetic Forge data is **fictional** (stress-test corpus, not ICSRs)  
- openFDA = **US FAERS / MAUDE** only  
- MedDRA / UMLS / GMDN coding uses **open offline caches**, not licensed redistributions  
- E2B / CIOMS / PBRER = **demo-shaped templates** for structure walkthroughs  
- Cox PH panel = **social-listening timing estimate** on posts  
- Completeness = **documentation quality**, not causality proof  
- VigiBase / Sentinel / NESTcc appear as **surrogate / architecture cards** — not ingested warehouses  
- Comparative registry math uses **local reference caches**, not live pipes into closed networks  

Full how-to tables, empty-result teaching, and keyword packs: **[`docs/VIGILAI_APPLICATION_HANDBOOK.md`](docs/VIGILAI_APPLICATION_HANDBOOK.md)**

---

## License / status

VigilAI pharmacovigilance workbench — see §15 for source provenance before external distribution.
