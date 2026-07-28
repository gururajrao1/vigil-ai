import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { api } from '../api';
import { useRefresh } from '../App';
import { useProject } from '../projectContext';
import { Badge, Button, Card, CardHeader, Spinner, StatCard } from '../components/ui';

const pct = (v) => (v === null || v === undefined ? '—' : `${(v * 100).toFixed(0)}%`);

function scoreTone(status) {
  if (status === 'healthy') return 'text-emerald-300 border-emerald-600/40 bg-emerald-500/10';
  if (status === 'needs_attention') return 'text-amber-300 border-amber-600/40 bg-amber-500/10';
  return 'text-rose-300 border-rose-600/40 bg-rose-500/10';
}

export default function Kpis({ embedded = false }) {
  const { tick, bump } = useRefresh();
  const { project } = useProject();
  const [kpis, setKpis] = useState(null);
  const [audit, setAudit] = useState([]);
  const [busyId, setBusyId] = useState(null);
  const [msg, setMsg] = useState('');

  const load = () => {
    api.kpis().then(setKpis).catch(() => setKpis(null));
    api.audit(40).then((d) => setAudit(d.entries || [])).catch(() => setAudit([]));
  };

  useEffect(() => { load(); }, [tick, project?.id]);

  const review = async (id, state) => {
    setBusyId(id);
    setMsg('');
    try {
      await api.reviewSignal(id, state);
      setMsg(`Signal #${id} marked ${state}.`);
      bump();
      load();
    } catch (e) {
      setMsg(e.message || 'Review failed');
    } finally {
      setBusyId(null);
    }
  };

  if (!kpis) return <Spinner label="Computing ops KPIs…" />;

  const ttd = kpis.time_to_detection_days || {};
  const rev = kpis.review || {};
  const spc = kpis.spc || {};
  const comp = kpis.completeness || {};
  const triage = kpis.triage_queue || [];
  const reviewedPct = kpis.signal_count
    ? Math.round(((rev.reviewed || 0) / kpis.signal_count) * 100)
    : 0;

  const leadLatency = ttd.fresh_median ?? ttd.median ?? ttd.mean ?? 0;
  const leadLatencyLabel = ttd.fresh_median != null
    ? 'median (≤30d fresh)'
    : 'median (all)';

  return (
    <div className="space-y-6">
      {!embedded && (
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="text-xl font-bold text-slate-100">Signal operations · KPIs</h2>
            <p className="text-xs text-slate-500 mt-0.5 max-w-2xl">
              Ops health for this workspace: detection latency, review backlog, actionable vs noise rates,
              alert SPC, and a triage queue you can clear without leaving the page.
            </p>
          </div>
          <div className={`rounded-xl border px-4 py-3 min-w-[160px] ${scoreTone(kpis.ops_status)}`}>
            <div className="text-[10px] uppercase tracking-wide opacity-80">Ops readiness</div>
            <div className="text-3xl font-semibold tabular-nums">{kpis.ops_score ?? 0}</div>
            <div className="text-[11px] capitalize mt-0.5">{(kpis.ops_status || '').replace('_', ' ')}</div>
          </div>
        </div>
      )}

      {(kpis.ops_notes || []).length > 0 && (
        <Card className="p-4 border-sky-700/40 bg-sky-950/20">
          <div className="text-[10px] uppercase tracking-wide text-sky-400 mb-2">What this means right now</div>
          <ul className="space-y-1.5 text-sm text-slate-300">
            {kpis.ops_notes.map((n) => (
              <li key={n} className="flex gap-2">
                <span className="text-sky-500 shrink-0">•</span>
                <span>{n}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {/* Primary KPIs — lead with actionable latency + backlog */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          label="Detection latency"
          value={`${leadLatency}d`}
          sub={`${leadLatencyLabel} · mean ${ttd.mean ?? 0}d · n=${ttd.n ?? 0}`}
          accent="text-sky-300"
        />
        <StatCard
          label="Review backlog"
          value={rev.unreviewed ?? 0}
          sub={`${pct(rev.backlog_rate)} of ${kpis.signal_count ?? 0} signals`}
          accent="text-amber-300"
        />
        <StatCard
          label="Actionable rate"
          value={pct(rev.actionable_rate)}
          sub={rev.reviewed ? `confirmed of ${rev.reviewed} reviewed` : 'needs HCP reviews'}
          accent="text-emerald-300"
        />
        <StatCard
          label="False-positive ratio"
          value={pct(rev.false_positive_ratio)}
          sub={rev.reviewed ? `dismissed of ${rev.reviewed} reviewed` : 'needs HCP reviews'}
          accent="text-rose-300"
        />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="SDR signals" value={kpis.sdr_count ?? 0}
                  sub={`${kpis.strong_count ?? 0} STRONG · ${kpis.spike_count ?? 0} spiking`} accent="text-violet-300" />
        <StatCard label="Confirmed" value={rev.confirmed ?? 0} accent="text-emerald-300" />
        <StatCard label="Dismissed" value={rev.dismissed ?? 0} accent="text-rose-300" />
        <StatCard label="Well-documented" value={pct(comp.well_documented_rate)}
                  sub={`${comp.well_documented ?? 0} · avg completeness ${(comp.mean ?? 0).toFixed(2)}`} accent="text-lime-300" />
      </div>

      {/* Review progress */}
      <Card className="p-4">
        <div className="flex items-center justify-between gap-3 mb-2">
          <CardHeader title="Review funnel" subtitle="Confirm / dismiss unlocks actionable & FP ratios" />
          <span className="text-xs text-slate-400 tabular-nums">{reviewedPct}% reviewed</span>
        </div>
        <div className="h-2 rounded-full bg-slate-800 overflow-hidden">
          <div
            className="h-full bg-gradient-to-r from-emerald-500 via-amber-400 to-rose-500"
            style={{
              width: `${Math.max(2, reviewedPct)}%`,
              opacity: reviewedPct ? 1 : 0.25,
            }}
          />
        </div>
        <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-slate-500">
          <span className="text-emerald-400">{rev.confirmed ?? 0} confirmed</span>
          <span className="text-rose-400">{rev.dismissed ?? 0} dismissed</span>
          <span>{rev.unreviewed ?? 0} unreviewed</span>
          <span className="text-slate-600">·</span>
          <span>{rev.note}</span>
        </div>
      </Card>

      {/* Triage queue — the useful deliverable */}
      <Card className="overflow-hidden">
        <div className="px-4 pt-4 flex flex-wrap items-end justify-between gap-2">
          <CardHeader
            title="Triage queue"
            subtitle="SDR / STRONG / spike only — Confirm real pairs here. WEAK noise stays on Signals (unchanged)."
          />
          <Link to="/signals?strength=STRONG" className="text-[11px] text-sky-400 hover:underline">
            Open full signals →
          </Link>
        </div>
        {msg && <p className="px-4 text-xs text-sky-300">{msg}</p>}
        <div className="mt-2 app-table-scroll">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-wide text-slate-500 border-b border-slate-800">
                <th className="px-4 py-2">Signal</th>
                <th className="px-4 py-2">Why now</th>
                <th className="px-4 py-2">PRR</th>
                <th className="px-4 py-2">Posts</th>
                <th className="px-4 py-2">Action</th>
              </tr>
            </thead>
            <tbody>
              {triage.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-slate-500">
                    No unreviewed SDR / STRONG / spike items. WEAK backlog (if any) is still on Signals.
                  </td>
                </tr>
              )}
              {triage.map((row) => (
                <tr key={row.id} className="border-b border-slate-800/60 hover:bg-slate-900/40">
                  <td className="px-4 py-2.5">
                    <Link to={`/signals/${row.id}`} className="text-slate-100 hover:text-sky-300 font-medium">
                      {row.drug} → {row.symptom}
                    </Link>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {row.sdr_flag && <Badge value="SDR" className="bg-rose-500/15 text-rose-300 border-rose-500/30" />}
                      {row.strength === 'STRONG' && <Badge value="STRONG" className="bg-violet-500/15 text-violet-300 border-violet-500/30" />}
                      {row.spike_flag && <Badge value="SPIKE" className="bg-amber-500/15 text-amber-300 border-amber-500/30" />}
                      {row.severity && <Badge value={row.severity} className="bg-slate-800 text-slate-300 border-slate-700" />}
                    </div>
                  </td>
                  <td className="px-4 py-2.5 text-xs text-slate-400 max-w-[220px]">{row.why}</td>
                  <td className="px-4 py-2.5 tabular-nums text-slate-300">{row.prr}</td>
                  <td className="px-4 py-2.5 tabular-nums text-slate-400">{row.post_count}</td>
                  <td className="px-4 py-2.5">
                    <div className="flex gap-1.5">
                      <Button
                        variant="primary"
                        disabled={busyId === row.id}
                        onClick={() => review(row.id, 'confirmed')}
                        className="!px-2 !py-1 text-[11px]"
                      >
                        Confirm
                      </Button>
                      <Button
                        variant="danger"
                        disabled={busyId === row.id}
                        onClick={() => review(row.id, 'dismissed')}
                        className="!px-2 !py-1 text-[11px]"
                      >
                        Dismiss
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* SPC */}
      <Card className="p-2">
        <CardHeader
          title="SPC — daily alert frequency"
          subtitle={`${spc.interpretation || ''} · mean ${spc.mean ?? 0} · UCL ${spc.ucl ?? 0} · LCL ${spc.lcl ?? 0} (±3σ)`}
        />
        <div className="h-64 mt-2">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={spc.series || []}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#64748b' }} tickFormatter={(d) => d?.slice(5)} />
              <YAxis tick={{ fontSize: 10, fill: '#64748b' }} allowDecimals={false} />
              <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }} />
              <ReferenceLine y={spc.ucl} stroke="#f43f5e" strokeDasharray="4 4" label={{ value: 'UCL', fill: '#f43f5e', fontSize: 10, position: 'right' }} />
              <ReferenceLine y={spc.mean} stroke="#64748b" strokeDasharray="2 2" label={{ value: 'x̄', fill: '#94a3b8', fontSize: 10, position: 'right' }} />
              <ReferenceLine y={spc.lcl} stroke="#334155" strokeDasharray="4 4" />
              <Line type="monotone" dataKey="count" stroke="#38bdf8" strokeWidth={2}
                    dot={{ r: 3 }} activeDot={{ r: 5 }} name="Alerts/day" />
            </LineChart>
          </ResponsiveContainer>
        </div>
        {(spc.breaches || []).length > 0 && (
          <div className="px-4 pb-3 text-xs text-rose-300/90">
            Out-of-control days: {(spc.breaches || []).map((b) => `${b.date.slice(5)} (${b.count})`).join(' · ')}
          </div>
        )}
        {(spc.series || []).length < 3 && (
          <p className="px-4 pb-3 text-xs text-slate-500">
            Control limits become meaningful as more alert-days accumulate (scheduler / ongoing ingest).
          </p>
        )}
      </Card>

      {/* Latency caveat + glossary */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card className="p-4">
          <CardHeader title="Detection latency detail" subtitle={ttd.note} />
          <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
            <div><div className="text-[10px] uppercase text-slate-500">Median</div><div className="text-slate-200 tabular-nums">{ttd.median ?? 0}d</div></div>
            <div><div className="text-[10px] uppercase text-slate-500">P90</div><div className="text-slate-200 tabular-nums">{ttd.p90 ?? 0}d</div></div>
            <div><div className="text-[10px] uppercase text-slate-500">Mean (all)</div><div className="text-slate-200 tabular-nums">{ttd.mean ?? 0}d</div></div>
            <div><div className="text-[10px] uppercase text-slate-500">Fresh ≤30d</div>
              <div className="text-slate-200 tabular-nums">
                {ttd.fresh_median != null ? `${ttd.fresh_median}d med · n=${ttd.fresh_n}` : '—'}
              </div>
            </div>
          </div>
        </Card>
        <Card className="p-4">
          <CardHeader title="Metric glossary" subtitle="What each KPI is measuring" />
          <dl className="mt-3 space-y-2 text-xs text-slate-400">
            {Object.entries(kpis.glossary || {}).map(([k, v]) => (
              <div key={k}>
                <dt className="text-slate-200 font-medium uppercase tracking-wide text-[10px]">{k}</dt>
                <dd className="mt-0.5">{v}</dd>
              </div>
            ))}
          </dl>
        </Card>
      </div>

      {/* Audit */}
      <Card className="overflow-hidden">
        <CardHeader title="Audit trail" subtitle={`Append-only compliance log · ${kpis.audit_trail_entries ?? 0} entries`} />
        <div className="mt-3 max-h-72 overflow-y-auto app-table-scroll">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-slate-900">
              <tr className="text-left text-xs uppercase tracking-wide text-slate-400 border-b border-slate-800">
                <th className="px-4 py-2">Time</th>
                <th className="px-4 py-2">Actor</th>
                <th className="px-4 py-2">Action</th>
                <th className="px-4 py-2">Detail</th>
              </tr>
            </thead>
            <tbody>
              {audit.length === 0 && (
                <tr><td colSpan={4} className="px-4 py-6 text-center text-slate-500">No audit entries yet. Confirm/dismiss a signal to generate one.</td></tr>
              )}
              {audit.map((a) => (
                <tr key={a.id} className="border-b border-slate-800/50">
                  <td className="px-4 py-2 text-xs text-slate-500 whitespace-nowrap">{a.created_at?.replace('T', ' ').slice(0, 16)}</td>
                  <td className="px-4 py-2 text-xs text-slate-300">{a.actor}</td>
                  <td className="px-4 py-2 text-xs"><span className="rounded bg-slate-800 border border-slate-700 px-2 py-0.5 text-slate-300">{a.action}</span></td>
                  <td className="px-4 py-2 text-xs text-slate-400">{a.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
