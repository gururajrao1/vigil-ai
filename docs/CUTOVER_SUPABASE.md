# Cut over VigilAI off Neon → Supabase (free Postgres)

Neon free **network transfer** is exhausted → login/`/api/*` that hit the DB return **500**.
Storage was fine (~0.16 GB); the blocker is **egress**, not disk.

**Recommended replacement:** [Supabase](https://supabase.com) free Postgres (persistent, pooler on port **6543** works from Render).

Neon data cannot be copied while the quota is blocked. This is a **fresh DB** cutover (seeded admin + re-ingest later).

## 1) Create Supabase project

1. Sign in at https://supabase.com/dashboard → **New project**.
2. Region: prefer **US West** (close to Render Oregon).
3. Set a strong DB password (save it).
4. **Project Settings → Database → Connection string → URI**.
5. Choose **Connection pooling** (Transaction) — host like `…pooler.supabase.com`, port **6543**.
6. Copy the URI. It should look like:

```text
postgresql://postgres.YOUR_REF:YOUR_PASSWORD@aws-0-….pooler.supabase.com:6543/postgres
```

Add `?sslmode=require` if missing:

```text
postgresql://postgres.YOUR_REF:YOUR_PASSWORD@aws-0-….pooler.supabase.com:6543/postgres?sslmode=require
```

Do **not** use the direct `db.…supabase.co:5432` URL from Render (IPv6 issues).

## 2) Point Render API at Supabase

1. https://dashboard.render.com → service **vigil-ai-api** → **Environment**.
2. Set **`DATABASE_URL`** = the pooled Supabase URI above (replace the Neon URL).
3. Keep `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD` (defaults `admin@vigilai.dev` / `admin123`).
4. **Manual Deploy → Clear build cache & deploy** (or restart the service).

On boot, VigilAI runs `init_db()` + seeds demo users. Empty corpus is expected until you ingest again.

## 3) Point local `.env` at Supabase

In `backend/.env` replace `DATABASE_URL` with the same pooled URI, then:

```powershell
cd backend
.\.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv(); from app.database import init_db; init_db(); print('ok')"
```

## 4) Verify

```text
https://vigil-ai-api.onrender.com/api/health
```

Login: `admin@vigilai.dev` / `admin123` on https://vigil-ai-eight.vercel.app

Then **hard-refresh**. Overview will be near-empty until stream-ingest / demo pack.

## 5) Rebuild corpus (after login works)

Prefer CDN stream-ingest (no full download), with modest limits so you don’t blow Supabase free egress:

```http
POST /api/etl/openfda/stream-ingest
{ "domain": "drug", "max_partitions": 5, "event_limit": 20000, "also_posts": true, "recompute_signals": true }
```

Or in the app: load PV demo pack, then **Recompute**.

## Optional: paid Render Postgres

If you prefer DB co-located on Render: Dashboard → **New → PostgreSQL** (Starter), copy Internal/External URL into `DATABASE_URL`. Same restart steps. Not free forever on new accounts.

## Do not

- Keep hammering Neon (wastes nothing useful; quota already blocked).
- Commit real `DATABASE_URL` / passwords into git.
- Stream all ~2k openFDA partitions on day one.
