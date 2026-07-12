# VigilAI — Feature Usage Guide

> **Purpose:** A practical "how to use each feature perfectly" manual for demos, exploration, and judge walkthroughs. Every section is grounded in the actual routes, models, and page components — nothing is invented.
>
> **Login credentials:** `admin@vigilai.dev / admin123`
> **Backend:** `http://localhost:8000` · **Frontend:** `http://localhost:5173`
> **Read-only pages:** all pages except Data Forge and Forum Onboarding.
> **Write pages (require sign-in):** Data Forge (`/forge`), Forum Onboarding (`/onboarding`).

---

## Table of Contents

1. [Getting Started](#1-getting-started)
2. [Overview Dashboard](#2-overview-dashboard)
3. [Safety Signals Page](#3-safety-signals-page)
4. [Signal Detail — Explainability Drawer](#4-signal-detail--explainability-drawer)
5. [SMQ Syndromes Page](#5-smq-syndromes-page)
6. [Class Effects Page](#6-class-effects-page)
7. [Vaccine Safety Page](#7-vaccine-safety-page)
8. [Geo Clusters Page](#8-geo-clusters-page)
9. [Federated / DP Page](#9-federated--dp-page)
10. [Knowledge Graph](#10-knowledge-graph)
11. [KPIs & SPC](#11-kpis--spc)
12. [Alerts](#12-alerts)
13. [Live Feed + Streaming Controls](#13-live-feed--streaming-controls)
14. [Data Forge](#14-data-forge)
15. [Forum Onboarding](#15-forum-onboarding)
16. [Surveillance Net](#16-surveillance-net)
17. [Sources](#17-sources)
18. [The Hero Demo Moments](#18-the-hero-demo-moments)
19. [If Asked Tough Questions](#19-if-asked-tough-questions)

---

## 1. Getting Started

### First-Time Setup

**Where to find it:** Top bar of every page (the `DemoBar` component) — four buttons always visible.

**What to do (step by step):**

1. Start backend: `cd backend && uvicorn app.main:app --reload` (port 8000).
2. Start frontend: `cd frontend && npm run dev` (port 5173).
3. Open `http://localhost:5173` in a browser — the animated 3D DNA backdrop confirms the app loaded.
4. Check the **sidebar footer** at the bottom left: it should say `Backend online`. If it says `Backend offline`, the FastAPI server is not running.
5. Click **Load demo corpus** (top-right header button). This calls `POST /api/ingest/seed?days=21&demo=true`.
   - Wait approximately **5–10 seconds** for the seed to finish (the button shows `Seeding…`).
   - After seeding finishes, external evidence (FAERS/DailyMed/PubMed/recalls) begins pre-warming on the top 12 signals in a **background thread** (~20–30 s). You do NOT need to wait — but open the isotretinoin signal once before demoing to confirm evidence is cached.
6. To sign in for write features: click **Sign in** (top-right), enter `admin@vigilai.dev` / `admin123`.
7. To simulate real-time data: click **▶ Stream batch** (top bar) — 4 new posts arrive, NLP runs, signals recompute (~1–2 s).
8. To pull live Reddit data (needs internet): click **Crawl Reddit (live)** (~3–8 s with Wi-Fi).
9. To reset for a repeat demo: click **Reset** (top bar, red button), then click **Load demo corpus** again.

**What you'll see:**
- After seeding: the Overview stat cards fill in — approximately 260 posts, ~70–90 adverse events, 30–50 safety signals, 10–20 alerts.
- Sidebar footer: `Backend online · LLM: offline · NER: lexicon` (or `Ollama` / `transformer` if those are running).
- The 3D DNA helix background animates on all pages except the Knowledge Graph (where WebGL is shared with the force-graph).

**Key things to highlight:**
- "Load demo corpus" back-dates detection and alert timestamps across a 21-day window so KPIs and the SPC control chart show a realistic distribution — the disproportionality statistics themselves are untouched.
- Evidence pre-warm runs in a daemon thread so it never blocks the UI; top signals will open instantly on stage.
- The entire app runs **offline with zero API keys** — only "Crawl Reddit (live)" requires internet.

**Common gotcha:** If you click into a signal immediately after seeding (before the ~20–30 s pre-warm finishes), DailyMed/PubMed/recalls will load on-demand for that signal (a few extra seconds). Open the isotretinoin signal once beforehand to cache it.

**API shortcut:**
```bash
# Seed with fast lexicon NLP (default) + demo timestamps:
curl -X POST "http://localhost:8000/api/ingest/seed?days=21&demo=true"

# Force evidence pre-warm on top 12 signals:
curl -X POST "http://localhost:8000/api/prewarm?limit=12"
```

---

## 2. Overview Dashboard

### Overview Dashboard

**Where to find it:** Sidebar nav label **Overview** (◧ icon) · route `/`

**What to do (step by step):**
1. Navigate to `/` — this is the default landing page.
2. The page loads automatically via `GET /api/dashboard/stats` and `GET /api/trends/overview`.
3. Scan the two rows of **stat cards** (first row: Posts ingested, Adverse events, Safety signals, Active alerts, Spikes detected, Countries + languages; second row: Critical signals, Translated posts, Regions covered, MedDRA organ classes).
4. Look at the **Signal volume over time** area chart (left panel) — two overlapping areas: total posts (sky blue) and adverse events (rose). X-axis is date (shows MM-DD); Y-axis is daily count.
5. Look at the **Sentiment mix** donut chart (right panel) — NEGATIVE (rose), NEUTRAL (slate), POSITIVE (green) slices.
6. Scroll down to see: **Top implicated drugs** (horizontal bar), **Signal strength distribution** (STRONG/MODERATE/WEAK bar), **Geographic spread** (region pie), **MedDRA System Organ Classes** (horizontal bar by SOC), **Languages detected** (bar chart).

**What you'll see:**
- Stat cards showing approximately: 260+ posts, 70–90 AE posts, 30–50 signals, 10–20 alerts, 2–5 spikes, 11 countries, 6 languages.
- Area chart with a visible AE trend over 21 days.
- Top drugs bar chart: isotretinoin, simvastatin, warfarin, codeine, clopidogrel, lisinopril, carbamazepine, azathioprine, and vaccine names.
- SOC distribution: Psychiatric disorders, Skin/subcutaneous disorders, Nervous system disorders, Musculoskeletal disorders typically at the top.
- Language bars: English dominant, plus Spanish, French, German, Portuguese, Hindi.

**Key things to highlight:**
- Every number traces back to individual PII-scrubbed posts — clicking a signal shows the exact supporting posts.
- Worldwide reach: 6 languages auto-translated to English, 11 countries, 7 geographic regions — all without any API key.
- The chart auto-refreshes whenever data changes (the app uses a global `RefreshContext`).

**Common gotcha:** If all stat cards show zeros, the demo corpus hasn't been seeded yet. Click **Load demo corpus** in the top bar and wait for `Seeding…` to finish.

**API shortcut:**
```bash
curl http://localhost:8000/api/dashboard/stats | python -m json.tool
curl http://localhost:8000/api/trends/overview | python -m json.tool
```

---

## 3. Safety Signals Page

### Safety Signals Page

**Where to find it:** Sidebar nav label **Safety Signals** (⚠ icon) · route `/signals`

**What to do (step by step):**

1. Click **Safety Signals** in the sidebar.
2. **Strength filter tabs** (top-left): click `ALL`, `STRONG`, `MODERATE`, or `WEAK` to filter by disproportionality tier.
3. **Product type dropdown**: choose `All products`, `drug`, `device`, or `combination`.
4. **Region dropdown**: choose `Global`, `North America`, `Europe`, `Asia`, `South America`, `Africa`, or `Oceania`.
5. **Syndromes (SMQ) dropdown**: choose `All syndromes (SMQ)` or a specific Standardised MedDRA Query (populated from detected signals).
6. **Sort dropdown**: choose `Sort: PRR`, `Sort: EB05 (MGPS)`, `Sort: IC025 (BCPNN)`, or `Sort: Reports`.
7. **Checkbox filters** (right side of the filter bar — scroll horizontally if needed):
   - `SDR only` — Signals of Disproportionate Reporting only (IC025 > 0, or EB05 ≥ 2, or PRR CI-lower ≥ 1 with χ² ≥ 4 and n ≥ 3)
   - `Spiking only` — EWMA z-score spike detected
   - `🧬 PGx-actionable` — genomically explainable (CPIC/PharmGKB match)
   - `⬛ Boxed-warning` — drug carries an FDA black-box warning
   - `⚛ Mechanistically plausible` — drug's MoA biologically explains the event (Bradford Hill)
   - `⚗ Class effect` — 2+ drugs in the same ATC class report this event
   - `◎ Stands out in class` — active-comparator ROR CI lower bound > 1
   - `✓ Calibrated` — survives empirical-null calibration against negative controls
   - `💉 Vaccine AESI` — vaccine signal matching an Adverse Event of Special Interest
   - `📍 Geo cluster` — reports geographically concentrated beyond expectation
   - `▤ Well-documented` — vigiGrade-style completeness ≥ 0.5
   - `⏱ HR elevated` — Cox PH hazard ratio CI lower bound > 1
   - `🔔 MaxSPRT crossed` — sequential surveillance boundary exceeded
8. Click any row to open the Signal Detail page for that signal.

**Table columns:**
- **Product → Event**: drug name (💊) or device (🩺) → MedDRA PT or symptom. Inline badges: `SDR` (rose), `🧬 PGx` (emerald), `⬛ Boxed` (amber), `⚛ Plausible` (cyan), `⚗ Class` (teal), `◎ In-class` (fuchsia), `✓ Cal` (indigo), `📍 Geo` (emerald), `💉 AESI` (pink), `▤ 0.xx` completeness dot, `⏱ HR` (orange), `🔔 MaxSPRT` (violet). Below the drug name: ATC class (drugs) or GMDN/product code (devices), MedDRA SOC, primary region, SMQ memberships, and openFDA FAERS/MAUDE corroboration if available.
- **PRR** — Proportional Reporting Ratio
- **χ²** — Yates-corrected chi-square
- **EB05** — MGPS Empirical Bayes 5% lower bound (≥ 2 = signal, shown in rose)
- **IC025** — BCPNN Information Component 2.5% lower bound (> 0 = signal, shown in rose)
- **Reports** — observed co-report count (a-cell)
- **Strength** — STRONG / MODERATE / WEAK badge
- **Causality** — WHO-UMC badge (Certain / Probable / Possible / Unlikely / Unassessable)
- **Severity** — Critical / High / Medium / Low
- **Trend** — `▲ spike z=X.X` (rose, with pulsing red dot) or `↗ 0.xx` trend score

**What you'll see:**
- After seeding: a full table of 30–50 (drug, event) and (device, failure) pairs, sorted by PRR descending by default.
- Switching to `STRONG` + `SDR only` + `Sort: EB05` isolates the highest-confidence signals — typically isotretinoin → depression, simvastatin → rhabdomyolysis, warfarin → bleeding near the top.
- Filtering `product = device` shows infusion pump, insulin pump, and pacemaker signals with 🩺 icons and GMDN/IMDRF codes.

**Key things to highlight:**
- Sort by EB05 (not PRR) to rank by Bayesian-shrunk signal strength — EB05 controls false positives from sparse data.
- The SDR flag combines three independent statistical thresholds (UMC's IC025 > 0, FDA's EB05 ≥ 2, and the PRR rule) for a robust gate.
- Every badge links to a deeper panel inside the Signal Detail — the filter bar is a triage queue a real safety team would work top-down.

**Common gotcha:** The product-type dropdown, SDR/badge checkboxes, and the SMQ dropdown are applied **client-side** on the already-loaded signals list. The strength, region, and spiking filters are applied **server-side** via query parameters (`?strength=STRONG&spiking=true`). If you change both simultaneously, the result is the intersection.

**API shortcut:**
```bash
# STRONG SDR signals only, sorted by PRR desc:
curl "http://localhost:8000/api/signals?strength=STRONG&spiking=false" | python -m json.tool

# Vaccine AESI signals:
curl "http://localhost:8000/api/signals?aesi=true" | python -m json.tool

# MaxSPRT-crossed signals:
curl "http://localhost:8000/api/signals?maxsprt=true" | python -m json.tool
```

---

## 4. Signal Detail — Explainability Drawer

### Signal Detail — Explainability Drawer

**Where to find it:** Click any row on the Safety Signals page → route `/signals/:id`

**What to do (step by step):**
1. Click any signal row. The detail page loads (`GET /api/signals/{id}`).
2. Read the **header** — the drug → MedDRA PT title; the pulsing red dot if spiking.
3. Scan the **badge strip** (all inline, left to right):
   - 💊 Drug / 🩺 Device badge (sky/amber)
   - Strength badge: `STRONG` (rose), `MODERATE` (amber), `WEAK` (slate)
   - `SDR` badge (rose) if signal of disproportionate reporting
   - `WHO-UMC: Probable` / `Certain` / `Possible` causality badge
   - Severity: `Critical` (rose), `High` (orange), `Medium` (amber), `Low` (slate)
   - `🧬 PGx: HLA-B` (emerald) — gene name in badge
   - `⬛ Boxed warning` (amber) — hover for warning topics
   - `⚛ Plausible: SSRI serotonin reuptake inhibition` (cyan) — hover for MoA
   - `⚗ Class effect: HMG-CoA reductase inhibitors (statins)` (teal)
   - `◎ Stands out in class` (fuchsia)
   - `✓ Calibrated` (indigo) — survives empirical null
   - `▤ 0.72` completeness dot (lime = well-documented, slate = poor)
   - `📍 Geo cluster: Europe` (emerald) — hover for RR
   - `💉 AESI: Anaphylaxis` (pink) — vaccine AESI badge
   - `▲ Spike z=3.4` (rose)
   - `⏱ HR 2.34` (orange if elevated)
   - `🔔 MaxSPRT crossed LLR=4.21` (violet if boundary crossed) or `MaxSPRT LLR=1.23` (slate)
   - `🔐 Fed-PRR 3.1 ε=1.0` (teal if consistent, amber if diverged)
   - MedDRA SOC badge (violet)
   - `ATC C10AA` class badge (sky) for drugs; `GMDN/PC XXX` (amber) for devices
4. Read the **SMQ chip strip** (below badges) — each SMQ chip is clickable and navigates to the SMQ page filtered to that syndrome.
5. Top-right: click **⬇ E2B R3** or **⬇ E2B R2** to download the E2B XML ICSR.
6. Top-right: click **✓ Confirm** or **✕ Dismiss** to HCP-review the signal (feeds KPIs).

**Scroll through the panels in order:**

### Panel 1: AI Signal Narrative
- A plain-English paragraph synthesizing the signal's statistics.
- Source label: `deterministic` or `llm` (Ollama).
- Click **↻ Regenerate** to re-generate via local Ollama (15–60 s) or deterministic fallback.
- Below the narrative: WHO-UMC factor chips (e.g., `dechallenge cue`, `rechallenge cue`, `high-risk drug prior`, `temporal plausibility`).

### Panel 2: Safety-Scientist Copilot
- Card with indigo border: `🤖 Safety-Scientist Copilot`.
- Click **🤖 Draft Assessment** to generate a RAG-based structured pharmacovigilance memo (calls `POST /api/signals/{id}/copilot`). Takes 15–60 s with Ollama; falls back to deterministic template.
- After generation, displays:
  - **Recommendation badge**: `🔴 Escalate`, `🟡 Monitor`, or `⚪ Close`
  - **Recommendation rationale** (always visible, bold text)
  - Collapsible sections (click to expand):
    - 📋 Signal Summary
    - 📊 Statistical Evidence
    - ⚖️ Causality Assessment
    - 🧬 Clinical Context (PGx / Mechanism / Class)
    - 📜 Regulatory Context (Label / FAERS / Recalls)
    - ⚖ Benefit-Risk
  - Disclaimer text at the bottom.

### Panel 3: Disproportionality Analysis
- Six metric cards:
  - **PRR** (Proportional Reporting Ratio) with 95% CI
  - **ROR** (Reporting Odds Ratio) with 95% CI
  - **χ²** (Yates-corrected chi-square; ≥ 4 ≈ p<0.05)
  - **EB05** (MGPS EBGM 5% lower bound; ≥ 2 = FDA-style signal, shown rose)
  - **IC025** (BCPNN Information Component 2.5% lower bound; > 0 = UMC signal, shown rose)
  - **Reports** (observed co-report count; hover for expected count)
- Below cards: plain-English SDR rule explanation + WHO-UMC confidence % + factor list.

### Panel 4: Active-Comparator Analysis (when present)
- Fuchsia-bordered card: `◎ Active-comparator analysis`
- Shows vs same-class comparator (ATC class name, n comparator drugs):
  - **AC ROR** with 95% CI (fuchsia if stands out)
  - **AC PRR** with 95% CI
  - **vs all-drugs ROR** (for comparison)
  - **Comparators** count
- Explanation note: why it stands out (or attenuates) within the class.
- Comparator drug list (chips showing the other drugs in the same ATC class).

### Panel 5: Empirical Calibration & E-value
- Indigo-bordered card: `Empirical calibration & E-value`
- Four metric cards:
  - **Calibrated p** (p-value against empirical null from negative controls; significant < 0.05)
  - **Calibrated 95% CI** (ROR CI re-centred on empirical null)
  - **E-value** (minimum confounder RR needed to explain away the signal; ≥ 2 = robust, emerald)
  - **E-value (CI)** (E-value applied to the CI limit nearest the null)
- Footer: empirical null parameters (null μ, null σ, n controls).

### Panel 6: Report Completeness (vigiGrade-style)
- Lime-bordered card: `▤ Report completeness (vigiGrade-style)`
- Mean completeness bar (0.0–1.0) with a dashed marker at 0.5 (well-documented threshold).
- Grade label (e.g., `A`, `B`, `C`).
- Best-documented and worst-documented supporting post summaries.
- Checklist of 11 dimensions with per-dimension coverage bars:
  - Drug + event identifiable
  - Indication / condition
  - Time-to-onset cue
  - Outcome / seriousness
  - Dechallenge cue
  - Rechallenge cue
  - Patient descriptors (age/sex)
  - Dose / regimen
  - Sufficient free text
  - Country known
  - Sentiment / severity signal

### Panel 7: Time-to-Event (Cox PH Surrogate)
- Orange-bordered (if HR elevated) or slate card: `⏱ Time-to-event (HR) — Cox PH surrogate`
- Four metric cards: **Hazard Ratio (HR)**, **95% CI**, **Wald p**, **Log-rank p**
- Sample sizes: exposed (signal posts), unexposed (other-drug AE posts).
- Amber disclaimer: illustrative surrogate, not a clinical HR.

### Panel 8: MaxSPRT Sequential Surveillance (when present)
- Violet-bordered card: `🔔 MaxSPRT sequential surveillance`
- Four metric cards: **Max LLR**, **Critical boundary**, **Looks (buckets)**, **Crossed at look**
- LLR-over-looks mini bar chart with dashed boundary line (violet bars above boundary).
- Plain-language interpretation box (violet if crossed, slate if not).
- Alpha and method note.

### Panel 9: Pharmacogenomic Risk (when present)
- Emerald-bordered card: `🧬 Pharmacogenomic risk (PGx)`
- Three info boxes: **Gene** (large), **Risk allele** (monospace), **At-risk phenotype**
- CPIC guidance box: full recommendation text.
- Footer: `Genomically explainable · CPIC Level A · CPIC / PharmGKB`

### Panel 10: FDA Boxed (Black-Box) Warning (when present)
- Amber-bordered card: `⬛ FDA boxed (black-box) warning`
- Boxed warning topics list (bullet points, amber text).
- Badge: `Covers this event` (amber) or `Different event` (sky).
- Footer: novelty classification (`Known-serious (already boxed)` or `Boxed drug — different event`).

### Panel 11: Mechanistic Plausibility (when present)
- Cyan-bordered card: `⚛ Mechanistic plausibility`
- Target / MoA box and explanation box.
- Confidence badge (e.g., `high confidence`).
- Footer: `Biologically plausible · Bradford Hill`

### Panel 12: Class Effect & Chemical Read-Across (when present)
- Teal-bordered card: `⚗ Class effect & chemical read-across`
- ATC class name → event; four metric cards: Class EB05, Class IC025, Class PRR, Pooled reports.
- Member drugs chip list (the current drug highlighted in teal, others in slate).
- Read-across section: structural analogs also reporting the same event, each with Tanimoto similarity score.

### Panel 13: Vaccine Safety — AESI / Brighton / SCRI (when present)
- Pink-bordered card: `💉 Vaccine safety (AESI / Brighton / SCRI)`
- Three info boxes: Vaccine name + platform, AESI name + SOC, Brighton level badge.
- Brighton rationale text box.
- SCRI table: Relative incidence, 95% CI, Risk window (n / days), Control window (n / days).

### Panel 14: Geographic Clustering (when present)
- Emerald-bordered card: `📍 Geographic clustering`
- Hotspot name, level (country/region).
- Four metric cards: **Observed**, **Expected**, **Relative risk (RR)**, **LLR (scan)**
- Per-area RR bar chart (top 8 areas, hotspot highlighted in emerald).

### Panel 15: Reporting Trend Chart
- Bar chart: daily supporting-report volume. Bars are rose-colored if spiking, sky-blue otherwise.
- X-axis: MM-DD date; Y-axis: report count.

### Panel 16: External Evidence
- Four sections in a right-side card:
  - **openFDA FAERS** (drugs) or **MAUDE** (devices): report count + confidence boost %.
  - **FDA device classification** (devices only, live): product code, class (I/II/III), 21 CFR, specialty.
  - **DailyMed label** (drugs): clickable link to the FDA-approved SPL.
  - **FDA recalls / enforcement**: count, classification (Class I/II/III), date, reason snippet.
  - **Literature (PubMed)**: article count + clickable top article link.

### Panel 17: Source Traceability
- List of supporting posts, each showing:
  - Platform + date + country (emerald text)
  - Translated-from badge, PII-scrubbed badge, sentiment badge, AE confidence badge
  - Post text with **color-highlighted entities**: drugs (sky), symptoms (rose), conditions (amber). Patient vernacular terms have a dotted underline with a superscript `🗣→MedDRA PT` mapping.
  - Original-language text (if translated).
  - **4-gate AE decision trace** (each gate: ✓ emerald or ✕ rose):
    - Gate 1: Drug present
    - Gate 2: Symptom present
    - Gate 3: Negative sentiment
    - Gate 4: Non-negated symptom

**Key things to highlight:**
- Every layer is independent evidence — stats, causality, mechanism, class, geography, sequential test, external corroboration — and when they all agree it is especially compelling.
- The 4-gate trace is fully auditable: every AE classification decision can be inspected post hoc.
- E2B R3 and R2 downloads provide regulator-ready ICSRs with real MedDRA PT/SOC and WHO-UMC fields.
- The Copilot memo is grounded exclusively in the signal's own computed data — it cannot hallucinate facts not in the signal.

**Common gotcha:** External evidence (DailyMed, PubMed, recalls, device classification) loads **lazily on first view** if not pre-warmed. The first open of a signal may take 5–10 extra seconds while it fetches and caches. Pre-warm the hero signals before demoing: click each once and wait for evidence to appear.

**API shortcut:**
```bash
# Fetch full signal detail (includes trend series + supporting posts):
curl http://localhost:8000/api/signals/1 | python -m json.tool

# Download E2B R3 XML:
curl -o e2b_r3_1.xml http://localhost:8000/api/signals/1/e2b

# Download E2B R2 XML:
curl -o e2b_r2_1.xml http://localhost:8000/api/signals/1/e2b-r2

# Confirm a signal as reviewed:
curl -X POST "http://localhost:8000/api/signals/1/review?state=confirmed&by=analyst"

# Draft Copilot assessment:
curl -X POST http://localhost:8000/api/signals/1/copilot | python -m json.tool
```

---

## 5. SMQ Syndromes Page

### SMQ Syndromes Page

**Where to find it:** Sidebar nav label **SMQ Syndromes** (◈ icon) · route `/smq`

**What to do (step by step):**
1. Click **SMQ Syndromes** in the sidebar. The page calls `GET /api/smq`.
2. Read the page header explanation: "Standardised MedDRA Query grouping pools related Preferred Terms into clinical syndromes (DILI, SCAR, rhabdomyolysis, haemorrhage…)."
3. Scan the grid of syndrome cards (2-column on large screens). Each card shows:
   - SMQ name (e.g., `◈ Drug-induced liver injury (DILI)`)
   - Number of SDR signals as a badge (`3 SDR` in rose) or `watch` badge
   - SOC label and total pooled member-PT reports
   - Table of drugs in that syndrome, sorted by EB05: Drug name (with member PTs below it), EB05, IC025, PRR, Reports, SDR badge
4. Click a drug row to navigate to `/signals?smq={smq_code}` — the Signals page pre-filtered to that syndrome.
5. Scroll through all syndrome cards to see which drugs appear in multiple syndromes.

**What you'll see:**
- 3–8 syndrome groups depending on the corpus: typically DILI, SCAR (severe cutaneous adverse reactions), Rhabdomyolysis, Haemorrhage, Anaphylaxis/hypersensitivity, Cardiac disorders.
- Each group has 2–6 contributing drugs.
- EB05 and IC025 are **group-level** (pooled across all member PTs), so a drug that is weak on any single preferred term can still surface as an SDR at the syndrome level.

**Key things to highlight:**
- SMQ aggregation catches dispersed signals — a drug reporting a little rash here, a little skin blistering there, and some mouth ulcers might not trigger individual PT-level SDRs, but pools into a SCAR-level signal.
- The EB05/IC025 thresholds are the same as on individual signals; the math is identical but the denominator pools across member terms.
- Clicking a drug row drills straight to the individual signals for that syndrome.

**Common gotcha:** SMQ grouping uses an **open MedDRA-style surrogate** (not the licensed MedDRA terminology). The syndrome definitions are faithful to real SMQs but may not exactly match a licensed MedDRA installation.

**API shortcut:**
```bash
curl http://localhost:8000/api/smq | python -m json.tool
```

---

## 6. Class Effects Page

### Class Effects Page

**Where to find it:** Sidebar nav label **Class Effects** (⚗ icon) · route `/class-effects`

**What to do (step by step):**
1. Click **Class Effects** in the sidebar. The page calls `GET /api/class-effect`.
2. The page lists ATC pharmacological subgroup groups. Each group shows:
   - ATC class key (e.g., `C10AA`) and class name (e.g., `HMG-CoA reductase inhibitors (statins)`)
   - Event (e.g., `myalgia`)
   - Class EB05, Class IC025, Class PRR, Total pooled reports
   - Member drugs contributing to this class-level signal (chip list)
   - `Class-level SDR` badge (rose) if class signal crosses thresholds
3. A class group is marked as a class effect when **2 or more drugs in the same ATC class** independently report the same event.
4. Click a group row to navigate to the individual signals for those drugs.

**What you'll see:**
- Statin class → myalgia (simvastatin, atorvastatin, pravastatin)
- SSRI class → nausea / dizziness (paroxetine, fluoxetine, sertraline)
- Anticoagulant class → bleeding (warfarin, acenocoumarol)
- Each group shows the aggregated disproportionality metrics for the whole class.

**Key things to highlight:**
- A class-level signal where a SINGLE drug shows a weak individual signal but the whole class shows a strong class-level SDR is a powerful finding — it suggests the pharmacological class, not the specific molecule, is responsible.
- Read-across structural analogs (Tanimoto-style similarity) are shown inside the individual Signal Detail — the Class Effects page shows the ATC-level roll-up.
- The `class_effect` flag is stored per signal in the `Signal.class_effect` boolean field; the Class Effects page is the aggregated view.

**Common gotcha:** Only drugs with an assigned ATC code (`Signal.drug_atc`) are included in class-effect grouping. If an ATC code cannot be resolved for a drug, it won't appear in any class group.

**API shortcut:**
```bash
curl http://localhost:8000/api/class-effect | python -m json.tool
```

---

## 7. Vaccine Safety Page

### Vaccine Safety Page

**Where to find it:** Sidebar nav label **Vaccine Safety** (💉 icon) · route `/vaccine`

**What to do (step by step):**
1. Click **Vaccine Safety** in the sidebar. Calls `GET /api/vaccine`.
2. Read the four summary stat cards: **Vaccine signals**, **AESI matched**, **Registered vaccines**, **AESI defined**.
3. Scroll through the **AESI signal groups** (2-column grid). Each card title is the AESI name (e.g., `💉 Anaphylaxis/Severe allergic reaction`).
   - Card header: AESI name, SOC, n vaccines, total reports, Brighton level badge (L1 = rose, L2 = amber, L3 = slate)
   - Table: Vaccine → event, Brighton level, SCRI RI (relative incidence with 95% CI), Reports, SDR badge
   - Click any row to open the signal detail for that vaccine–AESI pair
4. Scroll to **AESI reference** section — cards for each monitored AESI with its SOC, description, and narrow Preferred Terms (first 4 shown).
5. Scroll to **Vaccine registry** — chips for each registered vaccine with platform (mRNA, adjuvanted, inactivated, live-attenuated, viral vector, subunit, etc.).

**What you'll see:**
- 3–6 AESI groups depending on which vaccine signals are in the demo corpus.
- Brighton levels: Level 1 (highest diagnostic certainty, rose) through Level 3+ (lower certainty, slate).
- SCRI relative incidence (RI): a ratio of AE events in the risk window vs control window. RI > 1 with CI lower bound > 1 shown in rose.
- AESI examples: Anaphylaxis, Myocarditis/Pericarditis, ADEM, TTS (Thrombosis with Thrombocytopenia Syndrome), Febrile seizures, GBS, Bell's palsy.

**Key things to highlight:**
- Vaccine pharmacovigilance is a distinct discipline from drug PV — healthy people receive vaccines, so even rare AESIs at population scale matter.
- Brighton levels provide a clinical diagnostic certainty gradient — Level 1 means the case definition is definitively met.
- SCRI is a **self-controlled design** that uses each patient as their own control, eliminating stable confounders. The social-listening surrogate anchors the risk window at the earliest reported AE onset.
- All Brighton levels and SCRI estimates are clearly labeled as **social-listening surrogates** — no true per-patient vaccination dates exist in social data.

**Common gotcha:** If no vaccine signals appear, check that the demo corpus was loaded — the synthetic corpus includes vaccine-related posts (mRNA, flu vaccine, etc.) that generate is_vaccine signals. The filter `is_vaccine=True` on the `/api/signals` endpoint narrows to only vaccine products.

**API shortcut:**
```bash
# Vaccine AESI summary:
curl http://localhost:8000/api/vaccine | python -m json.tool

# Vaccine signals from the signals endpoint:
curl "http://localhost:8000/api/signals?vaccine=true&aesi=true" | python -m json.tool
```

---

## 8. Geo Clusters Page

### Geo Clusters Page

**Where to find it:** Sidebar nav label **Geo Clusters** (📍 icon) · route `/spatial`

**What to do (step by step):**
1. Click **Geo Clusters** in the sidebar. Calls `GET /api/spatial`.
2. Read the page description: "Kulldorff-style Poisson scan statistic tests whether a signal's reports concentrate in a country or region beyond the expected share."
3. Scan the cluster cards (2-column grid). Each card shows:
   - Drug → event name + hotspot (e.g., `Europe` or `United States`)
   - Level: `country` or `region`
   - RR badge (e.g., `RR 3.2×`)
   - Four metric boxes: **Observed** (emerald), **Expected**, **RR** (emerald if ≥ 2), **LLR** (emerald if ≥ 3.84)
   - Per-area RR bar chart for top 6 areas — hotspot highlighted in emerald, others in slate
4. Click **View geo-cluster signals →** inside any card to navigate to the Signals page filtered to spatial cluster signals.
5. Read the caveat at the bottom: geolocation is coarse (country/region), clusters are hypotheses for follow-up, not confirmed defects.

**What you'll see:**
- 3–8 geographic clusters depending on the corpus.
- Hotspots like `Europe`, `North America`, `Asia`, or specific countries.
- RR (relative risk) typically 1.5–5× for detected clusters; LLR ≥ 3.84 marks statistical significance.
- Signals like isotretinoin in Europe or simvastatin in North America may show geographic concentration.

**Key things to highlight:**
- A geographic cluster with a high RR and LLR is an early indicator of a regional batch issue, a counterfeit product in a market, or a regional prescribing/reporting pattern.
- The Kulldorff-style Poisson scan uses the corpus-wide geographic AE distribution as the baseline, not population denominators — a signal that accounts for 3× its expected share of North American AE reports is flagged.
- Each cluster badge appears in the Signal Detail for that signal — the Geo Clusters page is the corpus-wide view across all clustered signals.

**Common gotcha:** Geographic attribution in social posts is coarse. A Reddit post tagged to `North America` means the user's IP geolocation suggested North America, not a confirmed patient location. Treat clusters as hypotheses, not confirmations.

**API shortcut:**
```bash
curl http://localhost:8000/api/spatial | python -m json.tool
```

---

## 9. Federated / DP Page

### Federated / Privacy-Preserving Analytics Page

**Where to find it:** Sidebar nav label **Federated / DP** (🔐 icon) · route `/federated`

**What to do (step by step):**
1. Click **Federated / DP** in the sidebar. Calls `GET /api/federated`.
2. Read the amber disclaimer banner: "Federated simulation over local corpus partitions — not a real multi-institution deployment."
3. Read the four **summary stat cards**:
   - **Federated Sites (K)**: 3 (North America · Europe · Asia)
   - **DP Epsilon (ε)**: 1.0 (Mechanism: Laplace)
   - **Privacy Releases**: n releases, Total ε consumed
   - **Total AE Reports** and total federated signal pairs
4. Read the **Privacy Budget** panel: Total ε consumed, Total δ, Releases, Composition (sequential).
5. Read the **Per-Site Breakdown** table: Site name, AE Reports, Signal Pairs, DP ε per site, Noise Scale b.
6. Read the **Top Signals by Federated PRR** table:
   - Drug | Event | Fed PRR | Pooled PRR | Fed Count | Pooled Count | Consistency | Signal link
   - Consistency: `✓ Consistent` (emerald) or `⚠ Diverged` (amber)
   - Click `View` in Signal column to go to the signal detail.
7. Read the technical note at the bottom (Haldane-Anscombe correction, consistency definition, noise scale formula).

**What you'll see:**
- 3 sites partitioned by region, each with their share of AE reports.
- Fed PRR values close to (but not identical to) Pooled PRR — the Laplace noise adds controlled randomness.
- Most strong signals show `✓ Consistent` (federated and pooled estimates agree on direction PRR > 1); some weaker signals may `⚠ Diverge`.
- The Signal Detail page for any federated signal shows a `🔐 Fed-PRR 3.1 ε=1.0` chip (teal if consistent, amber if diverged).

**Key things to highlight:**
- Laplace mechanism (ε=1.0, sensitivity=1): each count perturbed by `Laplace(0, 1/ε)` — the math is in `analytics/dp.py` with zero external DP libraries.
- Sequential composition: 3 releases × ε=1.0 = total ε=3.0 worst case.
- The federated PRR uses Haldane–Anscombe +0.5 correction on all 2×2 cells computed from the noisy aggregated counts — same rigor as the main disproportionality.
- This demonstrates a real regulatory concern: how to share pharmacovigilance data across institutions (hospital networks, country regulators) without exposing individual-level records.

**Common gotcha:** This is a **simulation** over the local corpus partitioned by region, not a real multi-site deployment. The disclaimer is intentional and should be stated when presenting.

**API shortcut:**
```bash
curl http://localhost:8000/api/federated | python -m json.tool
```

---

## 10. Knowledge Graph

### Knowledge Graph

**Where to find it:** Sidebar nav label **Knowledge Graph** (⬡ icon) · route `/graph`

**What to do (step by step):**
1. Click **Knowledge Graph**. The page calls `GET /api/knowledge-graph`.
2. Read the four **stat cards**: Nodes (total), Relationships (total), and the **Hub entities** chip list (most connected entities ranked by degree centrality).
3. The large `Drug–Symptom–Condition Knowledge Graph` force-directed graph renders below:
   - **Node colors**: drugs = sky blue (#38bdf8), symptoms = rose (#f43f5e), conditions = amber (#f59e0b)
   - **Node size**: scales with degree (more connections = larger node)
   - **Edge color**: severity (`Critical` = rose, `High` = orange, `Medium` = amber, `Low` = slate) for adverse edges; dark slate for indication edges
   - **Edge width**: proportional to report count
   - **Animated particles** flow along adverse edges (drug → symptom direction)
4. Hover over a node to see its label and type tooltip.
5. Drag nodes to rearrange; scroll to zoom in/out. The graph uses a WebGL canvas (ForceGraph2D).
6. Read the hub entities chips — these are the most "connected" drugs or reactions in the corpus.

**What you'll see:**
- 50–100+ nodes and 100–200+ edges depending on the corpus.
- Hub drugs: isotretinoin, simvastatin, warfarin, clopidogrel will have many connections (many symptom/condition relationships).
- Hub symptoms: depression, myalgia, bleeding will be large rose nodes at the center.
- Conditions (amber): acne, hyperlipidemia, epilepsy appear as peripheral amber nodes connected to their associated drugs.
- The DNA background is automatically **disabled** on this page (two WebGL contexts would compete) and shows a static veil instead.

**Key things to highlight:**
- Shared-symptom clusters are visually obvious — if three different drugs all connect to the same large symptom node, that symptom is a class-wide concern.
- Degree centrality hubs identify the drugs and reactions with the most systemic safety relevance in the current corpus.
- Adverse edges (drug→symptom) carry particles; indication edges (drug↔condition) are dark and static — the directional flow makes adverse relationships visually distinct.

**Common gotcha:** The Knowledge Graph uses a WebGL canvas. On slow hardware, the force simulation may take 5–10 seconds to stabilize. Avoid switching quickly between the Knowledge Graph and other heavy pages. The 3D DNA background is deliberately disabled here to avoid competing WebGL contexts.

**API shortcut:**
```bash
curl http://localhost:8000/api/knowledge-graph | python -m json.tool
```

---

## 11. KPIs & SPC

### KPIs & SPC Page

**Where to find it:** Sidebar nav label **KPIs & SPC** (📈 icon) · route `/kpis`

**What to do (step by step):**
1. Click **KPIs & SPC**. Calls `GET /api/kpis` and `GET /api/audit?limit=50`.
2. Read the **first row of KPI stat cards**:
   - **Time to detection**: mean days (min / max / n). This is `detected_at − earliest_post_at` per signal.
   - **Actionable rate**: confirmed signals ÷ reviewed signals (%)
   - **False-positive ratio**: dismissed signals ÷ reviewed signals (%)
   - **SDR signals**: count of SDR-flagged signals, with total signal count and STRONG count
3. Read the **review funnel** row: Confirmed (HCP), Dismissed (HCP), Unreviewed — three stat cards side by side.
4. Read the **report completeness** row:
   - **Avg report completeness**: mean vigiGrade-style score (0–1)
   - **Well-documented signals**: count where completeness ≥ 0.5
   - **Well-documented rate**: percentage
5. Read the **SPC control chart**: a Shewhart line chart of daily alert frequency over time.
   - Central line (x̄, slate dashed): mean daily alerts
   - **UCL** (upper control limit, rose dashed): mean + 3σ
   - LCL (lower control limit, dark dashed): mean − 3σ (or 0)
   - Points above UCL are **out-of-control** (emerging surge) — these would be investigation triggers.
   - The chart legend shows: `Alerts/day` (sky line), UCL (rose), x̄ (slate)
6. Scroll to the **Audit trail** table (last 50 entries by default):
   - Columns: Time, Actor, Action (badge), Detail
   - Actions include: `signal_detected`, `signal_reviewed`, `alert_ack`
   - The detail column shows e.g. `isotretinoin -> depression marked confirmed`

**What you'll see after demo seed + a few reviews:**
- Time to detection: ~2–8 days mean (back-dated detection timestamps + earliest supporting post)
- Actionable rate: ~60–80% (a few signals are pre-reviewed as confirmed in the demo prepare step)
- SPC chart: a line with some daily variation, possibly 1–2 points above UCL showing an emerging surge.
- Audit trail: 5–15 entries from the demo prepare step showing pre-reviewed signals.

**Key things to highlight:**
- Time-to-detection is the core pharmacovigilance KPI — conventional spontaneous reporting takes weeks; social listening can detect in days.
- Actionable rate and false-positive ratio together define the triage efficiency of the system.
- The Shewhart SPC chart is standard industrial quality control applied to pharmacovigilance — a point above UCL means "something unusual is happening today, investigate."
- The audit trail is append-only and feeds regulatory compliance — every HCP review action is logged with actor, action, and detail.

**Common gotcha:** The SPC chart requires multiple daily buckets to show meaningful control limits. Right after seeding, the back-dated timestamps create a good distribution. If you Reset and re-seed, the chart repopulates. If you have fewer than 3 daily buckets, a note says "Control limits become meaningful as the background scheduler runs over time."

**API shortcut:**
```bash
curl http://localhost:8000/api/kpis | python -m json.tool
curl "http://localhost:8000/api/audit?limit=100" | python -m json.tool
```

---

## 12. Alerts

### Alerts Page

**Where to find it:** Sidebar nav label **Alerts** (🔔 icon) · route `/alerts`

**What to do (step by step):**
1. Click **Alerts**. Calls `GET /api/alerts`.
2. Read the header description: "Alerts fire automatically for high-severity, spiking, or strong-disproportionality signals."
3. Scan the alert list (newest first):
   - **Severity dot** on the left: pulsing rose = Critical, solid orange = High, solid amber = Medium
   - **Alert message**: e.g., "isotretinoin → depression: STRONG SDR, severity Critical" 
   - **Timestamp** in slate
   - Severity badge on the right
   - **Acknowledge** button (ghost, right side) — click to mute the alert
4. Click any alert card body (not the Acknowledge button) to navigate to the Signal Detail for that signal.
5. Acknowledged alerts turn semi-transparent (opacity 50%).

**What you'll see after demo seed:**
- 10–20 alerts for the top signals: Critical severity for isotretinoin→depression, simvastatin→rhabdomyolysis, warfarin→bleeding, and any device signals; High for moderate-severity signals; spiking signals also fire alerts.

**Key things to highlight:**
- Alerts are automatic — they fire during signal recompute when a signal is Critical/High severity, is spiking, is an SDR, or is STRONG disproportionality.
- One-click navigation from alert → signal detail eliminates triage overhead.
- The Acknowledge action is logged in the audit trail.

**Common gotcha:** If Alerts shows "No alerts yet", load the demo corpus — the seed + recompute step auto-generates alerts for qualifying signals. Clicking Reset clears all alerts.

**API shortcut:**
```bash
curl http://localhost:8000/api/alerts | python -m json.tool
# Acknowledge alert #1:
curl -X POST http://localhost:8000/api/alerts/1/ack
```

---

## 13. Live Feed + Streaming Controls

### Live Feed + Streaming Controls

**Where to find it:** Sidebar nav label **Live Feed** (≋ icon) · route `/feed`

**What to do (step by step):**

#### Part A: Autonomous Monitoring Worker
1. Click **Live Feed**.
2. See the **Autonomous monitoring worker** card (sky border) at the top.
3. Status badge: `● running` (emerald) or `○ stopped` (slate).
4. Click **▶ Start worker** — calls `POST /api/stream/start?interval=15&mode=stream`.
5. Once running, the card shows:
   - `interval: 15s` — ingests a new synthetic batch every 15 seconds
   - `mode: stream` — uses the simulated stream (vs `reddit` for live RSS)
   - `ticks: N` — how many batches have processed
   - `last: HH:MM:SS (+N)` — last run time + how many new posts
6. Click **■ Stop worker** to halt.

#### Part B: Real Streaming Ingestion Control
1. Below the worker card, see the **Real streaming ingestion** card (emerald border).
2. Click **▶ Start live stream** — calls `POST /api/stream/start?interval=15&mode=stream`.
3. Once running, the badge shows: `● streaming · session XXXXXXXX` (session_id, first 8 chars).
4. Below the button:
   - `batches: N` — batches processed this session
   - `posts ingested: N` — total posts ingested this session
   - `started: HH:MM:SS` — session start time
   - `latest batch: HH:MM:SS` — most recent batch timestamp
5. The feed below automatically refreshes every 5 seconds while streaming.
6. Click **■ Stop live stream** to halt.

#### Part C: Post Feed
1. Below the streaming controls, see the **Adverse events only** checkbox (rose accent).
2. Check it to filter to only AE-flagged posts.
3. Each post card shows:
   - Platform + timestamp (top-left)
   - `ADVERSE EVENT` (rose) or `no AE` (slate) badge + sentiment badge
   - Post text
   - Entity chips below: 💊 drug names (sky), ⚕ symptoms (rose)

**What you'll see:**
- With the worker or stream running: new posts appear at the top every 15 seconds.
- Each post shows the raw (but PII-scrubbed) text with extracted entities highlighted.
- The Overview dashboard stat cards update automatically as new posts and signals accumulate.

**Key things to highlight:**
- The autonomous monitoring worker is a **server-side daemon thread** — it continues running even if the browser tab is closed. This is genuine autonomous surveillance.
- The stream mode (`stream`) uses the simulated synthetic stream. Use `reddit` mode with internet to pull real Reddit posts in the worker.
- `POST /api/stream/tick?n=4` (the top-bar **▶ Stream batch** button) is a one-shot batch; the worker automates this on an interval.

**Common gotcha:** Both the "Autonomous monitoring worker" card and the "Real streaming ingestion" card wire to the same underlying `scheduler` object — starting one while the other is running will simply restart it. Stop first, then start with the desired mode.

**API shortcut:**
```bash
# Start worker (stream mode, 15s interval):
curl -X POST "http://localhost:8000/api/stream/start?interval=15&mode=stream"

# Check status:
curl http://localhost:8000/api/stream/status | python -m json.tool

# Stop:
curl -X POST http://localhost:8000/api/stream/stop

# Manual one-shot batch of 4 posts:
curl -X POST "http://localhost:8000/api/stream/tick?n=4"
```

---

## 14. Data Forge

### Data Forge

**Where to find it:** Sidebar nav label **Data Forge** (⚗ icon) · route `/forge` **(requires sign-in)**

**What to do (step by step):**
1. Sign in first (`admin@vigilai.dev / admin123`) — an unsigned-in user sees a "Sign in to generate" card.
2. Click **Data Forge** in the sidebar.
3. Fill out the **generation form** (6 fields):
   - **Drug**: text input — e.g., `isotretinoin` (default)
   - **Condition**: text input — e.g., `acne` (default)
   - **Platform**: dropdown — `reddit`, `twitter`, or `forum`
   - **Region**: dropdown — `Global`, `North America`, `Europe`, `Asia`, `South America`, `Africa`, `Oceania`
   - **Records**: number input (1–10)
   - **⚗ Generate** button
4. Click **⚗ Generate** — calls `POST /api/forge/generate`. The button shows `Forging…` while running (1–30 s depending on Ollama availability).
5. Read the **summary cards** after generation:
   - **Generated**: total records produced
   - **Export-ready**: records that passed quality threshold
   - **Avg quality**: mean quality score (0–100, green ≥ 85, amber ≥ 70, rose < 70)
   - **Engine**: `Ollama LLM` or `Deterministic`
6. Use the **⬇ Export JSONL** and **⬇ Export CSV** buttons to download the generated dataset.
7. Read the **individual record cards** (one per generated post):
   - Top row: platform badge, region · age · gender · emotion scenario, `repaired` badge (amber, if one repair cycle ran), engine badge
   - Quality score (top-right, color-coded)
   - ✓ ready (emerald) if export-ready
   - Post text
   - Per-axis score breakdown: `medical N`, `realism N`, `hallucination N`, `PII N` (scale 0–100)

**What you'll see:**
- With Ollama running: LLM-generated realistic patient posts (e.g., a Reddit-style post about isotretinoin and depression from a 19-year-old female in North America).
- Without Ollama: deterministic template-based posts (still valid for testing, clearly labeled `deterministic`).
- Quality scores: medical (clinical coherence), realism (social-media tone), hallucination (absence of meta-phrases like "As an AI..."), PII (no PII leaked past scrubbing).
- `repaired` badge: means the first generation scored below threshold and a repair cycle was attempted.

**Key things to highlight:**
- The agentic loop: `scenario → generate → judge → repair → re-score` — a real judge-and-repair pattern without a human in the loop.
- Fully offline — uses local Ollama; falls back to deterministic templates so the demo always works.
- Export as JSONL/CSV for downstream NLP training or pipeline testing **without ever touching real patient data**.

**Common gotcha:** Forge output is **never automatically ingested into the live signal store** — it's clearly fictional data for testing/training. If you want to test how Forge-generated posts flow through the pipeline, you would need to manually ingest them via the API.

**API shortcut:**
```bash
# Generate 3 records (requires auth token):
curl -X POST http://localhost:8000/api/forge/generate \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"drug":"isotretinoin","condition":"acne","platform":"reddit","region":"North America","records":3}'

# Export as JSONL:
curl -o batch.jsonl http://localhost:8000/api/forge/export/BATCH_ID/jsonl
```

---

## 15. Forum Onboarding

### Forum Onboarding

**Where to find it:** Sidebar nav label **Forum Onboarding** (🌐 icon) · route `/onboarding` **(requires sign-in)**

**What to do (step by step):**
1. Sign in first — an unsigned-in user sees a "Sign in" prompt.
2. Click **Forum Onboarding**.
3. Read the subtitle: "Point VigilAI at any patient forum URL; it analyzes the page and proposes an extraction config."
4. The URL input is pre-filled with `https://www.reddit.com/r/AskDocs/`. Try that, or paste any patient forum URL (e.g., `https://www.patient.info/forums/`, `https://forum.drugs.com/`).
5. Click **🌐 Onboard** — calls `POST /api/agentic/onboard-forum`. Shows `Analyzing…` while running.
6. Read the **Proposed extraction config** card (left):
   - **Method**: `firecrawl`, `direct`, or `heuristic`
   - **Forum type**: `wordpress`, `discourse`, `phpbb`, `reddit`, `generic`
   - **Post selector**: CSS selector string (monospace)
   - **Title selector**: CSS selector string (monospace)
   - **Date selector**: CSS selector string (monospace)
   - **Content selector**: CSS selector string (monospace)
   - **Posts/page (est.)**: estimated posts per page
   - **Confidence**: percentage badge (sky)
   - **LLM refined**: `yes` if Ollama refined the config
7. Read the **Sample extracted posts** card (right): up to 3 sample post text snippets (PII already scrubbed).

**What you'll see:**
- For Reddit: method=`direct`, forum_type=`reddit`, confidence ~70–90%, post selectors targeting Reddit's post structure.
- For a WordPress forum: selectors targeting `.post-content`, `.entry-title`, etc.
- For a JS-rendered forum: "No samples extracted (page may be JS-rendered)" — honest about limitations.
- Sample posts are the raw scraped content with PII scrubbed before display.

**Key things to highlight:**
- The resolution order is: Firecrawl (if key configured) → direct HTTP + HTML-heuristic selector analysis (no key needed) → optional Ollama LLM refinement → deterministic template fallback.
- This can onboard any new patient forum **without hand-writing a scraper** — the analyst just pastes the URL.
- Honestly reports low confidence rather than inventing selectors for JS-rendered pages.

**Common gotcha:** Many patient forums are JS-rendered (Angular, Vue, React). For these, heuristics find no samples and confidence is low. The honest low-confidence response is correct behavior, not a bug.

**API shortcut:**
```bash
curl -X POST http://localhost:8000/api/agentic/onboard-forum \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.reddit.com/r/AskDocs/"}'
```

---

## 16. Surveillance Net

### Surveillance Net

**Where to find it:** Sidebar nav label **Surveillance Net** (🛰 icon) · route `/surveillance`

**What to do (step by step):**
1. Click **Surveillance Net**. Calls `GET /api/surveillance/sources`.
2. Read the **four summary stat cards**: Networks modeled, Live connectors, Connectors, Surrogate/reference.
3. Read the header note (italic text under the title).
4. Read the **Live connectors** grid — each card has:
   - Source name
   - Type badge: `connector` (emerald) or `surrogate` (slate)
   - Region, modality, product badges
   - `live · no key` (emerald) or `live · key` (amber) status badge
   - API endpoint URL (monospace, truncated)
   - Descriptive note
5. Real live connectors (no key needed): openFDA FAERS, openFDA MAUDE, FDA drug labels, DailyMed SPL, FDA drug recalls, FDA device recalls, FDA device classification, PubMed (NCBI E-utilities), RxNorm/RxNav — ~9 sources.
6. Read the **Surrogate / reference networks** grid — licensed or distributed-infrastructure systems that are NOT ingested but modeled for architecture fidelity (WHO VigiBase/VigiLyze, FDA Sentinel, NESTcc, BEST, CDC VSD, CNODES, CAEFISS, MHRA Yellow Card, ASPREN, MID-NET, China ADR, etc.).
   - Each surrogate card clearly says `surrogate` type (slate badge) and has an honest `note` explaining it's modeled, not ingested.
7. Scroll to **VigiLyze-style exploration** — a drill-down table over VigilAI's **own** signal store (not VigiBase itself):
   - Filters: Product type, Region (from signal data), SOC (from signal data), free-text search
   - Table: Product → Event, Type, PRR, EB05, IC025, N, SDR badge
   - Sorted by EB05 descending
   - Click any row to open Signal Detail

**What you'll see:**
- ~30 total networks modeled (9 live connectors + 21 surrogates).
- The VigiLyze-style explorer shows the same signals as the Safety Signals page but in an explorer interface without the dense badge strip — good for MedDRA SOC drill-down.

**Key things to highlight:**
- "9 live keyless connectors do real corroboration; the licensed global networks are modeled for architecture fidelity and clearly labeled as surrogates."
- The VigiLyze-style explorer emulates the UMC VigiLyze interface over VigilAI's own data — we say so plainly.
- This is the honest way to represent global coverage: real where possible, surrogate where data is licensed/closed.

**Common gotcha:** The surrogate network cards intentionally lack live query results — they represent the architecture, not a live connection. If a judge asks "can you query VigiBase?", the honest answer is: "VigiBase/VigiLyze is licensed and not openly ingestible; we emulate the exploration interface over our own signals and label the licensed sources as surrogates."

**API shortcut:**
```bash
curl http://localhost:8000/api/surveillance/sources | python -m json.tool
```

---

## 17. Sources

### Sources Page

**Where to find it:** Sidebar nav label **Sources** (⛓ icon) · route `/sources`

**What to do (step by step):**
1. Click **Sources**. Calls `GET /api/sources` and `GET /api/llm/status`.
2. Read the **Worldwide data sources** grid (2-column). Each card:
   - Source name
   - Status badge: `live` (emerald) or `optional` / `key required` (amber)
   - Note: description of what the source provides
   - Type badge, scope badge, `no key` or `key required` badge
3. Read the **FHIR / HL7 Ingestion** card:
   - Card subtitle: "Paste a FHIR R4 Bundle or single AdverseEvent / MedicationStatement resource (JSON)."
   - **Load sample bundle** button: fills the textarea with a sample FHIR bundle (2 AdverseEvent resources: simvastatin→rhabdomyolysis and lisinopril→angioedema)
   - **Clear** button: resets the textarea
   - **JSON textarea**: paste any FHIR R4 Bundle or resource here
   - **Ingest FHIR Bundle** button (teal): calls `POST /api/ingest/fhir`
   - Result cards: **Parsed** (n resources found), **Ingested (new)** (emerald if > 0), **Signals** (updated signal count), **Alerts** (new alerts fired)
4. Read the **AI engine status** card:
   - LLM enabled: `yes` / `no`
   - Ollama: `online` (emerald) / `offline`
   - Model: Ollama model name (e.g., `llama3.2`, `mistral`)
   - OpenRouter: `configured` / `not set`

**To use the FHIR ingest panel:**
1. Click **Load sample bundle** — the textarea fills with a JSON bundle containing 2 AdverseEvent resources.
2. Optionally edit the bundle (change drug/symptom/location).
3. Click **Ingest FHIR Bundle**.
4. Read the result: "Ingestion complete — Parsed: 2, Ingested (new): 2, Signals: N, Alerts: N"
5. Navigate to Safety Signals — the FHIR-sourced signals appear with `platform = fhir`.

**What you'll see:**
- 5–6 source cards: Reddit (public RSS, no key), Reddit health subreddits (no key), Twitter/X (needs `TWITTERAPI_IO_KEY`), patient forums (heuristic, no key), openFDA FAERS (no key).
- FHIR ingest: the sample bundle contains simvastatin→rhabdomyolysis and lisinopril→angioedema — both should generate or reinforce signals.
- AI engine: `offline` if Ollama is not running (all features still work via deterministic fallback).

**Key things to highlight:**
- FHIR R4 ingestion means VigilAI can accept **EHR-sourced structured adverse events** from clinical systems (Epic, Cerner, etc.) — the same pipeline handles social posts and clinical records uniformly.
- The FHIR parser extracts: drug from `suspectEntity.instance.display`, event from `event.coding[0].display`, location from `location.display`, seriousness from `seriousness.coding[0].code`.
- Every source runs with **no API key** except Twitter (which degrades gracefully when unconfigured).

**Common gotcha:** If Ollama shows `offline` in the AI engine status, all LLM features (narrative regeneration, Copilot, Forge) will fall back to deterministic templates — this is expected behavior and not a failure. The deterministic fallback produces valid, useful output.

**API shortcut:**
```bash
# Fetch FHIR sample bundle:
curl http://localhost:8000/api/fhir/sample | python -m json.tool

# Ingest a FHIR bundle:
curl -X POST http://localhost:8000/api/ingest/fhir \
  -H "Content-Type: application/json" \
  -d '{"resourceType":"Bundle","type":"collection","entry":[{"resource":{"resourceType":"AdverseEvent","status":"completed","actuality":"actual","event":{"coding":[{"display":"rhabdomyolysis"}]},"suspectEntity":[{"instance":{"display":"simvastatin"}}]}}]}'
```

---

## 18. The Hero Demo Moments

### Hero Moment 1 — Drug Signal: Isotretinoin → Depression

**Full walkthrough:**

1. Click **Safety Signals**.
2. Set product type to `drug`, check `SDR only`, sort by `EB05`.
3. Look for `isotretinoin → depression` (or `isotretinoin → depressive symptoms`) near the top.
4. Click the row. In the signal detail header, expect:
   - `💊 Drug` badge + `STRONG` badge + `SDR` badge (rose)
   - `WHO-UMC: Probable` or `Certain`
   - `Critical` severity
   - `▲ Spike z=3.x` (spiking)
   - `🧬 PGx: CYP2D6` or similar (if PGx match)
   - `⬛ Boxed warning` (isotretinoin has an FDA black-box for psychiatric effects and teratogenicity)
   - `⚛ Plausible: retinoid receptor / CNS modulation` mechanism
5. Read the **Disproportionality** panel:
   - PRR typically 4–8 with CI lower bound > 1
   - EB05 ≥ 2 (FDA threshold, rose)
   - IC025 > 0 (UMC threshold, rose)
   - SDR badge: `✓ Signal of Disproportionate Reporting`
6. Read the **Trend chart**: a spike in recent days (the corpus seeds a deliberate late-window burst with temporal + dechallenge + rechallenge language).
7. Read the **External evidence**:
   - `openFDA FAERS: N,NNN reports (+X% confidence)` — real FAERS corroboration
   - `DailyMed label: [link]` — approved SPL on file
   - `Literature (PubMed): N articles` + top article link
8. Scroll to **Source traceability**: see posts mentioning "stopped Accutane and the depression lifted" (dechallenge language), "went back on it and it got worse" (rechallenge) — these are the WHO-UMC causality cues.
9. Click **⬇ E2B R3** — download the XML ICSR.
10. Say: "Every independent layer — statistics, causality, trend, and real-world evidence — agrees on isotretinoin and depression. That convergence is the signal. And it's a genuine black-box warning."

**Why this is the hero signal:**
- Isotretinoin's psychiatric effects (depression, suicidal ideation) are a real FDA black-box warning — the system found a real, validated safety concern.
- Multiple analytical layers converge: strong disproportionality, probable/certain causality, spike trend, FAERS corroboration, PubMed literature, DailyMed label, boxed warning overlay.
- Dechallenge and rechallenge language in the supporting posts is the strongest causality cue — the system detects this automatically.

---

### Hero Moment 2 — Device Signal: Infusion Pump → Overinfusion

**Full walkthrough:**

1. On Safety Signals, set product type to `device`.
2. Look for `infusion pump → overinfusion` (or `insulin pump → malfunction`).
3. Click the row. In the header expect:
   - `🩺 Device` badge (amber)
   - `GMDN/PC XXXX` badge (amber) — FDA product code
   - `IMDRF XXXX` code badge — device failure-mode term
4. Read the **External evidence** panel:
   - **openFDA MAUDE**: N reports — real MAUDE device experience reports
   - **FDA device classification**: product code, Class II or III, 21 CFR regulation number, medical specialty — this is **live real data** from the openFDA device classification endpoint
   - **FDA recalls / enforcement**: any recall records for this device
5. Say: "Same pipeline, devices too — MAUDE experience reports, real FDA product code and class, and IMDRF failure coding. The system routes drug signals to FAERS and device signals to MAUDE automatically."

---

### Hero Moment 3 — Federated Privacy Demo

1. Click **Federated / DP**.
2. Point to the 3 sites (North America, Europe, Asia) and the ε=1.0 Laplace mechanism.
3. Show the top signals table — Fed PRR vs Pooled PRR, consistency badge.
4. Find isotretinoin→depression in the list. Show `✓ Consistent` — the federated (privacy-preserving) estimate agrees with the pooled estimate.
5. Click `View` → Signal Detail → find the `🔐 Fed-PRR 3.1 ε=1.0` chip in the badge strip.
6. Say: "Even with differential privacy noise injected at each site, the federated signal for isotretinoin→depression remains consistent with the pooled estimate. This is how real hospital networks could share pharmacovigilance data without exposing individual records."

---

## 19. If Asked Tough Questions

### Honest Answers to Expected Hard Questions

**Q: Is this real patient data?**
> "The demo corpus is **synthetic and reproducible** — designed to be stable on stage. The same pipeline runs on live Reddit RSS crawls (click 'Crawl Reddit live') and FHIR bundles from real EHR systems. No real patient PII is ever stored — every post is scrubbed by regex + optional Presidio before NLP runs."

**Q: Are the MedDRA codes real MedDRA?**
> "We use an **open MedDRA-style surrogate** — a curated open drop-in that is faithful to real MedDRA PT/SOC structure but is not the licensed MedDRA terminology. Licensed MedDRA requires a subscription from the MSSO. The E2B XML uses our surrogate codes."

**Q: Is the E2B a valid regulatory submission?**
> "It's a **demo-grade E2B R2/R3 template** with real-structure MedDRA PT/SOC, ATC, WHO-UMC, and disproportionality fields — structurally correct but not a validated production regulatory filing. A real ICSR system would integrate with a licensed MedDRA database and go through regulatory validation."

**Q: Can you really query VigiBase?**
> "VigiBase and VigiLyze are licensed WHO products — not openly ingestible. We **model them for architecture fidelity** and label them as surrogates. We emulate VigiLyze-style exploration over our own signal store and say so plainly. The ~9 live connectors (FAERS, MAUDE, DailyMed, PubMed, recalls, device classification, RxNorm) do **real** corroboration with no API key."

**Q: Is the Federated DP analysis real federated learning?**
> "It's a **simulation** over local corpus partitions split by region — not a real multi-institution deployment. The differential privacy math (Laplace mechanism, sequential composition) is real and correct — implemented in `analytics/dp.py` with zero external DP libraries. The disclaimer is shown in the UI."

**Q: Does the LLM hallucinate?**
> "The narrative and Copilot memo are **grounded strictly in the signal's computed evidence** — the LLM path is constrained to the signal's own statistics, WHO-UMC factors, external evidence, and PGx/mechanism/class data. It cannot fabricate facts not in the signal object. The deterministic fallback produces the same structure without any LLM. Both paths are clearly labeled with their source (`llm` or `deterministic`)."

**Q: Is the FAERS data real and current?**
> "Yes — openFDA FAERS is queried live via the public openFDA API (`https://api.fda.gov/drug/event.json`) with no API key. It is **US-only** (FDA data). Results are cached per signal to respect rate limits. The pre-warm step fills the cache before the demo so signals open instantly."

**Q: What happens if there's no internet?**
> "VigilAI is **offline-first**. Transformer NER, Presidio PII scrubbing, PRR/ROR/χ²/EBGM/BCPNN, WHO-UMC, MedDRA coding, the knowledge graph, E2B export, KPIs/SPC, and deterministic narratives all work without internet. External evidence (FAERS/MAUDE/DailyMed/PubMed/recalls) falls back to a deterministic offline knowledge base; pre-warmed signals already have cached values. Local Ollama handles LLM features; if Ollama is down it falls back to deterministic templates. Just avoid 'Crawl Reddit (live)'."

**Q: Why use social media? Doctors don't prescribe based on Reddit.**
> "Real pharmacovigilance agencies (FDA, EMA, WHO) already monitor social media — the FDA has published guidance on patient forums as a spontaneous reporting source. Social listening catches signals **weeks before** they surface in formal spontaneous reports because patients report symptoms to peers before they report to doctors. VigilAI makes that social signal statistically rigorous, explainable, and corroborated against formal regulatory sources."

**Q: What about false positives?**
> "Three things control false positives: (1) the **4-gate AE detector** requires drug + symptom + negative sentiment + non-negated symptom — a casual mention doesn't make it; (2) **Bayesian shrinkage** (EBGM/EB05 + BCPNN IC025) shrinks small-count coincidences toward the null; (3) **empirical calibration** against negative controls removes signals within the observed noise floor. The false-positive ratio KPI on the KPIs & SPC page tracks HCP dismissal rate. After demo seed, expect ~15–25% dismissal rate for realistic triage performance."

**Q: What is the SCRI and is it valid?**
> "SCRI (Self-Controlled Risk Interval) is a real pharmacoepidemiological design used in vaccine safety — each patient is their own control, eliminating stable confounders (age, sex, chronic conditions). The social-listening surrogate here **anchors the risk window at the earliest reported AE onset** (we don't have true vaccination dates in social data). It's labeled as a surrogate. The design principle is sound; the data source is acknowledged as imperfect."

---

*Guide generated from: `backend/app/api/routes.py`, `backend/app/models.py`, `backend/app/analytics/*.py`, `frontend/src/pages/*.jsx`, `frontend/src/App.jsx`, `docs/DEMO_SCRIPT.md`, `docs/PRESENTER_GUIDE.md`.*

*Last updated: 2026-07-05*
