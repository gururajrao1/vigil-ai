# Free / low-cost deploy

Production stack:

- **Frontend:** Vercel — https://vigil-ai-eight.vercel.app  
- **Backend:** Render free Web Service (Docker) — https://vigil-ai-api.onrender.com  
  Proxied as `/api/*` from Vercel ([`frontend/vercel.json`](../frontend/vercel.json))  
- **Database:** **Supabase free Postgres** (`DATABASE_URL`, pooler port **6543**) — preferred after Neon free **network-transfer** exhaustion  
- **Auth:** JWT roles admin / analyst / viewer (`backend/app/rbac.py`)

> **Neon sunset for this project:** Free egress (~5 GB/month) was exhausted; DB reads/writes (including login) return 500. Do not point `DATABASE_URL` at Neon until you upgrade Neon or the quota resets.  
> Cutover steps: [`CUTOVER_SUPABASE.md`](./CUTOVER_SUPABASE.md).  
> Blueprint: [`render.yaml`](../render.yaml). Generic PG copy: `backend/scripts/migrate_pg_to_neon.py` (works for any Postgres→Postgres).

## Empty dashboards / cold start?

Render free instances **sleep after ~15 minutes idle**. First request can take 30–60s.

1. Open https://vigil-ai-api.onrender.com/api/health once.  
2. Then browse as usual — Postgres (Supabase) keeps posts/signals while the API sleeps.

## 1) Backend (Render + Supabase)

1. Create a Supabase project → copy the **pooler** URI (`…pooler.supabase.com:6543/postgres?sslmode=require`). See [`CUTOVER_SUPABASE.md`](./CUTOVER_SUPABASE.md).  
2. Render → **vigil-ai-api** → Environment → set `DATABASE_URL` to that URI.  
3. Redeploy / restart the service. `init_db()` seeds admin users on empty DB.  
4. Confirm `/api/health` and login (`admin@vigilai.dev` / `admin123`).

Optional paid path: Render Postgres Starter → same `DATABASE_URL` swap.

## 2) Frontend (Vercel)

[`frontend/vercel.json`](../frontend/vercel.json) must rewrite `/api/:path*` → `https://vigil-ai-api.onrender.com/api/:path*`.

```powershell
cd frontend
npx vercel --prod
```

## 3) Demo credentials

| Role | Email | Password |
|------|-------|----------|
| Admin | `admin@vigilai.dev` | `admin123` |
| Analyst | `analyst@vigilai.dev` | `analyst123` |
| Viewer | `viewer@vigilai.dev` | `viewer123` |

Public Register → **viewer** only. Admins promote users on `/users`.

## Demo tip

Before presenting, open `/api/health` once so Render is warm, then walk homepage → Login → Signals (General PV).

## Why not Neon free?

| Quota | What happened |
|-------|----------------|
| Storage 0.5 GB/project | Fine (~0.16 GB used) |
| Network transfer ~5 GB/mo | **Exceeded** → compute/DB connections refused → login 500 |
| CU-hours | Was still low |

Supabase free is a better fit for a Render-hosted API that streams FAERS; still watch egress when bulk-ingesting.
