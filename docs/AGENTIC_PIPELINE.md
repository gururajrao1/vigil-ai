# VigilAI Agentic Pipeline — Implementation Blueprint

Six-step upgrade from deterministic scrapers to an autonomous discovery-to-signal intelligence pipeline.

## Workflow

```
[1 Project Scoping] → [2 Pathfinder Discovery] → [3 Suggested Source Queue]
                                                          ↓
[6 Parameterized SPARQL] ← [5 FAERS Divergence] ← [4 Privacy Guard]
```

## Step 1 — Project-scoping & workspace isolation

**Backend**
- Models: `Project`, `MonitoredQuery`, `PathfinderRun`, `SuggestedSource` in `backend/app/models.py`
- FK `project_id` on `RawPost`, `Signal`, `Alert` with `ON DELETE CASCADE`
- Scoping: `backend/app/projects/scope.py` — `get_active_project()` reads `X-Project-Id` header
- Seed: `backend/app/projects/seed.py` — default workspaces + legacy backfill

**Frontend**
- `frontend/src/projectContext.jsx` — active project selector (header)
- `frontend/src/pages/Projects.jsx` — workspace management

## Step 2 — Pathfinder discovery loop

**Backend:** `backend/app/projects/pathfinder.py`
- Exa AI → Tavily → offline curated seeds (no key required)
- BeautifulSoup4 DOM scan for `wp-login`, `sign-in`, `paywall-overlay`, etc.
- Results enqueue `SuggestedSource` rows

**API:** `POST /api/projects/{id}/pathfinder/run-sync`

## Step 3 — Suggested source queue + Playwright

**Backend:** `backend/app/projects/source_queue.py`
- UI statuses: `🟢 public`, `🟡 login_required`
- `approve_and_onboard()` — Playwright with `storage_state` from `backend/app/browser_profiles/cookies.json`
- Falls back to httpx when Playwright is not installed

**Frontend:** `frontend/src/pages/SourceQueue.jsx`

**Setup login-walled forums:**
```bash
pip install playwright && playwright install chromium
playwright codegen --save-storage=backend/app/browser_profiles/cookies.json https://your-forum.example/login
```

## Step 4 — Privacy protection guard

**Backend:** `backend/app/projects/privacy_gateway.py`
- Async Presidio + regex gateway before 4-gate NLP
- Wired into `ingest_posts()` via `scrub_sync()`

## Step 5 — FAERS divergence engine

**Backend:** `backend/app/projects/divergence.py`
- Social daily buckets vs openFDA FAERS `receivedate` counts
- SciPy z-scores + project-scoped PRR/ROR/χ²/EB05
- Divergence alert when social spikes and FAERS stays flat

**Frontend:** `frontend/src/pages/Divergence.jsx` (Recharts side-by-side timelines)

**API:** `GET /api/projects/{id}/divergence?drug=...&symptom=...`

## Step 6 — Parameterized SPARQL graph

**Backend:** `backend/app/projects/rdf_graph.py`
- In-memory `rdflib` graph: `Drug → caused → Symptom`, regional `reportedIn` edges
- Parameterized SPARQL: `region_param`, `symptom_param`, `focus_node` for 1-hop clipping

**Frontend:** `frontend/src/pages/KnowledgeGraph.jsx` — filters + node-click focus expansion

**API:** `GET /api/projects/{id}/graph/sparql?region=China&symptom=nausea`

## Configuration (optional keys)

```env
EXA_API_KEY=
TAVILY_API_KEY=
PLAYWRIGHT_STORAGE_STATE_PATH=
```

## Offline-first fallbacks (implemented)

| Capability | Live path | Fallback |
|------------|-----------|----------|
| Pathfinder | Exa → Tavily | `_OFFLINE_SEEDS` + keyword-derived URLs |
| Source crawl | Playwright + cookies | httpx + BeautifulSoup |
| PII scrub | Presidio NER | regex layer (always on) |
| FAERS divergence | openFDA timeline API | `query_openfda()` offline KB → flat zero baseline |

Probe active modes: `GET /api/projects/capabilities` or `GET /api/health` → `pipeline_capabilities`.


Prototype; synthetic data is fictional; openFDA = US FAERS/MAUDE only; MedDRA coding is an open surrogate; not for clinical use.
