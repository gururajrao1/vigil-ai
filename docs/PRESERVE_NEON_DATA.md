# Preserve Neon data (client demo) — do NOT wipe Neon

Your corpus is **still on Neon**. Free **network transfer** exhaustion **suspends compute**; it does **not** delete tables. Login 500s are “locked door,” not lost data.

Right now every connection fails with:

```text
Your project has exceeded the data transfer quota. Upgrade your plan to increase limits.
```

There is **no offline dump** in this repo we can restore from. The only safe way to keep every row for a client demo is to **unlock Neon**, then optionally copy out.

---

## Path A — Fastest for tomorrow’s demo (recommended)

**Upgrade the Neon project to Launch** (pay-as-you-go; ~$0 unless you leave heavy compute on).

1. Open [Neon Console](https://console.neon.tech) → org that owns the VigilAI project (`autumn-forest…` / DB `vigilai`).
2. **Billing / Upgrade** → **Launch**.
3. If Neon was created via **Vercel Storage**: Vercel → project → **Storage** → Neon → **Change Configuration** → Launch (Vercel-managed billing).
4. Wait 1–2 minutes; retry https://vigil-ai-api.onrender.com/api/health then login.
5. Keep Render `DATABASE_URL` pointing at the **same** Neon pooled URL — no app code change.

You keep **all** posts, signals, OMOP, users. Then hard-refresh the SPA and run **Recompute** once (FAERS entity fix is already on `main`) so signals finally include FAERS.

Estimated cost for a short demo window: usually **well under a few dollars** if scale-to-zero stays on.

---

## Local backup (already taken while Launch was unlocked)

Full corpus dump on this machine (do not commit to git):

```text
backend/data/vigilai_neon_backup.db
```

~372k rows / ~74 MB including `raw_posts` (16447), `signals`, OMOP exposures, users, etc.

Restore into Supabase after you create a project:

```powershell
cd backend
# Put pooler URI in a file (do not commit):
# supabase_url.txt → postgresql://postgres.REF:PASS@….pooler.supabase.com:6543/postgres?sslmode=require
$env:DATABASE_URL = (Get-Content .\supabase_url.txt -Raw).Trim()
.\.venv\Scripts\python.exe scripts\restore_sqlite_to_pg.py --sqlite data/vigilai_neon_backup.db
```

Then set the same URI on Render `DATABASE_URL` and restart.


---

## What NOT to do

- Do **not** create an empty Supabase DB and switch Render to it before dumping Neon — that presents an empty product.
- Do **not** delete the Neon project.
- Do **not** keep retrying huge stream-ingests on Free Neon after unlock without Launch (you will hit 5 GB egress again).

---

## After unlock — demo checklist

1. Login works (`admin@vigilai.dev` / `admin123` or your seeded users).
2. Overview shows ~16k posts / FAERS breakdown (if still on same DB).
3. **Recompute** signals (admin) so FAERS string-entity fix lands in DMA.
4. Hard-refresh https://vigil-ai-eight.vercel.app.

If Launch is upgraded and login still 500s, say so — next step is verify Render’s `DATABASE_URL` still matches the unlocked Neon project.
