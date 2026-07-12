# VigilAI — Presenter Guide

> A rehearsable, page-by-page script grounded **strictly in the actual code**. Every
> claim below maps to a real route, API endpoint, or algorithm. Login when you need
> write features (Forge / Onboarding): **admin@vigilai.dev / admin123**.
> Backend `:8000`, frontend `http://localhost:5173`.

---

## 1. 30-second elevator pitch

> "Pre-market drug and device trials are small and short, so rare or late harms slip
> through — and over 30% of new therapeutics get a post-market safety action within a
> few years. **VigilAI** listens to real patients worldwide, in real time, and turns
> messy social posts into **explainable, regulator-shaped safety signals** — for both
> **drugs and medical devices**. It extracts clinical entities, detects adverse events
> with an auditable 4-gate rule, runs the same disproportionality math regulators use
> (PRR/ROR, EBGM, BCPNN), grades WHO-UMC causality, corroborates against live openFDA /
> DailyMed / PubMed / recall data, and exports a regulator-ready E2B ICSR — and it runs
> **fully offline with zero API keys**."

**One-sentence problem statement:** *Serious adverse drug/device reactions surface in
patient conversations long before they reach regulators — we need to ingest that
real-time worldwide chatter, extract the clinical signal, and surface emerging safety
issues with explainable, source-traceable evidence.*

---

## 2. The big idea / architecture in plain words

**The pipeline (left → right):**

1. **Sources** — Reddit public RSS (no key), a multi-region synthetic corpus, a
   simulated real-time stream, and optional Twitter/forum adapters.
2. **Ingest → PII → translate** — every post is **PII-scrubbed first** (regex for
   emails/phones/cards/SSN/Aadhaar/PAN + optional Presidio names/locations), then
   **language-detected and translated to English**, then re-scrubbed if translation
   changed the text. Deduped on ingest.
3. **NLP: entities + AE** — two-tier entity extraction (deterministic **lexicon** +
   optional **transformer biomedical NER**, `d4data/biomedical-ner-all`); drugs
   normalized to generic + **ATC** (RxNorm), symptoms to **MedDRA-style PT/SOC**; VADER
   sentiment; negation detection; then the **4-gate adverse-event detector**.
4. **Analytics (three parallel lenses):**
   - **Disproportionality** — PRR/ROR (+95% CI), Yates χ², plus Bayesian **EBGM/EB05**
     (MGPS) and **IC/IC025** (BCPNN), with an **SDR flag**.
   - **Trend / spike** — daily buckets, EWMA-smoothed baseline, **z-score spike** flag.
   - **WHO-UMC causality** — deterministic factor scoring → Certain/Probable/Possible/
     Unlikely/Unassessable + severity grade.
5. **Evidence corroboration** — openFDA **FAERS** (drugs) / **MAUDE** (devices),
   **DailyMed** label, **FDA recalls**, **PubMed** literature, **FDA device
   classification** — keyless, cached, offline-fallback, enriched lazily per signal.
6. **Dashboard** — React + Recharts + force-graph, JWT auth, E2B export, KPIs/SPC.

**Two brief-driven differentiators (neither source project had these):**
- **Drug–Symptom–Condition Knowledge Graph** (networkx, degree-centrality hubs).
- **Real-time streaming + trend/spike detection** (stream tick + EWMA/z-score).

**Agentic bits:**
- **Autonomous monitoring worker** — a server-side daemon that ingests + recomputes on
  an interval (real background surveillance).
- **Data Forge** — agentic synthetic-post generation with a *scenario → generate →
  judge → repair → score* loop (local Ollama, deterministic fallback).
- **Agentic forum onboarding** — point it at any forum URL; it proposes an extraction
  config (Firecrawl/LLM if configured, else HTML heuristics).

---

## 3. Global controls (top demo bar + ambient background)

The header has four buttons (`App.jsx` → `DemoBar`) plus a user menu:

