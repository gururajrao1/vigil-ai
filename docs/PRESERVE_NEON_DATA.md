# Preserve Neon data (client demo) — do NOT wipe Neon

Your corpus lives on Neon (and in local SQLite backups). Free **network transfer**
exhaustion suspends compute; it does **not** delete tables. Login 500s are a
“locked door,” not lost data.

---

## Path A — Keep Neon (recommended while Launch is unlocked)

1. Neon Console → project on **Launch** (or unlock if Free quota blocked egress).
2. Keep Render `DATABASE_URL` on the **same** Neon pooled URL.
3. Hard-refresh https://vigil-ai-eight.vercel.app — Overview **Posts ingested**
   should match `GET /api/dashboard/stats` → `total_posts` (currently **~27k** after
   the local 24k FAERS bridge).

No app code change required for Path A.

---

## Local backups (already on this machine — gitignored)

| Path | What |
|------|------|
| `backend/data/vigilai_neon_backup.db` | Full Postgres → SQLite dump (~94 MB / ~395k rows) |
| `backend/data/backups/vigilai_<stamp>/` | Pack: `vigilai_db.sqlite` + `manifest.json` (counts + FAERS JSON inventory) |

Refresh after major ingest/recompute:

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\backup_vigilai_corpus.py
.\.venv\Scripts\python.exe scripts\dump_pg_to_sqlite.py --out data\vigilai_neon_backup.db
```

External multi‑GB openFDA JSON stays under `%USERPROFILE%\Data\vigilai` (inventoried by path/size only).

---

## Path B — Temporary new DB (Supabase) without losing data

1. Create Supabase project → **pooler** URI port **6543** + `sslmode=require`.
2. Restore **before** pointing Render at empty Supabase:

```powershell
cd backend
$env:DATABASE_URL = (Get-Content .\supabase_url.txt -Raw).Trim()   # do not commit
.\.venv\Scripts\python.exe scripts\restore_sqlite_to_pg.py --sqlite data\vigilai_neon_backup.db
```

3. Set the same URI on Render `DATABASE_URL` → restart.
4. Verify login + `/api/dashboard/stats` (`total_posts` ≈ 27k) then recompute if signals look stale.

See also [`CUTOVER_SUPABASE.md`](./CUTOVER_SUPABASE.md).

---

## What NOT to do

- Do **not** switch Render to an empty Supabase DB before restore.
- Do **not** delete the Neon project until restore + live stats are verified.
- Do **not** expect Safety signals / Organ classes to jump from post inserts alone — run **Recompute** (DMA). Prefer `use_fda=False` on large corpora so openFDA fan-out does not hang for hours.

---

## Demo checklist

1. `/api/health` → `status: ok`
2. Login (`admin@vigilai.dev` / `admin123`)
3. Overview: **Posts ingested > 16k**, FAERS posts / Countries from live SQL (no hardcoded tiles)
4. After recompute: signals / alerts / spikes / priority / SOC counts refresh from PRR/ROR/χ²
5. Hard-refresh https://vigil-ai-eight.vercel.app
