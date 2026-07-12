import { useEffect, useMemo, useState } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts';
import { api } from '../api';
import { useProject } from '../projectContext';
import { Card, CardHeader, Spinner } from '../components/ui';

export default function Divergence({ embedded = false }) {
  const { project } = useProject();
  const [pairs, setPairs] = useState([]);
  const [selected, setSelected] = useState(null);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!project?.id) return;
    api.divergencePairs(project.id).then((p) => {
      setPairs(p);
      if (p.length) setSelected(p[0]);
    }).catch(() => setPairs([]));
  }, [project?.id]);

  useEffect(() => {
    if (!project?.id || !selected) return;
    setLoading(true);
    api.divergence(project.id, selected.drug, selected.symptom)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [project?.id, selected]);

  const chartData = useMemo(() => {
    if (!data) return [];
    const smap = Object.fromEntries(data.social_timeline.map((p) => [p.date, p.count]));
    const fmap = Object.fromEntries(data.faers_timeline.map((p) => [p.date, p.count]));
    const dates = [...new Set([...Object.keys(smap), ...Object.keys(fmap)])].sort();
    return dates.map((date) => ({
      date,
      social: smap[date] || 0,
      faers: fmap[date] || 0,
    }));
  }, [data]);

  if (!project) return <Spinner label="Loading project…" />;

  return (
    <div className="space-y-6">
{!embedded && (
      <div>
        <h2 className="text-lg font-semibold text-[var(--app-text)]">FAERS Divergence Engine</h2>
        <p className="text-sm text-[var(--app-text-muted)] mt-1">
          Benchmark social listening against openFDA FAERS baselines for <strong>{project.name}</strong>.
        </p>
      </div>

)}
      <Card className="p-4">
        <CardHeader title="Drug–event pair" />
        <select
          className="app-input mt-2 max-w-md"
          value={selected ? `${selected.drug}|${selected.symptom}` : ''}
          onChange={(e) => {
            const [drug, symptom] = e.target.value.split('|');
            setSelected({ drug, symptom });
          }}
        >
          {pairs.map((p) => (
            <option key={`${p.drug}|${p.symptom}`} value={`${p.drug}|${p.symptom}`}>
              {p.drug} → {p.symptom}
            </option>
          ))}
        </select>
      </Card>

      {loading && <Spinner label="Computing divergence…" />}

      {data && !loading && (
        <>
          <div className="flex flex-wrap gap-2 text-[11px]">
            <span className="rounded px-2 py-0.5 border border-[var(--app-border)] text-[var(--app-text-muted)]">
              FAERS source: <strong className="text-[var(--app-text-secondary)]">{data.faers_source}</strong>
            </span>
            {data.faers_evidence?.report_count != null && (
              <span className="rounded px-2 py-0.5 border border-[var(--app-border)] text-[var(--app-text-muted)]">
                KB reports: {data.faers_evidence.report_count}
              </span>
            )}
            {data.faers_source === 'offline_kb' && (
              <span className="rounded px-2 py-0.5 bg-amber-500/10 text-amber-300 border border-amber-500/30">
                openFDA unreachable — using offline FAERS KB
              </span>
            )}
            {data.faers_source === 'flat_baseline' && (
              <span className="rounded px-2 py-0.5 bg-slate-500/10 text-slate-400 border border-slate-500/30">
                No FAERS/KB match — flat zero baseline
              </span>
            )}
          </div>

          {data.divergent && (
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
              {data.alert_text}
            </div>
          )}

          <div className="grid md:grid-cols-4 gap-4">
            <Card className="p-3">
              <div className="text-xs text-[var(--app-text-muted)]">Social z-score</div>
              <div className="text-2xl font-bold">{data.social_z}</div>
            </Card>
            <Card className="p-3">
              <div className="text-xs text-[var(--app-text-muted)]">FAERS z-score</div>
              <div className="text-2xl font-bold">{data.faers_z}</div>
            </Card>
            <Card className="p-3">
              <div className="text-xs text-[var(--app-text-muted)]">PRR (social)</div>
              <div className="text-2xl font-bold">{data.disproportionality?.prr ?? '—'}</div>
            </Card>
            <Card className="p-3">
              <div className="text-xs text-[var(--app-text-muted)]">EB05</div>
              <div className="text-2xl font-bold">{data.disproportionality?.eb05 ?? '—'}</div>
            </Card>
          </div>

          <Card className="p-4">
            <CardHeader title="Social vs FAERS timelines" subtitle={data.disclaimer} />
            <div className="h-80 mt-4">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="date" tick={{ fontSize: 10 }} stroke="#64748b" />
                  <YAxis tick={{ fontSize: 10 }} stroke="#64748b" />
                  <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #334155' }} />
                  <Legend />
                  <Line type="monotone" dataKey="social" name="Social mentions" stroke="#38bdf8" dot={false} />
                  <Line type="monotone" dataKey="faers" name="FAERS reports" stroke="#f59e0b" dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