| Control | What it calls | What happens | Timing to expect |
|---|---|---|---|
| **Load demo corpus** | `POST /api/ingest/seed?days=21` (demo=true) | Ingests ~260 worldwide posts (fast deterministic lexicon path), recomputes all signals, **back-dates** detection/alert timestamps + pre-reviews a few signals (so KPIs/SPC populate), and kicks off a **non-blocking pre-warm** of the top 12 signals' external evidence. | ~a few seconds to seed; evidence pre-warm continues in the background ~20–30s. |
| **▶ Stream batch** | `POST /api/stream/tick?n=4` | 4 brand-new posts timestamped "now" arrive, run NLP, and trigger a recompute — the live-arrival moment. | ~1–2s (warm openFDA cache). |
| **Crawl Reddit (live)** | `POST /api/ingest/reddit?query=drug side effect` | Pulls **real** Reddit posts via public RSS, runs full worldwide NLP, recomputes. **Needs internet.** | ~3–8s depending on Wi-Fi. |
| **Reset** | `POST /api/reset` | Clears posts, signals, alerts, audit log. | Instant. |

- **Login:** `admin@vigilai.dev / admin123` (seeded admin, role hierarchy admin >
  analyst > viewer; JWT with a stdlib fallback so auth works even without python-jose).
  Read pages are open; **Forge** and **Forum Onboarding** require a signed-in account.
- **Ambient DNA background:** a code-split 3D WebGL life-sciences backdrop
  (`Dna3DBackground`). It's automatically **disabled on the Knowledge Graph page** (that
  page runs its own WebGL force-graph) and shows a static veil instead.
- **Sidebar footer** shows live health: *Backend online*, whether the **LLM** is Ollama/
  offline, and whether NER is **transformer** or **lexicon**.

> **Say this:** "Everything on screen is driven by these four buttons — seed a
> worldwide corpus, stream a live batch, or crawl real Reddit — and it all works
> offline."

---

## 4. Page-by-page

The nav (`App.jsx`) has 10 pages, in this order.

---

### 4.1 Overview

- **Where:** nav **Overview** · route `/`.
- **What it shows:** six KPI stat cards (posts ingested, adverse events + AE rate,
  safety signals + strong count, active alerts, spikes detected, countries + languages),
  a second row (critical signals, translated posts, regions covered, MedDRA organ
  classes), then charts: **signal volume over time** (total vs AE area chart),
  **sentiment mix** (pie), **top implicated drugs** (bar), **signal strength
  distribution** (STRONG/MODERATE/WEAK), and a worldwide row — **geographic spread** (by
  region), **MedDRA System Organ Classes**, and **languages detected**.
- **How it works:** `GET /api/dashboard/stats` and `GET /api/trends/overview`
  (`helpers.py`). Stats are counted directly off the `raw_posts` / `processed_posts` /
  `signals` tables; the time series buckets posts by day into total / AE / negative-
  sentiment counts.
- **What the viewer gets:** instant scale + worldwide reach (UX / scalability). "Every
  number traces back to individual PII-scrubbed posts." Ties innovation to breadth.
- **Say this:** "This is worldwide social listening at a glance — volume, sentiment,
  geography, languages, and organ classes, all recomputed live as data arrives."
- **If asked:**
  - *Is this real data?* "The demo corpus is synthetic and reproducible so the stats are
    stable on stage; the same pipeline runs on live Reddit crawls."
  - *Where do organ classes come from?* "Our open **MedDRA-style** PT/SOC surrogate —
    MedDRA itself is licensed, so we ship a curated open drop-in."

---

### 4.2 Safety Signals

- **Where:** nav **Safety Signals** · route `/signals`.
- **What it shows:** a filterable, sortable table of drug/device → event signals.
  Columns: **Product → Event** (💊 drug / 🩺 device icon, ATC or GMDN/product-code, SOC,
  region, and an openFDA FAERS/MAUDE report line), **PRR**, **χ²**, **EB05**, **IC025**,
  **Reports**, **Strength**, **Causality** (WHO-UMC badge), **Severity**, **Trend**
  (spike z or trend arrow). Filters: strength tabs, product type, region, **sort by
  PRR / EB05 / IC025 / reports**, **SDR-only** and **Spiking-only** toggles. A pulsing
  red dot marks spiking signals; a red **SDR** badge marks disproportionate reporting.
- **How it works:** `GET /api/signals` (server filters by strength/region/spiking);
  product-type + SDR filtering and the Bayesian sort are applied client-side. Signals
  are produced by `recompute_signals` → `compute_signals` (`disproportionality.py`):
  builds a 2×2 table per (product, event), applies **Haldane-Anscombe +0.5**, computes
  **PRR + 95% CI**, **ROR + 95% CI**, **Yates χ²**, **EBGM/EB05** (Gamma-Poisson
  shrinkage, DuMouchel-style MGPS), **IC/IC025** (BCPNN, Norén variance), a strength
  tier, and the **SDR flag** (IC025>0, or EB05≥2, or PRR CI-lower≥1 with χ²≥4 and n≥3).
