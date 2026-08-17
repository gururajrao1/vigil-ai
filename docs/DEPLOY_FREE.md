# Free / low-cost deploy

Production stack (Railway sunset):

- **Frontend:** Vercel — https://vigil-ai-eight.vercel.app  
- **Backend:** Render free Web Service (Docker) — https://vigil-ai-api.onrender.com  
  Proxied as `/api/*` from Vercel ([`frontend/vercel.json`](../frontend/vercel.json))  
- **Database:** Neon free Postgres (`DATABASE_URL`) — persists corpus across Render sleep  
- **Auth:** JWT roles admin / analyst / viewer (`backend/app/rbac.py`)

> Railway was the previous API+Postgres host. Do not rely on it after the trial ends.
> Blueprint: [`render.yaml`](../render.yaml). Migrate scripts: `backend/scripts/migrate_pg_to_neon.py`.

## Empty dashboards / cold start?

Render free instances **sleep after ~15 minutes idle**. First request can take 30–60s.

1. Open https://vigil-ai-api.onrender.com/api/health once (or use the app’s wake path).  
2. Then browse as usual — Neon keeps posts/signals while the API sleeps.

Postgres on Neon persists across deploys and sleep. Deploys do **not** wipe the corpus.

### Memory (512 MB free plan)

After a large FAERS DMA the API can be killed if a request materializes every Signal ORM row (JSON blobs) or every AE post’s entities into one worker. Production code keeps pools tiny (`pool_size=2`), `WEB_CONCURRENCY=1`, `MALLOC_ARENA_MAX=2`, SQL-paginated Detect, and caps the Evidence RDF graph to the strongest unique pairs. If Render emails “exceeded memory limit,” redeploy `main` — do **not** delete Neon rows to “fix” RAM.

To merge unique rows from a local `backend/vigilai.db` into Neon:

```powershell
cd backend
# Set DATABASE_URL to Neon pooled URL, then:
.\.venv\Scripts\python.exe scripts\merge_sqlite_into_pg.py
# Then POST /api/recompute as admin/analyst
```

To copy Railway (or any) Postgres → Neon before cutting over:

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\migrate_pg_to_neon.py --src-file railway_public_url.txt --dst-file neon_url.txt
```

## 1) Backend (Render + Neon)

1. Create a Neon project → copy the **pooled** `postgresql://…` URL (`sslmode=require`).  
2. Render Dashboard → Blueprint / GitHub connect using [`render.yaml`](../render.yaml), **or** update existing service `vigil-ai-api`.  
3. Set env vars on the service:
   - `DATABASE_URL` = Neon pooled URL  
   - `JWT_SECRET`, `SEED_ADMIN_EMAIL`, `SEED_ADMIN_PASSWORD`  
   - `USE_TRANSFORMER_NER=false`, `AUTO_SEED_DEMO=true` (as in blueprint)  
4. Confirm https://vigil-ai-api.onrender.com/api/health and login.

## 2) Frontend (Vercel)

[`frontend/vercel.json`](../frontend/vercel.json) must rewrite `/api/:path*` → `https://vigil-ai-api.onrender.com/api/:path*`.

```powershell
cd frontend
vercel --prod
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

## Sunset Railway

After verifying Vercel → Render → Neon end-to-end, cancel or leave the Railway project idle so the 14-day cliff does not surprise you. Keep Neon as the source of truth.
