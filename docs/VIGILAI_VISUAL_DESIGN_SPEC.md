# VigilAI Visual Design Specification

**Product:** VigilAI — post-market pharmacovigilance & medical device safety  
**Mode:** Premium Life Sciences digital stage · dark high-contrast · **zero animation**  
**Nav:** Exactly nine hubs in a dark slate sidebar

---

## 1. Global aesthetics & color tokens

| Token | Hex | Role |
|-------|-----|------|
| `--va-canvas` | `#030712` | Full app canvas (solid — no radial washes) |
| `--va-navy` | `#0B1220` | Sidebar / header chrome |
| `--va-glass` | `#131C2E` | Cards, panels, ledger rows |
| `--va-border` | `#1E293B` | 1px frames only |
| `--va-text` | `#F8FAFC` | Primary display copy |
| `--va-muted` | `#94A3B8` | Labels, secondary prose |
| `--va-mint` | `#2DD4BF` | Metrics, checks, pipeline active |
| `--va-sky` | `#38BDF8` | Secondary clinical accents |

**Hard bans:** drop shadows, glowing panels, saturated primary gradients, fuzzy blur as decoration, motion/keyframes, pulse rings, spin loaders as animation.

**Geometry:** 4px corner radius (`--va-radius: 4px`) on all containers. Sharp, clinical, not soft SaaS pills.

---

## 2. Typography & spatial rhythm

| Use | Face | Weight | Tracking |
|-----|------|--------|----------|
| Page / manifesto titles | Inter, Helvetica Neue | 700–800 | `-0.04em` |
| Section headers | Inter | 700 | `-0.03em` |
| Body / narrative | Inter | 400–500 | normal |
| Stats & equations | Fira Code / system mono | 600 | `0` |
| Runtime / file tags | Mono only | 500 | `0.04–0.08em` |

Monospace is **restricted** to: PRR, EB05, ROR, IC025, EBGM, N, env tags, schema paths, forge control values.

Page title rhythm: title → one muted subtitle line → content. No emoji icon forests in chrome.

---

## 3. Nine-hub layout blueprint

### 3.1 Homepage (`/`)
- Full-bleed cinematic landing (no sidebar chrome on this route).
- Manifesto block with **3px vertical mint rule** on the left.
- Throughput as large mono integers (docs / AE yield / pairs), each tagged `live_unstructured_pipeline`.
- Honesty strip: local reference surrogates ≠ live VigiBase/Sentinel.

### 3.2 Dashboard (`/dashboard`)
- Asymmetric **telemetry row**: large integers, not dense chart walls as the hero.
- Graphs (if present) are secondary, muted strokes on glass panels.
- Tabs: Corpus metrics · Ops KPIs — flat tab strip, mint active underline.

### 3.3 Safety Signals (`/signals`)
- **Clinical card ledger** (or dense table styled as card-rows): product → event as editorial pair.
- Strength/severity as high-contrast status pills (mint/sky/critical), not rainbow chips.
- Mono flags for PRR / EB05 / ROR.

### 3.4 Analytic Lenses (`/lenses`)
- **Tile matrix**: SMQ · class effects · vaccine · geo · divergence as equal flat tiles.
- Each tile: title, one-line clinical note, mint/sky top hairline — no nested dashboards.

### 3.5 Evidence Explorer (`/graph`)
- **Dual viewport:** node-link canvas (left) · Story Mode stepper (right).
- Path focus: unrelated nodes/edges at **15% opacity** (`opacity: 0.15`); active path full opacity mint/sky.
- No animated force jiggle as UX — layout may compute once; no CSS motion.

### 3.6 Projects (`/projects`)
- **Case portfolio** cards: owner names (e.g. Gururaja, Bharat, Shekhar) in muted mono tags.
- Structural target title in display weight (e.g. Air Pollution & Alzheimer's Predictive Risk Model).
- Status as mint/sky pill only.

### 3.7 Source Discovery (`/source-queue`) & Data Sources (`/sources`)
- Technical index of stream properties (protocol, latency class, auth).
- **Mandatory honesty banner:** comparative logic uses **local surrogate snapshots** only — never live closed-registry pipes.

### 3.8 Data Forge (`/forge`)
- Simulation control stage: injection error rate, negation density, etc. as **mono control targets** on glass panels.
- No playful illustrations; parameter → value → apply.

---

## 4. Interaction (static)

- Hover: border/text color shift only — **no transform, no shadow rise, no fade animations**.
- Loading: static mint square or “loading…” mono text — **no spinners**.
- Focus rings: 1px mint border, no glow shadow.

---

## 5. Compliance voice

Every comparative or registry-adjacent surface must remain honest:
- Live = workspace unstructured pipeline.
- Benchmark = local openFDA FAERS/MAUDE-style surrogate / offline KB.
- Never claim live WHO VigiBase, Sentinel, or licensed MedDRA sync.

Disclaimer footer on homepage and Sources remains visible.

---

## 6. Implementation map

| Layer | Location |
|-------|----------|
| Tokens + no-motion | `frontend/src/index.css` |
| Primitives | `frontend/src/components/ui.jsx` |
| Honesty banner | `frontend/src/components/SurrogateHonestyBanner.jsx` |
| Shell / 9 hubs | `frontend/src/App.jsx` |
| Homepage stage | `frontend/src/biotech/*` |
| Spec (this file) | `docs/VIGILAI_VISUAL_DESIGN_SPEC.md` |
