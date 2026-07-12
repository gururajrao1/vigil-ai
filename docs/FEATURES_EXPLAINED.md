# VigilAI — Every Feature Explained (Plain Language)

> Teach-yourself / presenter dictionary. For every capability: **what it is**, **what it means**, **why it exists**, **where to click**, and **what to say**.  
> Companion: [`VIGILAI_COMPLETE_GUIDE.md`](./VIGILAI_COMPLETE_GUIDE.md) (ordered ops guide).  
> **Login:** `admin@vigilai.dev` / `admin123` · **UI:** http://localhost:5173

---

## How to read this doc

VigilAI is one pipeline:

```
DATA IN  →  CLEAN & UNDERSTAND  →  DETECT AEs  →  FIND SIGNALS  →  CORROBORATE  →  GOVERN & EXPORT
```

Everything below is either a **way data enters**, a **way text becomes clinical facts**, a **math / analytics lens**, an **evidence overlay**, a **governance / export tool**, or a **UI page** that shows those pieces.

---

# PART A — Big picture

## A1. What problem VigilAI solves

After a drug or device is approved, rare or late harms often show up first in **patient talk, news, and case reports** — long before they are tidy ICSRs in a regulator database. VigilAI:

1. **Listens** to many worldwide sources  
2. **Removes identifiers** (PII) and translates to English  
3. **Finds** drugs/devices + symptoms/failures  
4. **Flags** posts that look like adverse events (explainable rules)  
5. **Computes** whether a product–event pair is reported *more than expected*  
6. **Corroborates** with FAERS / MAUDE / labels / literature  
7. **Exports** regulator-shaped packages (E2B, CIOMS)  

It is for **research / demos / hypothesis generation**, not a validated clinical system of record.

## A2. What a “signal” means here

A **safety signal** in VigilAI is usually a **(product, event)** pair — e.g. *isotretinoin → depression* or *pacemaker → battery failure* — with:

- Enough supporting posts  
- Disproportionality statistics (PRR, EB05, …)  
- Optional causality, severity, spike, trust, evidence packs  

**Not** every noisy social mention is a signal. Posts feed the AE detector; signals appear after corpus-level math.

## A3. Auth & roles

| Role | Meaning | Typical use |
|------|---------|-------------|
| **Admin** | Full control | Reset, users, all ingest |
| **Analyst** | Work the desk | Forge, Onboarding, Command, review |
| **Viewer** | Read-only | Explore dashboards / exports |

Most dashboards are readable without login; write/agent pages need analyst+. JWT session in the browser; keys stay on the **server**.

---

# PART B — How data gets in

Each source becomes **posts** in the DB. After enough new posts, VigilAI **recomputes signals** across the corpus.

## B1. Top-bar DemoBar (global controls)

| Control | Meaning | Used for |
|---------|---------|----------|
| **Sources** dropdown | Multi-select which crawlers to run | Batch “fill the desk” with live/news/regulatory data |
| **Select fast** | Only quick sources (skips Reddit/YouTube/Twitter) | Avoid 15+ minute demo hangs |
| **▶ Fetch** | Run selected crawls with **one** final recompute | Efficient multi-source ingest |
| **Demo corpus** | Seed ~21 days of synthetic worldwide posts | Instant full demo without Wi‑Fi crawls |
| **Reset** | Wipe posts/signals/alerts | Clean slate — **never mid-presentation** |

## B2. Every ingest source (what / why / where)

### Social & conversation

