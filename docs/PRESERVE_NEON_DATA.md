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

## Path B — Unlock Neon, then copy to Supabase (keep a second copy)

Only after Path A works:

```powershell
cd backend
# Install Postgres client tools if needed (pg_dump / pg_restore).

# 1) Dump from Neon (use DIRECT host if pooler struggles with long dumps;
#    still requires Launch so quota allows the transfer).
$env:PGPASSWORD = "<neon_password>"
pg_dump -Fc -h <neon-host> -U <user> -d vigilai -f vigilai_neon.dump

# 2) Restore into Supabase (pooler or direct — follow Supabase import docs).
pg_restore --clean --if-exists --no-owner --no-acl -d "<supabase_uri>" vigilai_neon.dump
```

Or use the existing helper (any Postgres → Postgres):

```powershell
.\.venv\Scripts\python.exe scripts\migrate_pg_to_neon.py --src-file neon_url.txt --dst-file supabase_url.txt
```

Then point Render `DATABASE_URL` at Supabase **only after** row counts match.

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