- **What the viewer gets:** regulator-grade rigor + noise control (accuracy /
  explainability). "EB05 and IC025 are exactly what FDA MGPS and UMC BCPNN use; Bayesian
  shrinkage stops a 2-report coincidence from masquerading as a strong signal."
- **Say this:** "Filter to devices, toggle SDR-only, sort by EB05 — this is a triage
  queue a real safety team would work top-down."
- **If asked:**
  - *Why sort by EB05 not PRR?* "PRR explodes on small counts; EB05/IC025 shrink small-N
    noise toward the null, so ranking by them surfaces the signals least fooled by
    sparse data."
  - *What's a 'report' here?* "A (product, event) co-occurrence inside an AE-flagged
    post — the disproportionality marginals are global, so stats are recomputed
    corpus-wide when new data arrives."

---

### 4.3 Signal Detail (the explainability drawer)

- **Where:** click any signal row → route `/signals/:id`.
- **What it shows:**
  - Header with product badge, strength, **SDR**, **WHO-UMC** causality, severity, spike
    z, SOC, and ATC (drugs) or **GMDN/product-code + IMDRF** (devices); **E2B R3** and
    **E2B R2** download buttons; and **Confirm / Dismiss** review buttons.
  - **AI signal narrative** (grounded in the computed stats; deterministic by default,
    **↻ Regenerate** tries the local LLM) + WHO-UMC factor chips.
  - **Disproportionality panel** — six metric cards: PRR (+95% CI), ROR (+95% CI), χ²,
    **EB05** (with EBGM in tooltip), **IC025** (with IC in tooltip), Reports (with
    expected count) + the plain-English SDR detection rule and WHO-UMC confidence %.
  - **Reporting trend** bar chart (daily supporting-report volume; bars turn red when
    spiking).
  - **External evidence** panel — openFDA FAERS/MAUDE report count + confidence boost;
    **FDA device classification** (product code + class + 21 CFR, devices only);
    **DailyMed** label link (drugs); **FDA recalls/enforcement** (count + class + date +
    reason); **PubMed** literature (article count + clickable top article).
  - **Source traceability** — every supporting post with entity highlighting, translated-
    from badge, **PII-scrubbed** badge, sentiment, AE confidence, original-language text,
    and the **4-gate AE decision trace** (drug present → symptom present → negative
    sentiment → non-negated symptom, each ✓/✕ with detail).
- **How it works:** `GET /api/signals/{id}` serializes the signal, computes the trend
  series, and joins supporting posts. External evidence beyond FAERS/MAUDE is enriched
  **lazily on first view** (`enrich_one`: ≤4 concurrent calls to DailyMed/recalls/PubMed/
  device-class, cached + persisted). WHO-UMC comes from `causality.py`; the gate trace
  from `ae_detector.py`; E2B XML from `e2b.py`.
- **What the viewer gets:** end-to-end **explainability + compliance** — the centerpiece.
  Every number has a source; every AE decision is auditable; the ICSR is one click away.
- **Say this:** "This drawer is the whole pitch: statistics, causality, trend, real
  multi-source evidence, per-post gate reasoning, and a regulator-ready E2B — all
  traceable."
- **If asked:**
  - *Is the narrative hallucinating?* "No — it's built from the signal's own statistics;
    the LLM path is constrained to those facts and always falls back to a deterministic
    template."
  - *Is the E2B a valid submission?* "It's a demo-grade E2B(R2/R3) template with real
    MedDRA PT/SOC, ATC, and WHO-UMC fields — structurally correct, not a validated
    production filing."

---

### 4.4 Knowledge Graph

- **Where:** nav **Knowledge Graph** · route `/graph`.
- **What it shows:** node/relationship counts, **hub entities by degree centrality**, and
  an interactive force-directed graph — drugs (blue), symptoms (red), conditions (amber);
  **edge color = severity, width = report count**; adverse edges emit directional
  particles.
