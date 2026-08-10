import { useEffect, useState } from 'react';
import { api } from '../api';
import { Badge, Button, Card, CardHeader, Spinner } from '../components/ui';

/** FDA AI/ML Context-of-Use + Model Credibility Index scorecard. */
export default function COUGovernanceScorecard({ embedded = false }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = () => {
    setBusy(true);
    api.governanceCredibility()
      .then(setData)
      .catch((e) => {
        const msg = e.message || String(e);
        setErr(
          /404|Not Found/i.test(msg)
            ? 'COU/credibility API not on this backend yet — deploy/push the latest API, then refresh.'
            : msg,
        );
      })
      .finally(() => setBusy(false));
  };

  useEffect(() => { load(); }, []);

  const idx = data?.model_credibility_index;
  const band = data?.credibility_band;
  const bm = data?.benchmark || {};
  const cou = data?.cou || {};
  // Prefer the rationale payload; fall back to plain strings on older API builds.
  const boundaries = cou.not_validated_rationale?.length
    ? cou.not_validated_rationale
    : (cou.not_validated_for || []).map((item) => ({ item }));

  return (
    <Card className={embedded ? 'p-4' : 'p-4 border-indigo-700/40'}>
      <CardHeader
        title="FDA model credibility & Context of Use"
        subtitle="COU boundaries + offline BioIE (BC5CDR / NCBI) precision / recall / F1 → Credibility Index."
        right={<Button variant="ghost" onClick={load} disabled={busy}>↻ Re-score</Button>}
      />
      {busy && !data && <div className="mt-3"><Spinner label="Running credibility scorecard…" /></div>}
      {err && <p className="mt-3 text-sm text-rose-300">{err}</p>}
      {data && (
        <div className="mt-4 space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="text-4xl font-mono font-bold text-indigo-200">{idx?.toFixed?.(1) ?? idx}</div>
            <div>
              <div className="text-[11px] uppercase tracking-wide text-slate-500">Model Credibility Index</div>
              <Badge
                value={band || '—'}
                className={
                  band === 'high' ? 'bg-emerald-500/15 text-emerald-200 border-emerald-500/30'
                    : band === 'moderate' ? 'bg-amber-500/15 text-amber-200 border-amber-500/30'
                      : 'bg-slate-600/30 text-slate-300 border-slate-600/40'
                }
              />
            </div>
          </div>
          <div className="grid sm:grid-cols-3 gap-3 text-center">
            <Stat label="Precision" value={bm.precision} />
            <Stat label="Recall" value={bm.recall} />
            <Stat label="F1" value={bm.f1} />
          </div>
          <div className="rounded-md border border-emerald-700/30 bg-emerald-500/5 p-3 text-[12px]">
            <div className="text-[10px] uppercase text-emerald-300 mb-1">
              Validated for (demo scope)
            </div>
            <ul className="list-disc pl-4 space-y-1 text-slate-200">
              {(cou.validated_for || []).map((x) => <li key={x}>{x}</li>)}
            </ul>
          </div>

          <div className="rounded-md border border-rose-600/40 bg-rose-500/10 p-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <div className="text-[11px] uppercase tracking-wide text-rose-200 font-semibold">
                Not validated for — hard boundaries
              </div>
              <Badge
                value="Human decision required"
                className="bg-rose-500/20 text-rose-100 border-rose-400/40 text-[10px]"
              />
            </div>
            {cou.boundary_stance && (
              <p className="mt-1.5 text-[11px] text-rose-100/80 leading-relaxed">
                {cou.boundary_stance}
              </p>
            )}
            <ul className="mt-2 space-y-2">
              {boundaries.map((b) => (
                <li key={b.item} className="border-t border-rose-500/20 pt-2 first:border-t-0 first:pt-0">
                  <div className="text-[12px] font-semibold text-rose-100">{b.item}</div>
                  {b.why && (
                    <p className="mt-0.5 text-[11px] text-slate-300 leading-relaxed">{b.why}</p>
                  )}
                  {b.human_control && (
                    <p className="mt-0.5 text-[11px] text-amber-200/90">
                      Stays with: {b.human_control}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          </div>
          <p className="text-[11px] text-slate-400">{cou.intended_use}</p>
          <p className="text-[10px] text-slate-600">{data.disclaimer}</p>
        </div>
      )}
    </Card>
  );
}

function Stat({ label, value }) {
  const v = value == null ? '—' : Number(value).toFixed(3);
  return (
    <div className="rounded-md border border-slate-700/50 bg-slate-950/40 px-3 py-2">
      <div className="text-[10px] uppercase text-slate-500">{label}</div>
      <div className="text-lg font-mono text-slate-100">{v}</div>
    </div>
  );
}
