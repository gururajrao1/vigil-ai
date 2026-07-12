# VigilAI — Original Features (Beyond the Three GitHubs)

> Features built **for VigilAI itself**, not simple ports of Algo-Pharma, pan-IITian / SignalRx, or PulseAI.  
> Companion doc: [`FEATURES_BY_SOURCE.md`](./FEATURES_BY_SOURCE.md) (full catalogue by origin).  
> **Login:** `admin@vigilai.dev` / `admin123` · **UI:** http://localhost:5173

---

## Quick map

| Feature | Sidebar / UI location | One-line purpose |
|---------|----------------------|------------------|
| Life-science news pack | Sources · DemoBar · Live Feed | Pharma/med journalism RSS → signals |
| Device vigilance | Sources · Signal Detail (devices) | MHRA / MAUDE / EUDAMED for devices |
| Bayesian disproportionality | Safety Signals · Signal Detail | EBGM/EB05, IC/IC025 + SDR triage |
| SMQ syndromes | **SMQ Syndromes** `/smq` | Group related AEs into syndromes |
| Class effects / ATC | **Class Effects** `/class-effects` | Same-class drug read-across |
| Vaccine AESI / SCRI | **Vaccine Safety** `/vaccine` | Vaccine-specific safety analytics |
| Geo clusters | **Geo Clusters** `/spatial` | Where reports concentrate |
| GVP lifecycle | **Signal Lifecycle** `/lifecycle` | Govern signals like a PV team |
| Clinical overlays | Signal Detail cards | Label gap, boxed warn, PGx, mechanism |
| Advanced stats suite | Signal Detail badges/cards | MaxSPRT, HR, calibration, B–R, completeness |
| Gemini LLM fallback | Health footer · Forge · Copilot | Cloud LLM when Ollama is down |
| FHIR R4 ingest | **Data Sources** FHIR panel | Paste EHR AdverseEvent bundles |
| Surveillance Net | **Surveillance Net** `/surveillance` | Honest live vs surrogate catalogue |
| Alert Notify | **Alerts** → Notify | Push webhook / simulated ops delivery |
| Demo multi-fetch | Top bar **Sources** → Fetch | Batch ingest + one recompute; Select fast |

---

## 1. Life-science news RSS pack

**What it is**  
Nine curated RSS feeds from serious life-science / pharma journalism and health agencies (ScienceDaily, STAT, Nature Medicine, WHO, NPR Health, Medical Xpress, Fierce Pharma, Endpoints, GEN).

**What it means**  
Not patient forums — **editorial and agency headlines** about drugs, trials, outbreaks, and safety. Useful early weak signals and narrative context next to social chatter.

**What it’s used for**  
- Demo “listening” without Reddit (often blocked)  
- Corroborate a drug/AE story with news environment  
- Live Feed mode for continuous news pull  

**Where to find it**  
- Top bar → **Sources** dropdown → **Life-science news** → Fetch  
- Sidebar → **Data Sources** → Life-science  
- Sidebar → **Live Feed** → life-science mode  
- API: `POST /api/ingest/life-science`, `GET /api/ingest/life-science/feeds`

---

## 2. Device vigilance (MHRA · MAUDE · EUDAMED)

**What it is**  
Medical-device post-market listening:

| Piece | Meaning |
|-------|---------|
| **MHRA devices** | UK Field Safety Notices / device alerts (gov.uk Atom) |
| **MAUDE live** | US FDA device MDR narratives via openFDA |
| **EUDAMED** | EU device registry lookup (CE / UDI-style enrichment) — not a bulk crawl |

**What it means**  
Classic PV is drug-heavy. This extends VigilAI to **devices** (pumps, implants, diagnostics) with the same NLP → signal pipeline and `product_type=device`.

**What it’s used for**  
Show worldwide product coverage (drugs + devices); open a device signal and show regulatory device evidence.

**Where to find it**  
- Sources / DemoBar → **MHRA device alerts**, **MAUDE live**  
- Safety Signals → filter **device**  
- Signal Detail → evidence / EUDAMED when applicable  
- API: `POST /api/ingest/mhra-devices`, `POST /api/ingest/maude-live`, `GET /api/device/eudamed?device=…`

---

## 3. Bayesian disproportionality (EBGM / EB05 · IC / IC025 · SDR)

**What it is**  
Beyond simple PRR/ROR/χ², VigilAI computes **Empirical Bayes (MGPS-style)** and **BCPNN Information Component** metrics, then marks **SDR** (signals of disproportionate reporting) when bounds cross PV thresholds.

| Metric | Plain meaning | Typical “interesting” rule (as used in UI) |
|--------|---------------|--------------------------------------------|
| **EBGM / EB05** | Shrinkage estimate of reporting rate; EB05 = cautious lower bound | EB05 ≥ ~2 often treated as stronger |
| **IC / IC025** | “How surprising is this drug–event pair?”; IC025 = lower bound | IC025 > 0 often treated as UMC-style interest |
| **SDR** | Boolean: passes disproportionality criteria | Filter “SDR only” on Signals list |