| Source | What it is | Why it exists | Where |
|--------|------------|---------------|-------|
| **Google News** | 5 curated PV RSS queries (drug AEs, vaccines, recalls, warnings…) | Reliable on corporate networks; no key | Sources / DemoBar / Live Feed |
| **Life-science news** | 9 outlets: ScienceDaily, STAT, Nature Med, WHO, NPR Health, Medical Xpress, FiercePharma, Endpoints, GEN | Journalism/agency context, not forums | Same |
| **HackerNews** | Algolia search for drug-safety chatter | Tech/clinical discussion; no key | Same |
| **YouTube** | Video titles, descriptions, tags + AE-related comments | Patient/educator video voice; needs `YOUTUBE_API_KEY` | Same (slow) |
| **X / Twitter** | Pharma/health tweets | Real-time social; needs `TWITTERAPI_IO_KEY` | Same (slow) |
| **Reddit direct / health** | 29 health subs via reddit.com | Classic patient forums; often **blocked** on corp nets | Same (slow) |
| **Reddit Pullpush** | Same subs via archive mirror | Works when Reddit.com is blocked; **~1–2 min** | Same (slowest) |
| **Synthetic batch / stream** | Fake but realistic posts | Offline demo, self-heal final fallback | DemoBar / Live Feed |
| **Forum onboarding** | Any patient-forum URL → selectors → optional samples | Onboard new sites without hand-written scrapers | `/onboarding` |

### Regulatory — drugs

| Source | What | Why | Where |
|--------|------|-----|-------|
| **FDA FAERS live** | Serious openFDA AE case snippets as posts | Real ICSRs into the same pipeline | Sources / DemoBar |
| **FDA RSS / MedWatch / recalls / press** | Regulatory news queries + enforcement | Official safety chatter | Same |
| **DailyMed labels** | New/revised labeling RSS | Label changes as surveillance fodder + label-gap later | Same |
| **PubMed** | PV / drug-safety papers | Literature early warning | Same |

### Regulatory — devices

| Source | What | Why | Where |
|--------|------|-----|-------|
| **MHRA devices (UK)** | Field Safety Notices / device alerts (gov.uk) | UK device vigilance | Sources / DemoBar |
| **MAUDE live (US)** | Device MDR narratives | Device AEs same as drug posts (`product_type=device`) | Same |
| **EUDAMED** | EU registry lookup (UDI, CE class, GMDN) | Enrich device **Signal Detail** (not bulk crawl) | Auto on device detail |

### Clinical interoperability

| Source | What | Why | Where |
|--------|------|-----|-------|
| **FHIR R4** | Paste AdverseEvent / MedicationStatement bundle | EHR → same PV desk | `/sources` FHIR panel |

### Live continuous mode

**Live Feed** (`/feed`): pick a mode + interval → **Start monitoring**. Server daemon keeps crawling even if you close the tab; shows 🟢🟡🔴 health and self-heal.

## B3. Self-healing crawler

If a source fails: **retry → quarantine → fallback chain** (e.g. Twitter → Pullpush → Google News → Synthetic). Goal: **never go fully dark**.

---

# PART C — Cleaning & understanding text (NLP)

Runs on **every** ingested post (mostly automatic; you see results on Live Feed posts and Signal Detail).

| Piece | Plain meaning | Why |
|-------|---------------|-----|
| **PII scrubbing** | Remove emails, phones, IDs, names (regex + optional Presidio) | Privacy; also **before** any LLM sees text |
| **Language detect + translate** | Non-English → English | Worldwide listening |
| **Vernacular map** | Slang (“brain zaps”) → clinical PT | Catch patient language |
| **Lexicon entities** | Match curated drug/symptom/device lists | Fast, offline, demo-stable |
| **Transformer NER** | Biomedical ML model (`d4data/biomedical-ner-all`) when enabled | Broader recall; footer shows NER mode |
| **Drug normalization** | Brand → generic + ATC | Clean stats keys |
| **MedDRA-style coding** | Symptom → PT / SOC (*open surrogate*) | Coding + SOC charts |
| **Device / IMDRF / GMDN** | Device type + failure mode codes | Device vigilance coding |
| **Sentiment (VADER)** | Pos / neu / neg | Feeds AE gate 3 |
| **Negation** | “no rash” ≠ rash | Feeds AE gate 4 |
| **4-gate AE detector** | Explainable rule (see below) | Which posts count as adverse events |

### The 4 gates (core explainability)

A post is an AE only if **all** pass:

1. **Product** present (drug or device)  
2. **Event** present (symptom or device failure)  
3. **Negative** sentiment (complaint tone)  
4. Event is **not negated**  

