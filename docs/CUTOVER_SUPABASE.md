# Cut over VigilAI — Neon → Supabase (optional)

> **Client demo / keep all data first:** read [`PRESERVE_NEON_DATA.md`](./PRESERVE_NEON_DATA.md).  
> Upgrade Neon to **Launch** to unlock the existing corpus. Do **not** point Render at an empty Supabase DB until you have a successful `pg_dump` / restore.

Neon free **network transfer** exhaustion suspends compute → login/`/api/*` that hit the DB return **500**.
Storage was fine; the blocker is **egress**, not deleted data.

**Recommended for demos:** stay on Neon **Launch** (Path A in PRESERVE_NEON_DATA).  
**Optional later:** copy to Supabase after unlock (Path B).

---

## Only if you intentionally want a fresh empty DB

(Skip this if you need the 16k FAERS corpus for clients.)

1. Create Supabase project → pooler URI port **6543** + `sslmode=require`.
2. Render → `DATABASE_URL` → that URI → restart.
3. `init_db()` seeds admin; Overview is empty until re-ingest.

## Supabase pooler URI shape

```text
postgresql://postgres.YOUR_REF:YOUR_PASSWORD@aws-0-….pooler.supabase.com:6543/postgres?sslmode=require
```

Do **not** use direct `db.…supabase.co:5432` from Render (IPv6 issues).