**What it’s used for**  
Triage: don’t only sort by raw report count — sort/filter by **strength of association** after accounting for background noise.

**Where to find it**  
- **Safety Signals** `/signals` — sort by EB05 / IC025; SDR checkbox  
- **Signal Detail** — stats strip (PRR, ROR, EB05, IC025, χ², …)  
- Overview / KPIs — strength distributions  

---

## 4. SMQ syndromes

**What it is**  
**SMQ** = Standardised MedDRA Query–*style* groupings: related Preferred Terms rolled into a **syndrome** (e.g. anaphylactic reaction cluster), so you don’t miss a pattern split across many PT names.

**What it means**  
“Is this one weird symptom, or a **known clinical syndrome** of related events?”

**What it’s used for**  
Safety review / demo of MedDRA-style thinking; filter signals by syndrome.

**Where to find it**  
- Sidebar → **SMQ Syndromes** `/smq`  
- Safety Signals → syndrome filter (when populated)  

> **Honest limit:** open MedDRA-*style* surrogates, not licensed MedDRA SMQ content.

---

## 5. Class effects + ATC / read-across

**What it is**  
Roll-up of signals by **pharmacologic class** (ATC-style), plus **read-across / analog** hints: if drug A in a class shows event X, related drugs may share risk narrative.

**What it means**  
Regulators often ask: *is this molecule-specific or a **class effect**?*

**What it’s used for**  
Pitch “class-level PV”; compare drugs in the same ATC group on one page.

**Where to find it**  
- Sidebar → **Class Effects** `/class-effects`  
- Signal Detail → read-across / structural analog notes when present  

---

## 6. Vaccine AESI / Brighton / SCRI

**What it is**  
Vaccine-oriented safety layer:

| Concept | Plain meaning |
|---------|---------------|
| **AESI** | Adverse Events of Special Interest — predefined events watched after immunisation |
| **Brighton** | Case-definition levels of diagnostic certainty (social-listening *surrogate* here) |
| **SCRI** | Self-Controlled Risk Interval — event rate in a risk window vs control window (timestamp *surrogate*) |

**What it’s used for**  
Show VigilAI isn’t only “chronic drug AEs” — it has an immunisation safety story.

**Where to find it**  
- Sidebar → **Vaccine Safety** `/vaccine`  

> **Honest limit:** Brighton/SCRI here are **research surrogates**, not clinician-adjudicated case reviews.

---

## 7. Spatial clusters (Kulldorff-style)

**What it is**  
A **scan-style** check: do reports for a drug–event pair **pile up in a country/region** more than you’d expect from overall geography?

**What it means**  
Possible local manufacturing, use-pattern, or reporting-culture hotspot — a **hypothesis**, not proof of causality.

**What it’s used for**  
Geographic storytelling on a signal (“cluster in Region X”).

**Where to find it**  
- Sidebar → **Geo Clusters** `/spatial`  
- Safety Signals / Signal Detail → geo-cluster badge when flagged  

---

## 8. GVP Module IX–style signal lifecycle

**What it is**  
A **Kanban board** for signal governance (new → under monitoring → validated / refuted / closed, with owner and notes), inspired by **EU GVP Module IX** process thinking.

**What it means**  
Detection ≠ done. PV teams **manage** signals over time with accountability.

**What it’s used for**  
Live demo of “how a safety team would work the queue,” not only detect.

**Where to find it**  
- Sidebar → **Signal Lifecycle (GVP)** `/lifecycle`  
- Signal Detail → lifecycle / review controls  

---

## 9. Clinical overlays (label gap · boxed warnings · PGx · mechanism)

**What it is**  
Context cards on Signal Detail that answer: *is this already on label? boxed? genetically relevant? mechanistically plausible?*

| Overlay | Used for |
|---------|----------|
| **Label gap** | Spot potentially **unlabelled** (or differently labelled) risk vs DailyMed-style knowledge |
| **Boxed warning** | Tie the story to known **highest-severity** label language |
| **PGx** | Pharmacogenomic modifiers (who may be at higher risk) |
| **Mechanism** | Narrative plausibility (why this AE *could* fit the drug) |

**Where to find it**  
- Open any rich **Signal Detail** `/signals/:id` → scroll clinical / label / PGx / mechanism cards  

---

## 10. Advanced analytics suite (MaxSPRT · HR · calibration · benefit–risk · completeness)

**What it is** (Signal Detail badges & cards — research-grade *illustrations* on the corpus):

| Piece | Plain meaning | Used for |
|-------|---------------|----------|
| **MaxSPRT** | Sequential testing — “has evidence crossed a boundary *as data accumulates*?” | Continuous monitoring story |
| **HR / survival** | Time-to-event *surrogate* from timestamps | “earlier vs later onset” narrative |
| **Calibration** | Does risk score behave sensibly vs negative controls? | Credibility / method QA story |
| **Benefit–risk** | Structured benefit vs harm framing | Decision-support style memo |
| **Completeness** | How much ICSR-like info is present in supporting posts | Data-quality / ICSR readiness |

**Where to find it**  
- **Signal Detail** badges and lower panels  