- **How it works:** `GET /api/knowledge-graph` → `build_graph` (`knowledge_graph.py`)
  builds a **networkx** graph from detected signals (drug↔symptom adverse edges weighted
  by strength × report count) plus drug↔condition "indication" edges (co-occurrence ≥2),
  and computes **degree centrality** for the hub ranking.
- **What the viewer gets:** innovation — a systems view that reveals shared-symptom
  clusters and the most "connected" drugs/reactions at a glance.
- **Say this:** "This is one of the two features the brief specifically asked for — the
  drug–symptom–condition relationship graph, with hubs ranked by centrality."
- **If asked:** *What makes a hub?* "Degree centrality — the drugs or reactions
  participating in the most relationships."

---

### 4.5 KPIs & SPC

- **Where:** nav **KPIs & SPC** · route `/kpis`.
- **What it shows:** KPI cards — **time to detection** (mean/min/max, n), **actionable
  rate** (confirmed of reviewed), **false-positive ratio** (dismissed of reviewed),
  **SDR count** — a review funnel (confirmed/dismissed/unreviewed), a **Shewhart SPC
  control chart** of daily alert frequency (mean, **UCL/LCL at ±3σ**, out-of-control
  points), and an append-only **audit trail** table.
- **How it works:** `GET /api/kpis` + `GET /api/audit` (`kpis.py`). Time-to-detection =
  `detected_at − earliest_post_at`; actionable/FP ratios from HCP review states; SPC
  computes mean ± 3σ over daily alert counts. The demo seed back-dates detection/alert
  timestamps and pre-reviews a few signals so these are populated on stage.
- **What the viewer gets:** operations + compliance — "this is how a safety team runs and
  proves signal quality," with a tamper-evident audit trail.
- **Say this:** "Detection latency, actionability, false-positive rate, and a control
  chart — the operational metrics a real pharmacovigilance team is measured on."
- **If asked:** *Where do the timestamps come from?* "The demo back-dates detection and
  alert times across the corpus window so KPIs/SPC show a real distribution; live, they
  accrue as the background worker runs."

---

### 4.6 Alerts

- **Where:** nav **Alerts** · route `/alerts`.
- **What it shows:** a live alert list with severity dot (Critical pulses), the alert
  message (drug → event + reasons), timestamp, severity badge, and **Acknowledge**;
  clicking an alert opens its signal.
- **How it works:** `GET /api/alerts` / `POST /api/alerts/{id}/ack`. Alerts are emitted
  during recompute (`_maybe_alert`) when a signal is **Critical/High severity**, is
  **spiking**, is an **SDR**, or is **STRONG** disproportionality.
- **What the viewer gets:** the actionable "so what" — automatic escalation of the
  signals that matter (UX / operations).
- **Say this:** "Alerts fire automatically on severity, spikes, or disproportionality —
  click through straight to the evidence."
- **If asked:** *Can it notify externally?* "In-app today; the alert model is the hook a
  webhook/email integration would attach to."

---

### 4.7 Live Feed

- **Where:** nav **Live Feed** · route `/feed`.
- **What it shows:** the **Autonomous monitoring worker** control card (start/stop,
  interval, mode, tick count, last run, last ingested), a **Start/Stop live stream**
  button (ingests every 4s), an **adverse-events-only** filter, and a scrolling feed of
  posts with platform, timestamp, AE/no-AE + sentiment badges, and highlighted drug/
  symptom entities.
- **How it works:** the worker card calls `POST /api/scheduler/start|stop` +
  `GET /api/scheduler/status` (`scheduler.py` — a real daemon thread that ingests a
  stream/Reddit batch and recomputes on an interval, idempotent + offline-safe). The
  live-stream toggle repeatedly calls `POST /api/stream/tick`. Feed = `GET /api/posts`.
- **What the viewer gets:** innovation / architecture — genuine **continuous autonomous
  surveillance** independent of the browser tab, not just a manual button.
- **Say this:** "Start the worker and VigilAI monitors on its own, server-side —
  ingesting and recomputing signals continuously."
- **If asked:** *Is it a real queue/broker?* "It's an in-process daemon thread with
  start/stop/status — a true background worker without adding an external broker."

---

### 4.8 Data Forge