Each supporting post on Signal Detail can show a **gate trace** — this is the “show your work” story for judges.

---

# PART D — Finding & scoring signals (analytics)

After AEs exist, VigilAI counts **how often product A co-occurs with event B** vs the rest of the corpus and runs multiple lenses.

## D1. Disproportionality (the core stats)

| Metric | Plain meaning | Rule of thumb in UI |
|--------|---------------|---------------------|
| **PRR** | “This pair is X× more common than expected by share” | Often ≥ 2 with N ≥ 3 |
| **ROR** | Odds-ratio version of the same idea | CI lower often > 1 |
| **χ²** | Is the table imbalance significant? | ≥ ~4 |
| **EBGM / EB05** | Bayesian shrinkage (MGPS-style); EB05 = cautious lower bound | EB05 ≥ ~2 “FDA-ish” |
| **IC / IC025** | Information Component (BCPNN); IC025 = lower bound | IC025 > 0 “UMC-ish” |
| **SDR** | Signal of Disproportionate Reporting — combined gate | Filter **SDR only** on Signals |
| **Strength** | STRONG / MODERATE / WEAK tier | Quick triage tabs |

**Where:** `/signals` table + Signal Detail stats cards. Sort by EB05 to punish sparse noise.

## D2. Causality, severity, sentiment decoupling

| Feature | Meaning |
|---------|---------|
| **WHO-UMC** | Certain / Probable / Possible / Unlikely / Unassessable from deterministic cues (time, dechallenge, rechallenge, priors…) |
| **Severity** | Clinical seriousness band (Critical → Low) — **not** the same as sentiment |
| **Sentiment on posts** | Tone of text; used in gates, shown on feed |

## D3. Trend & spike

Daily buckets + **EWMA / z-score**. Spike badge = volume jumped vs its own baseline → Alerts + Filters (**Spiking only**).

## D4. Specialist analytic desks

| Feature | Meaning | Page |
|---------|---------|------|
| **SMQ syndromes** | Group related PTs into a syndrome (DILI, SCAR, anaphylaxis…) so risk isn’t missed when split across synonyms | `/smq` |
| **Class effects / ATC** | Same-class drugs sharing an event → class story | `/class-effects` |
| **Active comparator** | Vs *other drugs in same ATC* (reduces pure indication confounding) | Signal Detail |
| **Read-across / analogs** | Structural/pharmacologic cousins | Class page + Detail |
| **Vaccine AESI** | Watchlist events post-immunisation | `/vaccine` + badges |
| **Brighton (surrogate)** | Certainty levels for vaccine cases | Vaccine |
| **SCRI (surrogate)** | Risk window vs control window rates | Vaccine |
| **Geo clusters** | Kulldorff-style: reports pile up in a region beyond expectation | `/spatial` |
| **Knowledge graph** | Force graph: drugs ↔ symptoms ↔ conditions | `/graph` |
| **PGx** | Gene–drug risk overlays (CPIC/PharmGKB-style table) | Detail / filter |
| **Boxed warning** | Event already in black-box language? | Detail / filter |
| **Label gap** | Event not (or differently) on label vs DailyMed knowledge | Detail / novelty |
| **Mechanism** | MoA makes the AE biologically plausible? | Detail |
| **MaxSPRT** | Sequential testing as data accumulates — boundary crossed? | Detail / filter |
| **Cox HR (surrogate)** | Time-to-mention hazard vs comparators | Detail |
| **Empirical calibration + E-value** | Beat an empirical null; how hard would confounding be? | Detail / filter |
| **Completeness (vigiGrade-style)** | How ICSR-like are supporting posts? | Detail / KPIs / filter |
| **Benefit–risk** | Structured benefit vs harm framing | Copilot / Detail |
| **Trust / Sybil** | Does the supporting cohort look authentic vs coordinated spam? | Detail badges |
| **Thread / cohort RAG score** | Red/Amber/Green multi-post corroboration | Signal Detail card |
| **Federated + DP** | Simulate multi-site PRR with differential privacy noise | `/federated` |
| **Ed25519 audit chain** | Cryptographic hash chain of signal snapshots | Detail Verify + Command panel |

