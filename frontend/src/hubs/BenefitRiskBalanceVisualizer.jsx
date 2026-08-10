import { useEffect, useState } from 'react';
import { api } from '../api';
import { Badge, Button, Card, CardHeader, Spinner } from '../components/ui';

/** PrOACT-URL / BRAT balance visualizer — efficacy % vs severe AE signal %. */
export default function BenefitRiskBalanceVisualizer({
  signalId = null,
  drug = '',
  event = '',
  strength = 'WEAK',
  postCount = 0,
  embedded = false,
}) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = () => {
    setBusy(true);
    setErr(null);
    const p = signalId
      ? api.signalBenefitRiskProact(signalId)
      : api.benefitRiskProact(drug, event, { strength, post_count: postCount });
    p.then(setData)
      .catch((e) => {
        const msg = e.message || String(e);
        setErr(
          /404|Not Found/i.test(msg)
            ? 'PrOACT benefit–risk API not on this backend yet — deploy/push the latest API, then refresh.'
            : msg,
        );
      })
      .finally(() => setBusy(false));
  };

  useEffect(() => {
    if (signalId || (drug && event)) load();
  }, [signalId, drug, event]);

  const eff = Number(data?.efficacy?.response_rate_pct) || 0;
  const risk = Number(data?.severe_ae_signal_rate_pct) || 0;
  const max = Math.max(eff, risk, 1);
  const tone = data?.tone;

  return (
    <Card className={embedded ? 'p-4' : 'p-4 border-teal-700/40'}>
      <CardHeader
        title="Benefit–risk balance (PrOACT-URL / BRAT)"
        subtitle="Efficacy response rate vs severe AE signal rate — executive trade-off scale."
        right={<Button variant="ghost" onClick={load} disabled={busy}>↻ Recompute</Button>}
      />
      {busy && !data && <div className="mt-3"><Spinner label="Computing balance…" /></div>}
      {err && <p className="mt-3 text-sm text-rose-300">{err}</p>}
      {data && (
        <div className="mt-4 space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge
              value={`Balance ${data.balance_ratio}`}
              className={
                tone === 'favourable' ? 'bg-emerald-500/15 text-emerald-200 border-emerald-500/30'
                  : tone === 'unfavourable' ? 'bg-rose-500/15 text-rose-200 border-rose-500/30'
                    : 'bg-amber-500/15 text-amber-200 border-amber-500/30'
              }
            />
            <span className="text-sm text-slate-300">{data.tradeoff}</span>
          </div>

          <div className="space-y-3">
            <Bar label={`Efficacy (${data.efficacy?.endpoint || 'response'})`} pct={eff} max={max} color="bg-teal-500/70" />
            <Bar label={`Severe AE signal (${data.primary_ae_pt})`} pct={risk} max={max} color="bg-rose-500/70" />
          </div>

          <div className="grid sm:grid-cols-2 gap-2 text-[11px] text-slate-400">
            <div>Efficacy source: {data.efficacy?.source}</div>
            <div>Formula: {data.balance_formula}</div>
          </div>

          {data.proact_dimensions && (
            <details className="text-[12px] text-slate-300">
              <summary className="cursor-pointer text-teal-300">PrOACT-URL dimensions</summary>
              <ul className="mt-2 space-y-1 list-disc pl-4">
                {Object.entries(data.proact_dimensions).map(([k, v]) => (
                  <li key={k}><span className="text-slate-500">{k}:</span> {v}</li>
                ))}
              </ul>
            </details>
          )}
          <p className="text-[10px] text-slate-600">{data.disclaimer}</p>
        </div>
      )}
    </Card>
  );
}

function Bar({ label, pct, max, color }) {
  const w = Math.max(2, (pct / max) * 100);
  return (
    <div>
      <div className="flex justify-between text-[11px] text-slate-400 mb-1">
        <span>{label}</span>
        <span className="font-mono text-slate-200">{pct.toFixed(1)}%</span>
      </div>
      <div className="h-3 rounded bg-slate-800 overflow-hidden">
        <div className={`h-full ${color}`} style={{ width: `${w}%` }} />
      </div>
    </div>
  );
}