- **Where:** nav **Data Forge** · route `/forge` (**requires sign-in**).
- **What it shows:** a form (drug, condition, platform, region, records) and, after
  generating, summary cards (generated, export-ready, avg quality, engine = Ollama vs
  deterministic), **JSONL/CSV export**, and per-record cards with the post text, scenario
  (age/gender/emotion), a **repaired** badge, and per-axis scores (medical, realism,
  hallucination, PII).
- **How it works:** `POST /api/forge/generate` → `engine.py` runs *scenario → generate →
  judge → repair → re-score* per record. Judges are rule-based (medical validity, realism,
  a hallucination/meta-phrase check, and a **PII** check via the real scrubber); if
  quality is below threshold it attempts one repair. Uses local Ollama when available,
  deterministic templates otherwise.
- **What the viewer gets:** agentic AI + safety — generate realistic **fictional** patient
  posts for testing/training **without touching real PII**; the judge+repair loop is the
  agentic story.
- **Say this:** "An agentic generator with a judge-and-repair loop — synthetic patient
  data you can score and export, fully offline."
- **If asked:** *Does this pollute the live signals?* "No — Forge output is clearly
  fictional and is never written into the live signal store automatically."

---

### 4.9 Forum Onboarding

- **Where:** nav **Forum Onboarding** · route `/onboarding` (**requires sign-in**).
- **What it shows:** a URL input; after running, a **proposed extraction config** (method,
  forum type, post/title/date/content CSS selectors, estimated posts/page, confidence,
  optional LLM-refined flag) and **sample extracted posts** (already PII-scrubbed).
- **How it works:** `POST /api/agentic/onboard-forum` → `forum_onboarding.py`. Resolution
  order: Firecrawl (if key) → direct HTTP fetch + **HTML-heuristic** selector analysis
  (no key) → optional Ollama refinement → deterministic template if unreachable. Detects
  forum type (WordPress/Discourse/phpBB/Reddit/generic).
- **What the viewer gets:** agentic scalability — onboard *any* new patient forum without
  hand-writing a scraper, with a robust no-key fallback.
- **Say this:** "Point it at any patient forum and it figures out how to extract posts —
  agentic onboarding with a keyless fallback."
- **If asked:** *What if the page is JS-rendered?* "Then heuristics may find no samples —
  it honestly reports low confidence rather than inventing selectors."

---

### 4.10 Surveillance Net

- **Where:** nav **Surveillance Net** · route `/surveillance`.
- **What it shows:** counts (networks modeled, live connectors, connectors, surrogates),
  a **Live connectors** grid, a **Surrogate/reference networks** grid (each card labeled
  with region, modality, product, live/no-key/surrogate status + endpoint + honest note),
  and a **VigiLyze-style Explorer** — disproportionality drill-down (product/region/SOC
  filters + search, sorted by EB05) over VigilAI's **own** signal store.
- **How it works:** `GET /api/surveillance/sources` → `registry.py` (30 modeled networks).
  The Explorer reuses `GET /api/signals` client-side.
- **What the viewer gets:** honesty + architecture fidelity (compliance / explainability)
  — real where possible, clearly-labeled surrogate where data is licensed.
- **Say this:** "Nine live keyless connectors do real corroboration; the licensed global
  networks are modeled for architecture fidelity and clearly labeled as surrogates."
- **If asked:** *Why not query VigiBase directly?* "VigiBase/VigiLyze are licensed and not
  openly ingestible, so we emulate VigiLyze-style exploration over our own signals and say
  so plainly." (See §6.)

---

### 4.11 Sources

- **Where:** nav **Sources** · route `/sources`.
- **What it shows:** the worldwide **data-source** cards (Reddit global, Reddit health
  subreddits, X/Twitter [needs key], patient forums, openFDA FAERS) with live/optional
  status + key-required flag, and an **AI engine status** panel (LLM enabled, Ollama
  online/offline, model, OpenRouter configured).
- **How it works:** `GET /api/sources` (`ingestion/sources.py`) + `GET /api/llm/status`.
- **What the viewer gets:** transparency — exactly what's live, what's optional, and that
  nothing requires a key to run.
- **Say this:** "Every ingestion source runs keyless; keyed options degrade gracefully
  when not configured."
- **If asked:** *Is the LLM required?* "No — it's local Ollama when present, deterministic
  everywhere it's used otherwise."

---

## 5. The hero moments

