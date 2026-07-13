# Biotech Homepage · Schema-Driven Life Sciences Canvas

## Split of concerns

| Role | Tooling | Output |
|------|---------|--------|
| Design-time | Google **Stitch** MCP (`generate_screen`) | Visual HTML / screenshots |
| Runtime | VigilAI FastMCP **`render_biotech_homepage`** | `vigilai.biotech_homepage.v1` JSON |
| Paint | React `BiotechHomepageRenderer` | Editorial sections (no admin grids) |

```
LLM ──render_biotech_homepage(focus_drug?)──▶ layout JSON
                                              │
SPA ──GET /api/biotech/homepage───────────────┘
         ▼
   Hero manifesto · 4-gate pillars · swimlane · signal spotlight
```

## Layer 1 — FastMCP

```bash
cd backend
pip install -r requirements-mcp.txt
python -m app.biotech_homepage.mcp_server
```

MCP config: `docs/mcp-biotech.example.json`

Tool: `render_biotech_homepage(focus_drug: str | None = None)`

Nodes: `hero_manifesto`, `technology_pillars`, `pipeline_swimlane`, `signal_spotlight`, `honesty`, `actions`.

Honesty: live unstructured pipeline vs **local reference surrogates** — never live VigiBase/Sentinel.

## Layer 2 — React

- `/` — public biotech homepage (works logged out; Sign in CTA)
- `/dashboard` — classic ops dashboard (authenticated)
- `/login` — gate for platform routes

Tokens: `#030712` / `#0B1220` / `#131C2E` / mint `#2DD4BF` / sky `#38BDF8`.
Monospace reserved for PRR · EB05 · ROR · provenance paths.

## Layer 3 — Agentic curation

1. **Mutate layout via parameters** — LLM calls `render_biotech_homepage("pregabalin")` → spotlight scopes to that product; open `/?drug=pregabalin`.
2. **Absolute layout tracking** — `meta.spatial` + `schema_version` are the screen model. React does not invent sections.
3. **Add narrative components server-side** — extend `layout_engine.py` with a new Pydantic node + builder; add a renderer branch in `BiotechHomepageRenderer.jsx` only if a new *visual* primitive is required. Prefer folding Forge / webhook cues into `actions[]` so the client stays thin.
4. **Stitch loop** — generate editorial screens with the prompt pack below; map approved motifs into tokens/renderer; never paste Stitch HTML as production React.

### Stitch prompt pack

```text
Life sciences product homepage, deep obsidian #030712, navy sections #0B1220,
glass #131C2E, borders #1E293B, white #F8FAFC, accents #2DD4BF and #38BDF8.
Large Inter/Helvetica display headings weight 800 tracking -0.04em. Emerald
left accent on cinematic manifesto hero. Four technology gate cards. Horizontal
pipeline swimlane. Editorial signal spotlight with bold monospace PRR/EB05 flags
— no data tables, no admin dashboards, no drop shadows, no gradients.
Disclaimer: comparative benchmarks are local surrogates, not live VigiBase/Sentinel.
```

## Smoke

```bash
curl -s "http://127.0.0.1:8010/api/biotech/homepage?focus_drug=pregabalin" | head
open http://127.0.0.1:5173/
open http://127.0.0.1:5173/?drug=pregabalin
```
