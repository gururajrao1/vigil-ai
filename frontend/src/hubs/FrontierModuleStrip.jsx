import { useEffect, useState } from 'react';
import { api } from '../api';
import { Card, CardHeader, Spinner } from '../components/ui';

// Fallback descriptors so the strip still explains the modules on older API builds.
const FALLBACK_MODULES = [
  { id: 'inspection_audit', label: 'Inspection readiness', where: 'Dashboard · Inspection & COU' },
  { id: 'cou_manager', label: 'Context of Use', where: 'Dashboard · Inspection & COU' },
  { id: 'pgx_engine', label: 'Pharmacogenomics', where: 'Signal Detail' },
  { id: 'longitudinal_biologics', label: 'Delayed-toxicity watch', where: 'Signal Detail' },
  { id: 'lot_clustering', label: 'Lot clustering', where: 'Signal Detail' },
  { id: 'benefit_risk_proact', label: 'PrOACT-URL benefit–risk', where: 'Signal Detail + below' },
];

const normalize = (m) => (typeof m === 'string' ? { id: m, label: m.replace(/_/g, ' ') } : m);

/** Single roll-up of the governance / next-gen modules and where each one lives. */
export default function FrontierModuleStrip() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let cancelled = false;
    api.frontiersSummary()
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => {
        if (cancelled) return;
        const msg = e?.message || String(e);
        setErr(/404|Not Found/i.test(msg)
          ? 'Frontiers API not on this backend yet — deploy the latest API, then refresh.'
          : msg);
      });
    return () => { cancelled = true; };
  }, []);

  const modules = (data?.modules?.length ? data.modules : FALLBACK_MODULES).map(normalize);

  return (
    <Card className="p-4">
      <CardHeader
        title="Governance modules"
        subtitle="What is running, and where to find each one in the app."
      />
      {!data && !err && <div className="mt-3"><Spinner label="Loading module status…" /></div>}
      {err && <p className="mt-3 text-sm text-rose-300">{err}</p>}
      <div className="mt-3 grid sm:grid-cols-2 lg:grid-cols-3 gap-2">
        {modules.map((m) => (
          <div
            key={m.id}
            className="rounded-md border border-slate-700/50 bg-slate-950/40 px-3 py-2"
          >
            <div className="flex items-center gap-2">
              <span
                className={`h-1.5 w-1.5 rounded-full ${data ? 'bg-emerald-400' : 'bg-slate-600'}`}
              />
              <span className="text-[13px] font-medium text-slate-100">{m.label}</span>
            </div>
            {m.summary && (
              <p className="mt-1 text-[11px] text-slate-300 leading-relaxed">{m.summary}</p>
            )}
            {m.where && <p className="mt-0.5 text-[10px] text-slate-500">{m.where}</p>}
          </div>
        ))}
      </div>
    </Card>
  );
}