### Drug hero — isotretinoin → depression
Filter Signals to **product = drug**, toggle **SDR-only**, sort by **EB05**, open
**isotretinoin → depression**. Walk the layers, all agreeing:
- **4-gate AE trace** — drug + symptom + negative sentiment + non-negated symptom, all ✓.
- **Disproportionality** — high PRR/ROR (CI lower bound above 1), χ², and Bayesian
  **EBGM/EB05 + IC/IC025** crossing thresholds → **SDR**.
- **Trend/spike** — reporting is spiking (the corpus seeds a deliberate late-window
  Accutane→depression burst with temporal + dechallenge + rechallenge language).
- **WHO-UMC** — the rechallenge/dechallenge cues + high-risk-drug prior push causality to
  **Probable/Certain**; depression is a critical event → **Critical severity**.
- **Evidence** — openFDA **FAERS** report count, **DailyMed** label match, **PubMed**
  article, and any **recall**.
- **Download E2B (R3/R2)** — a regulator-ready ICSR with MedDRA PT/SOC, ATC, and WHO-UMC.

> **Say this:** "Every independent layer — statistics, causality, trend, and real-world
> evidence — agrees on isotretinoin and depression, which is a genuine black-box warning.
> That convergence is the signal."

### Device hero — infusion pump → overinfusion (or insulin pump → malfunction)
Filter Signals to **product = device**, open **infusion pump → overinfusion**:
- Real **openFDA MAUDE** report count, **FDA device classification** (product code +
  Class II/III + 21 CFR), **IMDRF** failure-mode term, and any **device recall** — routed
  automatically by product type through the exact same pipeline.

> **Say this:** "Same pipeline, devices too — MAUDE experience reports, real FDA product
> code and class, and IMDRF failure coding."

---

## 6. Surveillance registry — how to talk about the 30 sources honestly

`registry.py` models **30 worldwide networks**, tagged by how VigilAI actually uses them:

- **~9 LIVE, keyless connectors** (queried live, cached, offline-fallback):
  FDA **FAERS** (`/drug/event`), FDA **MAUDE** (`/device/event`), FDA **drug labels**
  (`/drug/label`), **DailyMed** SPLs, FDA **drug recalls** + **device recalls**
  (`/enforcement`), FDA **device classification**, **PubMed** (NCBI E-utilities), and
  **RxNorm/RxNav**. (**WHO ICD-11** is a 10th connector but needs credentials, so it's
  "needs key" unless configured.)
- **~20 modeled surrogates** — licensed or distributed-infrastructure systems that
  **cannot be openly ingested**: WHO **VigiBase/VigiLyze** (+ WHO PIDM), FDA **Sentinel**,
  **NESTcc**, **FDA BEST**, **CDC VSD**, **CNODES**, **CAEFISS**, UK **MHRA Yellow Card**,
  Australia **ASPREN**, Japan **MID-NET**, **China ADR**, MedWatch, ISMP, MEDMARX, CEM,
  and specialty registries (antipsychotic pregnancy registry, C-VIPER, implant registries).

> **Say this honestly:** "Roughly nine connectors do **real** corroboration with no API
> key. The big licensed global networks like VigiBase aren't openly ingestible, so we
> **model** them for architecture fidelity and clearly label them as surrogates — and we
> emulate VigiLyze-style exploration over our own signal store rather than pretending to
> query VigiBase."

---

## 7. Suggested 5-minute demo flow

1. **Before you start:** click **Load demo corpus** once, wait for the seed (~a few
   seconds) + the background evidence pre-warm (~20–30s). Open the isotretinoin signal
   once to confirm evidence is cached.
2. **Overview** (40s) — scale, worldwide reach, "every number traces to a PII-scrubbed
   post."
3. **▶ Stream batch** (20s) — a live batch arrives and recomputes (real-time story).
4. **Safety Signals** (60s) — filter drug, SDR-only, sort by EB05.
5. **Signal Detail → isotretinoin → depression** (90s) — the hero walkthrough: 4-gate
   trace, disproportionality (EB05/IC025 + SDR), WHO-UMC, spike, external evidence,
   **download E2B**.
6. **Signals → device → infusion pump → overinfusion** (30s) — MAUDE + device class +
   IMDRF ("same pipeline, devices too").
