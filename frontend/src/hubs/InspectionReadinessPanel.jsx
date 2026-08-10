import { useEffect, useState } from 'react';
import { api } from '../api';
import { Badge, Button, Card, CardHeader, Spinner } from '../components/ui';

/** GVP Module IX inspection-readiness: SLA gauges + SJL export. */
export default function InspectionReadinessPanel({ signalId = null, embedded = false }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = () => {
    setBusy(true);
    setErr(null);
    api.inspectionPortfolio()
      .then(setData)
      .catch((e) => {
        const msg = e.message || String(e);
        setErr(
          /404|Not Found/i.test(msg)
            ? 'Inspection API not on this backend yet — deploy/push the latest API, then refresh.'
            : msg,
        );
      })
      .finally(() => setBusy(false));
  };

  useEffect(() => { load(); }, []);

  const exportSjl = async () => {
    if (!signalId) return;
    try {
      await api.downloadSjl(signalId);
    } catch (e) {
      console.error(e);
    }
  };

  const compliance = data?.compliance_rate != null ? Math.round(data.compliance_rate * 100) : null;

  return (
    <Card className={embedded ? 'p-4' : 'p-4 border-amber-700/40'}>
      <CardHeader
        title="Inspection readiness (GVP Module IX)"
        subtitle="Lead-time SLA clocks, overdue review warnings, and Signal Justification Log export."
        right={
          <div className="flex gap-2">
            {signalId && (
              <Button variant="ghost" onClick={exportSjl}>Export SJL (MD)</Button>
            )}
            <Button variant="ghost" onClick={load} disabled={busy}>↻ Refresh</Button>
          </div>
        }
      />
      {busy && !data && <div className="mt-3"><Spinner label="Loading inspection portfolio…" /></div>}
      {err && <p className="mt-3 text-sm text-rose-300">{err}</p>}
      {data && (
        <div className="mt-4 space-y-4">
          <div className="grid sm:grid-cols-4 gap-3">
            <Metric label="Open signals" value={data.n_open} />
            <Metric label="Overdue" value={data.n_overdue} accent="text-rose-300" />
            <Metric label="Justification gaps" value={data.n_justification_incomplete} accent="text-amber-300" />
            <Metric label="SLA compliance" value={compliance != null ? `${compliance}%` : '—'} accent="text-emerald-300" />
          </div>
          <div className="h-2 rounded bg-slate-800 overflow-hidden">
            <div
              className="h-full bg-emerald-500/70"
              style={{ width: `${Math.max(2, compliance ?? 0)}%` }}
            />
          </div>
          <p className="text-[11px] text-slate-500">
            Urgent SLA ≤{data.sla_urgent_days}d · Routine ≤{data.sla_routine_days}d · badge INSPECTION_RISK_WARNING when overdue
          </p>
          {(data.overdue || []).length > 0 && (
            <div>
              <div className="text-[11px] uppercase tracking-wide text-rose-300 mb-2">Overdue reviews</div>
              <ul className="space-y-1 text-sm text-slate-200 max-h-48 overflow-y-auto">
                {data.overdue.slice(0, 12).map((r) => (
                  <li key={r.signal_id} className="flex flex-wrap gap-2 items-center border-b border-slate-800/60 py-1">
                    <Badge value="INSPECTION_RISK_WARNING" className="bg-rose-500/15 text-rose-200 border-rose-500/30 text-[10px]" />
                    <span className="capitalize">{r.drug} → {r.event}</span>
                    <span className="text-slate-500 text-xs">{r.review_lead_time_days}d / SLA {r.sla_threshold_days}d</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <p className="text-[10px] text-slate-600">{data.disclaimer}</p>
        </div>
      )}
    </Card>
  );
}

function Metric({ label, value, accent = 'text-slate-100' }) {
  return (
    <div className="rounded-md border border-slate-700/50 bg-slate-950/40 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`text-xl font-mono font-semibold ${accent}`}>{value ?? '—'}</div>
    </div>
  );
}
