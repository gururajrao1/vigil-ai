# Free deploy (Vercel + Render) — no paid trial required

Stack used for submissions:
- **Frontend:** Vercel Hobby (free)
- **Backend:** Render free Web Service (Docker) — sleeps after ~15 min idle
- **Database:** SQLite on the Render instance (ephemeral) **or** free Neon Postgres if you add `DATABASE_URL`

## Empty dashboards after sleep?

Render free wipes SQLite when the instance sleeps. With `AUTO_SEED_DEMO=true` (default in `render.yaml`), startup **auto-fills** empty workspaces (General PV + oncology + vaccine) in the background so Overview / Signals / Alerts are not zeros for demo visitors.

- First open after sleep: wait ~1–2 min after health is OK while the corpus loads.
- Optional true persistence: Neon `DATABASE_URL` (seed runs once, then keeps real ingested data).

## 1) Backend on Render (one-time clicks)

1. Open: https://render.com/deploy?repo=https://github.com/gururajrao1/vigil-ai  
2. Sign in with **GitHub** (same account as the repo).  
3. Apply the Blueprint (`render.yaml`) → create **vigil-ai-api**.  
4. Wait for the first deploy (5–10 min).  
5. Copy the service URL, e.g. `https://vigil-ai-api.onrender.com`.

Optional (persistent DB): create a free project at https://console.neon.tech → copy connection string → Render → Environment → `DATABASE_URL` → Redeploy.

## 2) Frontend on Vercel

```powershell
cd frontend
vercel link --yes --project vigil-ai
vercel env add VITE_API_BASE production
# paste: https://YOUR-RENDER-URL   (no trailing slash)
vercel --prod
```

Or: Vercel Dashboard → Import `gururajrao1/vigil-ai` → Root Directory = `frontend` → Env `VITE_API_BASE` = Render URL → Deploy.

## 3) Submit this link

Give judges the **Vercel URL** only.

Login: `admin@vigilai.dev` / `admin123`  
Then: header **Sources → Fetch** (or Data Sources) → Safety Signals.

## Demo tip

Before presenting, open `https://YOUR-RENDER-URL/api/health` once so Render wakes up (cold start 30–60s), then give the auto-seed ~1–2 minutes before walking a judge through the UI.