7. **Knowledge Graph** (20s) — the relationship graph + hubs.
8. **KPIs & SPC + Surveillance Net** (40s) — operational metrics + honest source registry.
9. **(Optional) Data Forge** (20s) — agentic synthetic generation.
10. **Close** — "Statistical rigor + WHO-UMC causality + real multi-source evidence + full
    explainability + E2B — drugs and devices, worldwide, offline."

**If Wi-Fi fails:** VigilAI is **offline-first**. Transformer NER, Presidio PII,
PRR/ROR/χ²/EBGM/BCPNN, WHO-UMC, MedDRA/GMDN/IMDRF coding, the knowledge graph, E2B,
KPIs/SPC, and deterministic narratives **all still work**. External evidence falls back
to a deterministic offline knowledge base, and pre-warmed hero signals already have
cached values. LLM narratives/Forge use local Ollama, falling back to templates. **Just
avoid the "Crawl Reddit (live)" button when offline.** To reset between runs: **Reset**,
then **Load demo corpus** again.

---

## 17. Federated / Privacy-Preserving Analytics (`/federated`)

> **Navigation:** Federated / DP (🔐 in sidebar)

**What it shows:** A differential-privacy simulation modelling the scenario where
**K=3 hospital/country sites** (North America, Europe, Asia) each hold a local
partition of the corpus and want to share aggregated results **without exposing
individual posts**.

**Technical walkthrough:**
1. The corpus is partitioned by region into 3 federated sites.
2. Each site computes its local (drug, symptom) counts, then applies the **Laplace
   mechanism** (ε=1.0, sensitivity=1) to every count before "sharing" — a pure
   ε-differential-privacy release.
3. A central aggregator sums the noisy counts from all 3 sites.
4. A **federated PRR** is computed from the aggregated noisy counts (Haldane–Anscombe
   +0.5 correction), compared to the pooled non-DP estimate.
5. A **consistency flag** marks whether the federated and pooled estimates agree on
   signal direction (PRR > 1 vs ≤ 1).

**Privacy budget:** 3 releases × ε=1.0 = **total ε=3.0** under sequential composition.
Implemented in `app/analytics/dp.py` (Laplace + Gaussian mechanisms, budget tracker)
and `app/analytics/federated.py` (site simulation + aggregation) — **zero external DP
libraries**, pure numpy/math.

**Signal Detail** shows a 🔐 chip with `federated_prr` and `ε` when the signal has a
federated estimate; teal = consistent with pooled estimate, amber = diverges.

**API:** `GET /api/federated` returns simulation metadata, per-site post counts,
privacy budget consumed, and the top 20 signals by federated PRR with consistency
flags.

**Disclaimer (shown in UI):** "Federated simulation over local corpus partitions —
not a real multi-institution deployment."

---

## 8. Tech stack one-liner & known limitations

**Tech stack:** FastAPI + SQLAlchemy/SQLite backend; scipy (EBGM/BCPNN math), networkx
(graph), VADER (sentiment), feedparser (Reddit RSS), httpx (connectors); optional
transformers + torch (biomedical NER), Presidio + spaCy (PII), deep-translator +
langdetect (translation); JWT auth (python-jose + passlib, stdlib fallback); optional
local Ollama LLM. Frontend: React 19 + Vite + Recharts + react-force-graph-2d + Tailwind.

**Known limitations (be upfront):**
- **openFDA is US-only** (FAERS/MAUDE/labels/recalls/classification are US data).
- **MedDRA PT/SOC, GMDN/product-code, and IMDRF** coding are **open surrogates**, not the
  licensed terminologies.
- **E2B R2/R3 XML** is a **demo-grade template**, not a validated regulatory submission.
- **Surveillance surrogates** (VigiBase/VigiLyze, Sentinel, NESTcc, BEST, VSD, CNODES,
  Yellow Card, MID-NET, etc.) are **modeled, not ingested** — clearly labeled as such.
- **Evidence enrichment is lazy** (per signal on first view) to respect NCBI/openFDA rate
  limits; hero signals are pre-warmed for the demo.
- The default **demo corpus is synthetic** (reproducible) and detection/alert timestamps
  are back-dated to populate KPIs/SPC — this only touches timestamps + review state, never
  the disproportionality statistics or external evidence.
- Transformer NER / Presidio / translation / Ollama are **optional**; each degrades to a
  deterministic offline path, so results never regress below the lexicon baseline.