---

# PART E — Evidence (outside the social corpus)

Lazy-loaded on Signal Detail (cached after first open; seed pre-warms top signals):

| Evidence | Meaning |
|----------|---------|
| **openFDA FAERS** | US drug AE database corroboration |
| **MAUDE** | Device MDR corroboration |
| **DailyMed** | US labeling text |
| **PubMed** | Literature hits |
| **Recalls / enforcement** | Product recalls |
| **FDA device classification** | Class I/II/III, product code |
| **EUDAMED** | EU device registry fields |

If the network is down, **offline stubs / caches** still render something honest.

---

# PART F — Pages (every screen)

## F1. Overview `/`
**What:** Command center dashboard.  
**Shows:** Posts, AE rate, signals, alerts, spikes, countries, languages, sentiment mix, top drugs, strength mix, regions, MedDRA SOCs.  
**Say:** “Every KPI traces to scrubbed posts worldwide.”

## F2. Safety Signals `/signals`
**What:** Triage queue of all product–event pairs.  
**Use:** Filter SDR / device / vaccine / PGx / … → sort EB05 → open hero row.  
**Say:** “This is how a safety scientist works a list top-down.”

## F3. Signal Detail `/signals/:id`
**What:** The full dossier. Walk panels:

1. Badge strip (SDR, WHO-UMC, PGx, boxed, class, geo, AESI, spike, HR, MaxSPRT…)  
2. AI narrative (+ Regenerate)  
3. Copilot assessment (Escalate / Monitor / Close draft)  
4. Disproportionality cards  
5. Active-comparator / calibration / completeness / HR / MaxSPRT  
6. Clinical overlays (label, mechanism, PGx…)  
7. Vaccine / geo / class cards when relevant  
8. Thread corroboration + trust  
9. Gate-traced supporting posts  
10. External evidence  
11. Lifecycle / Confirm–Dismiss  
12. Downloads: **E2B R3**, **E2B R2**, **CIOMS**  
13. Verify audit chain  

**Say:** “One click from weak social text to regulator-shaped package.”

## F4. Signal Lifecycle `/lifecycle`
**What:** GVP Module IX–**inspired** Kanban (new → evaluation → validated → … → closed/rejected) with owner, notes, priority.  
**Say:** “Detection without governance isn’t PV.”

## F5. SMQ `/smq`
**What:** Syndrome-level roll-ups (Active corpus view + Full catalog of ~13 SMQs).  
**Say:** “Related PTs assembled so SCAR/DILI aren’t fragmented.”

## F6. Class Effects `/class-effects`
**What:** ATC subgroups, class effects (2+ drugs), analog catalog.  
**Say:** “Molecule problem or class problem?”

## F7. Vaccine `/vaccine`
**What:** Vaccine registry + AESI cards + Brighton/SCRI surrogates.  
**Say:** “Immunisation safety desk, honest about social-timestamp limits.”

## F8. Geo `/spatial`
**What:** Ranked geographic hotspots with RR/LLR.  
**Say:** “Hypothesis of local concentration — not proof.”

## F9. Knowledge Graph `/graph`
**What:** Interactive drug–symptom–condition network (force layout).  
**Say:** “Relational view of what co-occurs in the corpus.”

## F10. KPIs & SPC `/kpis`
**What:** Time-to-detection, actionable rate, false-positive story, Shewhart control chart on alerts, audit trail.  
**Say:** “Ops quality of the PV process, not only science.”

## F11. Alerts `/alerts`
**What:** Auto alerts when severity/spike/SDR/strong conditions hit.  
**Actions:** Acknowledge · **Notify** (webhook or simulated outbound).  

## F12. Live Feed `/feed`
**What:** Post stream + autonomous monitoring worker + health chips.  

## F13. Sources `/sources`
**What:** All connectors with status, crawl buttons, AE-yield bars, FHIR paste, LLM status.  

