# VigilAI — Architecture

> Combined **worldwide** pharmacovigilance platform harvesting the best of **Algo-Pharma**
> (statistical disproportionality + explainable AE gating + MCP/agentic ingestion) and
> **SignalRx/AyuScout** (WHO-UMC causality + openFDA evidence + ICH E2B export + synthetic
> Forge), plus two features the hackathon brief calls out that neither source project built:
> a **Drug–Symptom Knowledge Graph** and a **real-time streaming** layer with **trend/spike
> detection**. India is fully covered; global coverage is the default.

---

## 1. Alignment to the Hackathon Brief

| Brief requirement | VigilAI implementation |
|---|---|
| Ingest real-time data (streaming or batch) | Simulated real-time stream + Reddit RSS (no key) + multi-region batch seed |
| Extract clinical entities (drugs, symptoms, conditions) | Lexicon **+ transformer biomedical NER** (`d4data/biomedical-ner-all`); RxNorm/ATC drug normalization; MedDRA-style symptom coding |
| Identify adverse events + sentiment trends | 4-gate explainable AE detector + VADER sentiment; sentiment trend series |
| Detect emerging safety signals via analytics | PRR / ROR / χ² disproportionality **+** time-bucketed trend/spike (EWMA + z-score) |
| Explainable insights + source traceability + confidence | Per-post gate reasoning, per-signal reasoning trace + **LLM narrative**, WHO-UMC factors, source links |
| Knowledge Graph (drug–symptom relationships) | networkx graph: Drug ↔ Symptom ↔ Condition edges weighted by signal strength |
| Dashboard + alerts | React dashboard: Overview, Signals, Knowledge Graph, Alerts, Live Feed, Forge, Onboarding, Sources |
| Innovation / agentic AI | Agentic Forge (synthetic data w/ judge+repair loop); agentic forum onboarding; optional LLM (Ollama) narratives |
| Compliance | Worldwide PII scrubbing (Presidio + regex), WHO-UMC causality, MedDRA-style + ICD-11 coding, ICH E2B (R2/R3) XML, JWT auth + roles |

**Deliverables:** working prototype (full stack), architecture diagram (this doc + `architecture.svg`),
demo dashboard, 5–7 slide deck (`slides.html`).

**Design constraint:** runs fully **offline with zero API keys**. Transformer NER, Presidio,
online translation, RxNorm, ICD-11, Ollama LLM, Firecrawl, and Twitter are optional and each
degrades to a deterministic offline path.

---

## 2. High-Level Architecture

```
                         ┌─────────────────────────────────────────────┐
                         │            DATA SOURCES (worldwide)           │
                         │  Reddit RSS (no key) · multi-region seed ·    │
                         │  real-time stream · [opt] Twitter/Firecrawl   │
                         └───────────────────────┬───────────────────────┘
                                                 │
                         ┌───────────────────────▼───────────────────────┐
                         │            INGESTION LAYER (batch+stream)       │
                         │  dedupe · language detect + translate (any→en) │
                         │  · worldwide PII scrub · store                  │
                         └───────────────────────┬───────────────────────┘
                                                 │  RawPost (lang, region, country)
                         ┌───────────────────────▼───────────────────────┐
                         │                  NLP ENGINE                     │
                         │  entities: lexicon + transformer biomedical NER │
                         │  · drug→generic/ATC (RxNorm) · symptom→MedDRA   │
                         │    PT/SOC (+ICD-11) · sentiment · negation      │
                         │  · 4-gate AE detector                           │
                         └───────────────────────┬───────────────────────┘
                                                 │  ProcessedPost
              ┌──────────────────────────────────┼──────────────────────────────────┐
              ▼                                   ▼                                   ▼
   ┌────────────────────┐          ┌──────────────────────────┐       ┌────────────────────────┐
   │  DISPROPORTIONALITY │          │   TREND / SPIKE ENGINE    │       │   WHO-UMC CAUSALITY     │
   │  PRR · ROR · χ²     │          │   time buckets · EWMA·z   │       │   deterministic scoring │
   └─────────┬──────────┘          └────────────┬─────────────┘       └───────────┬────────────┘
             │                                   │                                 │
             └───────────────┬───────────────────┴─────────────────┬───────────────┘
                             ▼                                       ▼
                   ┌───────────────────┐                 ┌────────────────────────┐
                   │   SIGNAL STORE     │◄────evidence────│  openFDA FAERS (no key)│
                   │   + KNOWLEDGE GRAPH│                 │  + E2B R2/R3 XML export │
                   │   + LLM narrative  │                 └────────────────────────┘
                   └─────────┬─────────┘
                             │  REST (FastAPI) + JWT auth/roles
                   ┌─────────▼──────────────────────────────────────────┐
                   │        REACT DASHBOARD (Vite + Recharts + graph)     │
                   │  Overview · Signals · Knowledge Graph · Alerts ·     │
                   │  Live Feed · Forge · Onboarding · Explainability     │
                   └──────────────────────────────────────────────────────┘
                             ▲
                   ┌─────────┴─────────┐        ┌────────────────────────┐
                   │  AGENTIC FORGE     │        │  AGENTIC FORUM         │
                   │  synthetic posts   │        │  ONBOARDING            │
                   │  (Ollama + judges) │        │  (Firecrawl / heuristic)│
                   └───────────────────┘        └────────────────────────┘
```

