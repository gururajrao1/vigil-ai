import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { useRefresh } from '../App';
import { Badge, Button, Card, Spinner } from '../components/ui';

/** Pregnancy / teratogen findings — review cards with next actions. */
export default function Pregnancy({ embedded = false }) {
  const { tick, bump } = useRefresh();
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [autoTried, setAutoTried] = useState(false);

  const load = () => {
    api.pregnancy().then(setData).catch(() => setData(null));
  };

  useEffect(() => { load(); }, [tick]);

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

  if (!data) return <Spinner label="Building pregnancy cohort…" />;
  const findings = data.findings || data.congenital_signals || [];

  return (
    <div className="space-y-5">
      {!embedded && (
        <div>
          <h2 className="text-xl font-bold text-slate-100">Pregnancy / teratogen findings</h2>
          <p className="text-sm text-slate-400 mt-1">{data.how_to_use}</p>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <p className="text-sm text-slate-200 flex-1">{data.headline || data.verdict}</p>
        <Button variant="primary" disabled={busy} onClick={loadDemo}>
          {busy ? 'Loading…' : 'Refresh pregnancy demo pack'}
        </Button>
      </div>
      {data.fixture_blended && (
        <p className="text-[11px] text-amber-200/80">
          Showing offline teratogen fixtures blended into this view until live pregnancy ICSRs accumulate.
        </p>
      )}
      {err && <p className="text-sm text-rose-300">{err}</p>}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Card className="p-3">
          <div className="text-[10px] uppercase text-slate-500">AE posts</div>
          <div className="text-lg text-slate-100">{data.n_posts_total}</div>
        </Card>
        <Card className="p-3">
          <div className="text-[10px] uppercase text-slate-500">Pregnancy cohort</div>
          <div className="text-lg text-amber-200">{data.n_pregnancy_posts}</div>
        </Card>
        <Card className="p-3">
          <div className="text-[10px] uppercase text-slate-500">Findings</div>
          <div className="text-lg text-rose-300">{findings.length}</div>
        </Card>
        <Card className="p-3">
          <div className="text-[10px] uppercase text-slate-500">Other preg. signals</div>
          <div className="text-lg text-slate-100">{(data.other_pregnancy_signals || []).length}</div>
        </Card>
      </div>

      {findings.length === 0 ? (
        <Card className="p-4 text-sm text-slate-400">
          {busy ? 'Seeding pregnancy / teratogen fixtures…' : 'No congenital findings yet — click Refresh pregnancy demo pack.'}
        </Card>
      ) : (
        <div className="space-y-3">
          {findings.map((s) => (
            <Card key={`${s.drug}|${s.symptom}|${s.signal_id || 'fx'}`} className="p-4 border-rose-700/20">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium text-slate-100 capitalize">
                    {s.headline || `${s.drug} → ${s.symptom}`}
                  </div>
                  <p className="mt-1.5 text-sm text-slate-300 leading-relaxed">
                    {s.why_it_matters || 'Pregnancy-context congenital / teratogen stratum.'}
                  </p>
                  <p className="mt-1 text-[12px] text-amber-200/90">
                    Next: {s.what_to_do || 'Triage via Signal Detail / SAR.'}
                  </p>
                  <div className="mt-2 text-[11px] text-slate-500">
                    n={s.post_count} · PRR={s.prr} · IC025={s.ic025} · EB05={s.eb05}
                    {s.fixture ? ' · demo fixture' : ''}
                  </div>
                </div>
                <div className="flex flex-col gap-1.5 items-end">
                  <Badge
                    value={s.strength || '—'}
                    className={
                      s.strength === 'STRONG'
                        ? 'bg-rose-500/15 text-rose-300 border-rose-500/30'
                        : 'bg-slate-600/20 text-slate-400 border-slate-600/30'
                    }
                  />
                  {s.signal_id ? (
                    <Link to={`/signals/${s.signal_id}`} className="text-xs text-sky-300 hover:underline">
                      Open signal →
                    </Link>
                  ) : (
                    <Link
                      to={`/signals?q=${encodeURIComponent(s.drug)}`}
                      className="text-xs text-sky-300 hover:underline capitalize"
                    >
                      Search {s.drug} →
                    </Link>
                  )}
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {(data.other_pregnancy_signals || []).length > 0 && (
        <Card className="p-4">
          <div className="text-sm text-slate-200 mb-2">Other pregnancy-context signals (non-congenital)</div>
          <div className="space-y-1.5">
            {data.other_pregnancy_signals.slice(0, 8).map((s) => (
              <div key={`${s.drug}|${s.symptom}`} className="text-sm text-slate-400 flex flex-wrap justify-between gap-2">
                <span className="capitalize text-slate-300">{s.drug} → {s.symptom}</span>
                <span className="text-[11px]">n={s.post_count} · PRR={s.prr}</span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {data.disclaimer && <p className="text-[10px] text-slate-500 leading-relaxed">{data.disclaimer}</p>}
    </div>
  );
}
