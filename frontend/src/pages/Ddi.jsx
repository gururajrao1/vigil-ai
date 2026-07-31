import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { useRefresh } from '../App';
import { Badge, Button, Card, Spinner } from '../components/ui';

/** Drug–drug interaction findings — actionable cards, not a number dump. */
export default function Ddi({ embedded = false }) {
  const { tick, bump } = useRefresh();
  const [data, setData] = useState(null);
  const [plausibleOnly, setPlausibleOnly] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [autoTried, setAutoTried] = useState(false);

  const load = () => {
    api.ddi({ plausible_only: plausibleOnly || undefined, min_count: 1 })
      .then(setData)
      .catch(() => setData({ findings: [], pairs: [], needs_demo_seed: true, headline: 'Could not load DDI.' }));
  };

  useEffect(() => { load(); }, [tick, plausibleOnly]);

  useEffect(() => {
    if (!data || autoTried || busy) return;
    if (data.needs_demo_seed) {
      setAutoTried(true);
      (async () => {
        setBusy(true);
        try {
          await api.ingestPvDemo({ recompute: true });
          bump?.();
          load();
        } catch (e) {
          setErr(e?.message || String(e));
        }
        setBusy(false);
      })();
    }
  }, [data, autoTried, busy]);

  const loadDemo = async () => {
    setBusy(true);
    setErr(null);
    try {
      await api.ingestPvDemo({ recompute: true });
      bump?.();
      load();
    } catch (e) {
      setErr(e?.message || String(e));
    }
    setBusy(false);
  };

  if (!data) return <Spinner label="Mining DDI co-mentions…" />;
  const findings = data.findings || data.pairs || [];

  return (
    <div className="space-y-5">
      {!embedded && (
        <div>
          <h2 className="text-xl font-bold text-slate-100">Drug–drug interaction findings</h2>
          <p className="text-sm text-slate-400 mt-1">
            Co-mentioned products on the same AE report — ranked by plausibility / known DDI patterns.
            This is a hypothesis list for clinical review, not an interaction checker.
          </p>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3 text-sm">
        <p className="text-slate-200 flex-1">{data.headline || data.verdict}</p>
        <label className="flex items-center gap-2 text-slate-300 cursor-pointer">
          <input type="checkbox" checked={plausibleOnly} onChange={(e) => setPlausibleOnly(e.target.checked)} />
          Plausible / patterned first
        </label>
        <Button variant="primary" disabled={busy} onClick={loadDemo}>
          {busy ? 'Loading demo…' : 'Refresh demo pack'}
        </Button>
      </div>
      {err && <p className="text-sm text-rose-300">{err}</p>}

      {findings.length === 0 ? (
        <Card className="p-4 text-sm text-slate-400">
          {busy ? 'Seeding polypharmacy fixtures…' : 'No findings yet — click Refresh demo pack.'}
        </Card>
      ) : (
        <div className="space-y-3">
          {findings.slice(0, 15).map((p) => (
            <Card key={`${p.drug_a}|${p.drug_b}|${p.event}`} className="p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium text-slate-100">
                    {p.headline || `${p.drug_a} + ${p.drug_b} → ${p.event}`}
                  </div>
                  <p className="mt-1.5 text-sm text-slate-300 leading-relaxed">
                    {p.why_it_matters || p.plausibility?.known_pattern?.note || 'Co-mention interaction candidate.'}
                  </p>
                  <p className="mt-1 text-[12px] text-amber-200/90">
                    Next: {p.what_to_do || 'Review on Signal Detail after opening either product.'}
                  </p>
                  <div className="mt-2 text-[11px] text-slate-500">
                    n={p.count} · Ω={p.omega} (Ω025={p.omega025})
                    {p.interaction_ror != null ? ` · interaction-ROR≈${p.interaction_ror}` : ''}
                  </div>
                </div>
                <div className="flex flex-col gap-1.5 items-end">
                  <Badge
                    value={p.strength || 'WEAK'}
                    className={
                      p.strength === 'STRONG'
                        ? 'bg-rose-500/15 text-rose-300 border-rose-500/30'
                        : p.strength === 'MODERATE'
                          ? 'bg-amber-500/15 text-amber-300 border-amber-500/30'
                          : 'bg-slate-600/20 text-slate-400 border-slate-600/30'
                    }
                  />
                  <Badge
                    value={(p.plausibility || {}).plausible ? 'plausible' : 'review'}
                    className={
                      (p.plausibility || {}).plausible
                        ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
                        : 'bg-slate-600/20 text-slate-400 border-slate-600/30'
                    }
                  />
                  <Link
                    to={`/signals?q=${encodeURIComponent(p.drug_a)}`}
                    className="text-xs text-sky-300 hover:underline capitalize"
                  >
                    Find {p.drug_a} signals →
                  </Link>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {data.disclaimer && <p className="text-[10px] text-slate-500 leading-relaxed">{data.disclaimer}</p>}
    </div>
  );
}