## 3. Performance model (why it's fast and offline-safe)

- **Bulk seed** uses deterministic lexicon NER + regex PII (the synthetic corpus is built
  from known terms, so entities are identical) — ingests ~260 posts in a few seconds.
- **Transformer NER + Presidio + online translation** run on the smaller live-crawl and
  stream batches, and on `POST /api/ingest/seed?ml=true`.
- **openFDA** lookups during signal recomputation are **prefetched concurrently** (thread
  pool) and cached; translation calls are wrapped in a **hard timeout** so a slow network
  can never hang ingest.
- **LLM narratives / Forge** (Ollama) are generated **on demand**; every signal always has
  an instant deterministic narrative.

## 4. What we lift from each source project

**From Algo-Pharma:** PRR/ROR/χ² disproportionality math; the 4-gate explainable AE detector
(drug + symptom + negative sentiment + non-negated symptom); negation gating; agentic
forum-onboarding concept.

**From SignalRx/AyuScout:** WHO-UMC deterministic causality; openFDA evidence boost + brand→generic
normalization; ICH E2B R2/R3 XML export; PII vault/sanitization; the synthetic-data **Forge**
(scenario → generate → judge → repair → score → export); dashboard structure.

**New (brief-driven):** Drug–Symptom–Condition **Knowledge Graph**; **real-time streaming**
ingestion; explicit **trend/spike** emerging-signal detection. **Worldwide layer:** transformer
biomedical NER, RxNorm/ATC normalization, MedDRA-style + ICD-11 coding, multilingual translation,
multi-locale Presidio PII.

## 5. Tech Stack

- **Backend:** FastAPI, SQLAlchemy, SQLite, scipy, networkx, VADER, feedparser, httpx.
- **Worldwide NLP:** transformers + torch (biomedical NER), Presidio + spaCy (PII),
  deep-translator + langdetect (translation), RxNorm/ICD-11 public APIs.
- **Auth:** python-jose (JWT) + passlib (bcrypt), role hierarchy admin > analyst > viewer.
- **LLM (optional):** Ollama (local, no key) → OpenRouter/Gemini if keyed.
- **Frontend:** React 19 + Vite, Recharts, react-force-graph-2d, Tailwind.
- **Evidence connectors (keyless, live, cached, offline fallback):** openFDA FAERS
  (`/drug/event`), MAUDE (`/device/event`), drug/device enforcement recalls
  (`/*/enforcement.json`), device classification (`/device/classification.json`),
  DailyMed SPL (`/services/v2/spls.json`), RxNorm/RxNav, PubMed E-utilities. Signal
  evidence is enriched **lazily per signal on first view** (≤4 calls, cached, persisted)
  rather than as a bulk fan-out, to respect NCBI rate limits and keep recompute fast.
  Licensed/distributed networks (WHO VigiBase/VigiLyze, FDA Sentinel, NESTcc,
  registries) remain clearly-labeled surrogates with VigiLyze-style exploration over
  our own signal store.

## 6. Data Model (summary)

- `users` — email, hashed password, role (admin/analyst/viewer), is_active, last_login.
- `raw_posts` — PII-scrubbed source + English text, `lang` / `lang_name` / `translated`,
  `region`, `country`, platform, url, author_hash, posted_at.