> **Honest limit:** several use **social-time surrogates**, not full patient EHR trajectories.

---

## 11. Gemini LLM fallback chain

**What it is**  
LLM backend chain:

```
Ollama (local) → Gemini (cloud) → OpenRouter (optional) → deterministic templates
```

**What it means**  
Narratives, Copilot assessments, Forge judges, and Command/Forge agents **still work** if your laptop’s Ollama is off — as long as `GEMINI_API_KEY` is set on the **server**.

**What it’s used for**  
Cloud deploy / demos without forcing every machine to run Llama locally.

**Where to find it**  
- Footer / `GET /api/health` → `llm.gemini`, `llm.backend`  
- Used implicitly on: Forge, Copilot, narratives, Command / onboarding LLM steps  
- Configure: `backend/.env` → `GEMINI_API_KEY` → restart uvicorn  

---

## 12. FHIR R4 paste ingest

**What it is**  
Paste a FHIR **R4 Bundle** (or AdverseEvent / MedicationStatement resources); VigilAI parses them into pipeline posts (`platform=fhir`) and runs NLP → signals.

**What it means**  
Bridge from **EHR / hospital FHIR** into the same PV desk as social + news (interop story).

**What it’s used for**  
Hackathon “HL7/FHIR ready” pitch; Sources page sample bundle.

**Where to find it**  
- Sidebar → **Data Sources** `/sources` → FHIR panel  
- APIs: `POST /api/ingest/fhir`, `GET /api/fhir/sample`  

---

## 13. Surveillance Net registry

**What it is**  
A catalogue page that labels each connector as **live** vs **honest surrogate** (what we really hit vs what we simulate).

**What it means**  
Credibility with judges: we don’t pretend every badge is a production VigiBase feed.

**What it’s used for**  
Architecture / honesty slide without leaving the app.

**Where to find it**  
- Sidebar → **Surveillance Net** `/surveillance`  

---

## 14. Outbound alert Notify

**What it is**  
From Alerts, **Notify** sends (or **simulates**) an outbound notification for an alert — webhook if `ALERT_WEBHOOK_URL` is set, otherwise a logged simulated delivery.

**What it means**  
Close the loop from “signal firing” → “ops / Slack / pager-style handoff” without building a full SOAR product.

**Where to find it**  
- Sidebar → **Alerts** `/alerts` → **Notify** on a row  
- Config: `ALERT_WEBHOOK_URL` in `backend/.env`  

---

## 15. Demo multi-fetch polish (batch recompute · Select fast)

**What it is**  
Presentation-ops improvements (not PV science):

1. Multi-source **Fetch** sends `recompute=false` per crawl, then **one** `POST /api/recompute`  
2. **Select fast** selects only quick sources (excludes Reddit / YouTube / Twitter by default)

**What it means**  
Selecting “everything” no longer re-runs full-corpus signal math **after every source** (that caused 15+ minute hangs).

**Where to find it**  
- Top bar → **Sources** → **Select fast** / checkboxes → **Fetch**  
- APIs: ingest `?recompute=false`, `POST /api/recompute`  

---

## How this relates to the three GitHubs

| From the three (adapted) | VigilAI original (this doc) |
|--------------------------|-----------------------------|
| 4-gate AE, PII, forum onboard, Command chat, thread score | Life-science RSS, devices, FHIR |
| WHO-UMC, openFDA evidence, E2B, Forge, JWT, self-heal | Bayesian SDR, SMQ / class / vaccine / geo / GVP lifecycle |
| HN, YouTube comments, CIOMS, Copilot, trust, ⌘K, audit | Clinical overlays, advanced stats suite, Gemini chain, Notify, Surveillance Net, demo batching |

You can still show **ports** as “we unified three hackathon systems,” and use **this doc** as “here’s what we invented on top.”

---

## Suggested demo order (original features only)

1. **Surveillance Net** — honesty / coverage map (30s)  
2. Fetch **Life-science** + **FAERS** (or MHRA/MAUDE for devices)  
3. **Safety Signals** — sort EB05 / toggle SDR  
4. Hero **Signal Detail** — overlays + advanced badges  
5. Jump **Lifecycle** or **SMQ** / **Class Effects** / **Vaccine** / **Geo** (pick 1–2)  
6. **Alerts → Notify** (ops close)  
7. Mention **Gemini** on health footer if Ollama offline  

---

## Related docs

| Doc | Contents |
|-----|----------|
| [`FEATURES_BY_SOURCE.md`](./FEATURES_BY_SOURCE.md) | All features mapped to Algo / SignalRx / PulseAI / original |
| [`FEATURE_USAGE_GUIDE.md`](./FEATURE_USAGE_GUIDE.md) | Deep page click-paths |
| [`DEMO_SCRIPT.md`](./DEMO_SCRIPT.md) | Timed live demo |
| [`PRESENTER_GUIDE.md`](./PRESENTER_GUIDE.md) | Stage tips |
| [`ARCHITECTURE.md`](./ARCHITECTURE.md) | System design |

---

*Aligned with the VigilAI presentation build. Research / hypothesis-generation tooling — not a validated regulatory PV system of record.*
