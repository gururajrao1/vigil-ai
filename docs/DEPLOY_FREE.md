# Free / low-cost deploy

Stack used for the live app:

- **Frontend:** Vercel — https://vigil-ai-eight.vercel.app  
- **Backend:** Railway Web Service (Docker) + Postgres — proxied as `/api/*` from Vercel  
- **Auth:** JWT roles admin / analyst / viewer (`backend/app/rbac.py`)

> Older notes mentioned Render free tier. Production `/api` now targets Railway (`frontend/vercel.json`). Prefer Railway for RBAC-current code.

## Empty dashboards / cold start?

Postgres on Railway persists posts across deploys. After idle, wake the API once via `/api/health`, then use **Demo corpus** / Fetch as an **analyst or admin**.

## 1) Backend (Railway)

1. Create/link a Railway project with a Postgres service + `api` service.  
2. From `backend/`: set `DATABASE_URL` (Postgres), `SEED_ADMIN_*`, `AUTO_SEED_DEMO`, optional `TAVILY_API_KEY`, then `railway up -s api`.  
3. Generate a public domain for `api` (e.g. `https://api-….up.railway.app`).  
4. Point `frontend/vercel.json` rewrite `/api/:path*` → that host’s `/api/:path*`.

## 2) Frontend (Vercel)

```powershell
cd frontend
vercel --prod
```

Or: Vercel Dashboard → project root `frontend` → Deploy.

## 3) Demo credentials

| Role | Email | Password |
|------|-------|----------|
| Admin | `admin@vigilai.dev` | `admin123` |
| Analyst | `analyst@vigilai.dev` | `analyst123` |
| Viewer | `viewer@vigilai.dev` | `viewer123` |

Public Register → **viewer** only. Admins promote users on `/users`.

## Demo tip

Before presenting, open `/api/health` once so the API is warm, then walk judges through homepage → Login → Signals.