- `processed_posts` — entities (with generic/ATC + PT/SOC), sentiment, negation, ae_flag,
  ae_confidence, ae_reason, gate_trace.
- `signals` — drug, symptom, `drug_atc`, `meddra_pt`/`meddra_soc`, `regions_json`, counts,
  PRR/ROR/χ², strength, trend_score, spike_flag, who_umc (+ factors), severity,
  fda_evidence, narrative (+ source), supporting_post_ids.
- `alerts` — emitted when a signal crosses severity / spike / strength thresholds.
- `forge_records` — synthetic posts with scenario, per-axis scores, quality, export_ready.

See `backend/app/models.py` for the authoritative schema.

---

## 7. Statistical rigor — frequentist + Bayesian disproportionality

`app/analytics/disproportionality.py` now computes, per (product, event) pair:

- **PRR** and **ROR** with **95% confidence intervals** (log-based standard error).
- **Yates-corrected χ²** with **Haldane-Anscombe +0.5** on all cells (small-N safe).
- **EBGM / EB05** — MGPS Empirical-Bayes Geometric Mean via a Gamma-Poisson shrinkage
  prior (DuMouchel-style method-of-moments), with the 5% lower bound EB05 (FDA threshold ≥ 2).
- **IC / IC025** — BCPNN Information Component with its 2.5% lower bound (UMC/VigiBase
  threshold > 0).
- **SDR flag** (Signal of Disproportionate Reporting): `IC025 > 0` OR `EB05 ≥ 2` OR
  `PRR CI-lower ≥ 1 with χ² ≥ 4 and n ≥ 3`.

Bayesian shrinkage is the key upgrade for noisy social data: it pulls small-count pairs
toward the null so a 2-report coincidence cannot masquerade as a strong signal, while
genuine high-volume associations survive.

## 8. Medical-device vigilance (drugs + devices)

`product_type` (`drug | device | combination`) flows through RawPost → ProcessedPost →
Signal. `app/nlp/devices.py` adds a device lexicon/NER, **GMDN / FDA product-code**
surrogates, and **IMDRF** failure-mode terms; the 4-gate detector treats device +
malfunction as product + event. Evidence is routed by product type: **openFDA MAUDE**
(`/device/event.json`, keyless) for devices, **FAERS** for drugs (`app/evidence/fda.py`
`query_evidence`).

## 9. Continuous monitoring, KPIs & compliance

- **Background scheduler** (`app/scheduler.py`): a daemon thread that periodically ingests
  a stream/Reddit batch and triggers recompute — real autonomous surveillance with
  start/stop/status, idempotent and offline-safe.
- **Recompute performance**: a persistent openFDA cache + review/detection-metadata
  preservation make warm recomputes ~0.1s; narratives are generated on demand. (Full
  disproportionality is recomputed because the marginals are global — statistically correct.)
- **KPIs / SPC** (`app/analytics/kpis.py`): time-to-detection, actionable-signal rate,
  false-positive ratio, and a Shewhart **SPC control chart** (mean ± 3σ) over daily alert
  frequency; an HCP **review** loop (`/signals/{id}/review`) and append-only **audit trail**.
- **Surveillance source registry** (`app/evidence/registry.py`): 17 worldwide networks —
  4 live keyless connectors (FAERS, MAUDE, labels, RxNorm) + clearly-labeled surrogates
  (VigiBase/VigiLyze, Sentinel, NESTcc, ISMP, MEDMARX, registries…), honest about what is
  openly ingestible; VigiLyze-style exploration is emulated over VigilAI's own signals.

## 10. Literature grounding

- **Trontell (2004)** — pre-market trials miss rare/late ADRs → proactive "prepared mind"
  social listening.
- **Hauben et al. (2007)** — fuse automated data-mining algorithms with clinical validation
  on sparse, noisy data (our disproportionality + WHO-UMC + review loop).
- **FDAAA (2007) & 21st Century Cures** — active multi-center surveillance and RWE/RWD
  (streaming, source registry, KPIs).
- **Downing et al.** — >30% of novel therapeutics see a post-market safety event within a
  median 4.2y → causality risk-weighting for biologics, accelerated approvals, psychiatric
  therapeutics, and high-risk (Class III) devices.

> Compliance note: MedDRA (PT/SOC), GMDN, and IMDRF coding are open surrogates, not the
> licensed terminologies; openFDA is US FAERS/MAUDE only; E2B XML is a demo template.