## F14. Command Center `/command`
**What:** Natural language → parse source+query → crawl+ingest (MCP-lite). Audit chain panel beside chat.  
**Example:** `crawl google news about ozempic side effects`  
**Needs:** analyst login.

## F15. Forum Onboarding `/onboarding`
**What:** Paste URL → propose CSS selectors (Firecrawl / heuristics / LLM) → optionally ingest scrubbed samples.  
**Needs:** analyst.

## F16. Surveillance Net `/surveillance`
**What:** Honest catalogue — which networks are **live connectors** vs **licensed surrogates** (VigiBase, Sentinel…) plus VigiLyze-style explorer over **VigilAI’s own** store.  
**Say:** “We don’t pretend we are WHO VigiBase.”

## F17. Data Forge `/forge`
**What:** Agentic synthetic AE text: scenario → generate → multi-judge scores → repair → export JSONL/CSV.  
**Important:** Does **not** silently dump into the live signal vault.  
**Needs:** analyst · works with Gemini if Ollama offline.

## F18. Federated / DP `/federated`
**What:** Toy multi-site federated PRR with Laplace/Gaussian DP noise and privacy budget.  
**Say:** “How orgs could share *signals* without sharing raw posts.”

## F19. Login `/login`
Sign in / register. First user becomes admin; later public register → viewer.

## F20. ⌘K / Ctrl+K
Type a page name and jump — PulseAI-style command palette.

## F21. Health footer
Backend online · which **LLM** (Ollama/Gemini/…) · **NER** mode (transformer/lexicon) · Presidio flags.

---

# PART G — Exports & LLM

| Export | Meaning |
|--------|---------|
| **E2B R3 / R2** | ICH electronic ICSR XML **demo templates** |
| **CIOMS I** | Classic 6-section paper form as HTML |

| LLM use | Meaning |
|---------|---------|
| Narratives | Plain-English signal summary |
| Copilot | Structured PV memo |
| Forge judges | Quality scoring / repair |
| Command / onboard | Slot-fill & selector help |

**Chain:** Ollama (local) → **Gemini** → OpenRouter → deterministic templates. Configure `GEMINI_API_KEY` in `backend/.env`.

---

# PART H — Device path (end-to-end)

1. Ingest MHRA / MAUDE (or seeded device posts)  
2. Device NER → GMDN + IMDRF failure  
3. Same 4-gate + disproportionality  
4. Signal Detail shows device badges, **skips** drug-only overlays (DailyMed PGx), shows **MAUDE + EUDAMED + FDA class**  

---

# PART I — Suggested “explain everything” talk track (15–20 min)

1. Problem + Overview KPIs  
2. Sources honesty (Surveillance Net) + Fetch three fast sources  
3. Signals list (SDR + EB05) → hero Detail walk  
4. Device **or** Vaccine + Geo (one)  
5. Lifecycle + Alerts Notify  
6. Command **or** Forge **or** Onboarding (one agentic beat)  
7. Exports + offline-first / Gemini footer  

---

# PART J — Honest limits (say these if asked)

- SMQ / MedDRA / Brighton / SCRI / HR / calibration = **research surrogates** where labeled  
- E2B/CIOMS = **demo** packages, not validated submissions  
- Federated/DP = **simulation** on local partitions  
- One deployed instance = **one shared DB** for all link users  
- Reset wipes everyone’s shared cloud data  

---

# Quick glossary

| Term | One line |
|------|----------|
| **AE** | Adverse event mention that passed 4 gates |
| **ICSR** | Individual case safety report |
| **PT / SOC** | MedDRA Preferred Term / System Organ Class |
| **ATC** | WHO drug classification hierarchy |
| **SDR** | Stats say “disproportionate reporting” |
| **GVP IX** | EU good PV practice for signal management |
| **FAERS / MAUDE** | US drug / device AE databases |
| **EUDAMED** | EU device database |
| **AESI** | Vaccine adverse event of special interest |
| **PGx** | Pharmacogenomics |
| **MaxSPRT** | Sequential probability ratio test for safety monitoring |

---

*This is the exhaustive plain-language feature dictionary for the VigilAI presentation build.*
