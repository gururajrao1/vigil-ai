# Cut over VigilAI Postgres → Aiven Free (Neon bridge)

**Why Aiven:** always-on dedicated free Postgres (1 GB disk / 1 GB RAM), no credit card,
no 7‑day idle pause (Supabase), no Neon-style **egress soft-lock** that blocked login mid-demo.
Capped resources, not “unlimited” — but it will not hang the whole API when a transfer quota trips.

## 1) Create the free service

1. Sign up at https://console.aiven.io (no card).
2. **Create service → PostgreSQL → Free** (1 GB). Prefer a region close to Render (`oregon` / `us-west` if listed).
3. Wait until status is **Running**.
4. Open **Overview → Connection information**:
   - Copy the **Service URI** (`postgres://…` or `postgresql://…`).
   - Prefer the **connection pooler** URI if Aiven shows one (PgBouncer).
5. Ensure SSL is on (Aiven requires TLS). Append `?sslmode=require` if missing.

## 2) Restore corpus (local)

From `backend/` (venv active), with the **new** URI:

```powershell
$env:DATABASE_URL = "postgresql://avnadmin:…@….aivencloud.com:…/defaultdb?sslmode=require"
.\.venv\Scripts\python.exe scripts\restore_sqlite_to_pg.py --sqlite data\vigilai_neon_backup.db
```

Use the freshest dump:

- `data/vigilai_neon_backup.db` — current Neon snapshot (preferred after a fresh dump)
- or `data/backups/vigilai_20260816T170253Z/vigilai_db.sqlite` — larger pre-purge snapshot

## 3) Point Render + local at Aiven

1. Render → vigil-ai-api → **Environment** → set `DATABASE_URL` to the Aiven URI (same as above).
2. Local `backend/.env` → same `DATABASE_URL`.
3. Redeploy / wait for Render bounce.
4. Verify:

```text
https://vigil-ai-api.onrender.com/api/health
https://vigil-ai-api.onrender.com/api/dashboard/stats
```

Login with demo users (`admin@vigilai.dev` / `admin123`).

## 4) Keep Neon until verified

Do **not** delete the Neon project until login + Overview counts look right on Aiven.
When Neon free resets next month you can dump Aiven → restore Neon again the same way.

## Paste back

Reply with the Aiven **Service URI** (redact password in chat if you prefer a one-time paste
into Render only). Once `DATABASE_URL` is set locally we run restore + verify here.
