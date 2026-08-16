import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { api } from '../api';
import { useRefresh } from '../App';
import { useProject } from '../projectContext';
import { Card, CardHeader, StatCard, Spinner } from '../components/ui';

const SENTIMENT_COLORS = { NEGATIVE: '#f43f5e', NEUTRAL: '#64748b', POSITIVE: '#10b981' };
const STRENGTH_COLORS = { STRONG: '#f43f5e', MODERATE: '#f59e0b', WEAK: '#64748b' };

export default function Overview({ embedded = false }) {
  const nav = useNavigate();
  const { tick } = useRefresh();
  const { project } = useProject();
  const [stats, setStats] = useState(null);
  const [overview, setOverview] = useState(null);

  useEffect(() => {
    setStats(null);
    api.stats().then(setStats).catch(() => setStats(null));
    api.overview().then(setOverview).catch(() => setOverview(null));
  }, [tick, project?.id]);

  const goSignals = (params) => {
    const q = new URLSearchParams(params).toString();
    nav(`/signals?${q}`);
  };

  if (!stats) return <Spinner label="Loading dashboard…" />;

  const empty = stats.total_posts === 0;
  // Fold legacy lowercase FAERS labels if an older API host still returns them.
  const sentimentMerged = {};
  Object.entries(stats.sentiment_distribution || {}).forEach(([k, v]) => {
    const key = String(k || 'NEUTRAL').toUpperCase();
    sentimentMerged[key] = (sentimentMerged[key] || 0) + Number(v || 0);
  });
  const sentimentData = Object.entries(sentimentMerged).map(([k, v]) => ({ name: k, value: v }));
  const strengthData = Object.entries(stats.strength_distribution || {}).map(([k, v]) => ({ name: k, value: v }));
  const drugData = (stats.top_drugs || []).map(([name, value]) => ({ name, value }));
  const symptomData = (stats.top_symptoms || []).map(([name, value]) => ({ name, value }));
  const regionData = Object.entries(stats.region_distribution || {}).map(([name, value]) => ({ name, value })).sort((a, b) => b.value - a.value);
  // Chart: top 12 SOCs; card uses stats.soc_count (full distinct — never truncate server-side).
  const socData = Object.entries(stats.soc_distribution || {})
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 12);
  const langData = Object.entries(stats.language_distribution || {}).map(([name, value]) => ({ name, value }));
  const platformData = (stats.top_platforms
    || Object.entries(stats.platform_distribution || {}).sort((a, b) => b[1] - a[1]).slice(0, 8)
  ).map(([name, value]) => ({ name, value }));
  const REGION_COLORS = ['#38bdf8', '#a78bfa', '#f43f5e', '#10b981', '#f59e0b', '#ec4899', '#22d3ee'];

  const sev = stats.severity_distribution || {};
  const criticalN = sev.Critical || 0;
  const priorityN = stats.priority_signals ?? (criticalN + (sev.High || 0));
  const socCount = stats.soc_count ?? Object.keys(stats.soc_distribution || {}).length;
  const socCatalog = stats.soc_catalog_size || 27;
  const reg = stats.regulatory || {};
  const faersHeavy = (reg.faers_posts || 0) > Math.max(100, (stats.total_posts || 0) * 0.4);

  return (
    <div className="space-y-6">
      {empty && (
        <Card className="p-4 border-sky-600/40 bg-sky-600/10 text-sky-200 text-sm">
          No data yet — click <b>Load demo corpus</b> in the top bar to ingest a 21-day patient-post dataset,
          then <b>Stream batch</b> to simulate real-time arrivals.
        </Card>
      )}

      {faersHeavy && (
        <Card className="p-3 border-amber-600/30 bg-amber-600/10 text-amber-100/90 text-xs leading-relaxed">
          Corpus is FAERS/MAUDE-heavy ({reg.faers_posts || 0} FAERS · {reg.maude_posts || 0} MAUDE · {reg.social_posts ?? '—'} social).
          {' '}Translated posts only move when social NLP translates non-English text — regulatory ICSRs stay English.
          {' '}Macro-regions cap around 7 buckets; watch <b>Countries</b> and <b>FAERS posts</b> for geographic/corpus growth.
        </Card>
      )}

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        <StatCard label="Posts ingested" value={stats.total_posts} sub={`${stats.processed_posts} processed`} />
        <StatCard label="Adverse events" value={stats.ae_posts} sub={`${((stats.ae_rate || 0) * 100).toFixed(1)}% AE rate`} accent="text-rose-300" />
        <StatCard label="Safety signals" value={stats.signal_count} sub={`${stats.strength_distribution?.STRONG || 0} strong`} accent="text-sky-300" />
        <StatCard label="Active alerts" value={stats.alert_count} accent="text-amber-300" />
        <StatCard label="Spikes detected" value={stats.spike_count} sub="emerging trends" accent="text-violet-300" />
        <StatCard label="Countries" value={stats.country_count || 0} sub={`${stats.language_count || 0} languages`} accent="text-emerald-300" />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          label="Priority signals"
          value={priorityN}
          sub={`${criticalN} Critical · ${sev.High || 0} High`}
          accent="text-rose-400"
        />
        <StatCard
          label="Translated posts"
          value={stats.translated_posts || 0}
          sub={`social NLP · ${stats.non_english_posts || 0} non-EN`}
          accent="text-sky-300"
        />
        <StatCard
          label="FAERS posts"
          value={reg.faers_posts ?? 0}
          sub={`${reg.maude_posts || 0} MAUDE · ${reg.social_posts ?? 0} social`}
          accent="text-violet-300"
        />
        <StatCard
          label="Organ classes"
          value={socCount}
          sub={`of ~${socCatalog} MedDRA SOCs`}
          accent="text-amber-300"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card className="lg:col-span-2 p-2">
          <CardHeader title="Signal volume over time" subtitle="Daily total posts, adverse events, and negative-sentiment mentions" />
          <div className="h-64 mt-2">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={overview?.series || []} margin={{ top: 10, right: 20, left: -10, bottom: 0 }}>
                <defs>
                  <linearGradient id="gTotal" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#38bdf8" stopOpacity={0.5} />
                    <stop offset="100%" stopColor="#38bdf8" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="gAe" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#f43f5e" stopOpacity={0.5} />
                    <stop offset="100%" stopColor="#f43f5e" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#64748b' }} tickFormatter={(d) => d?.slice(5)} />
                <YAxis tick={{ fontSize: 10, fill: '#64748b' }} />
                <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Area type="monotone" dataKey="total" stroke="#38bdf8" fill="url(#gTotal)" name="Total posts" />
                <Area type="monotone" dataKey="ae" stroke="#f43f5e" fill="url(#gAe)" name="Adverse events" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card className="p-2">
          <CardHeader title="Sentiment mix" subtitle="NEGATIVE / NEUTRAL / POSITIVE (case-normalized)" />
          <div className="h-64 mt-2">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={sentimentData} dataKey="value" nameKey="name" innerRadius={45} outerRadius={80} paddingAngle={3}>
                  {sentimentData.map((e) => <Cell key={e.name} fill={SENTIMENT_COLORS[e.name] || '#64748b'} />)}
                </Pie>
                <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card className="p-2">
          <CardHeader title="Corpus by source" subtitle="FAERS/MAUDE vs social — folded feed variants" />
          <div className="h-64 mt-2">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={platformData} layout="vertical" margin={{ left: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 10, fill: '#64748b' }} />
                <YAxis type="category" dataKey="name" tick={{ fontSize: 10, fill: '#94a3b8' }} width={90} />
                <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }} />
                <Bar dataKey="value" fill="#38bdf8" radius={[0, 4, 4, 0]} name="Posts" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card className="p-2">
          <CardHeader title="Top implicated drugs" subtitle="Click a bar → Safety Signals filtered to that product" />
          <div className="h-64 mt-2">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={drugData} layout="vertical" margin={{ left: 30 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 10, fill: '#64748b' }} />
                <YAxis type="category" dataKey="name" tick={{ fontSize: 10, fill: '#94a3b8' }} width={90} />
                <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }} />
                <Bar
                  dataKey="value"
                  fill="#38bdf8"
                  radius={[0, 4, 4, 0]}
                  name="AE reports"
                  cursor="pointer"
                  onClick={(d) => {
                    const name = d?.name || d?.payload?.name;
                    if (name) goSignals({ drug: name, tab: 'detect' });
                  }}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card className="p-2">
          <CardHeader title="Top implicated adverse events" subtitle="Click a bar → Detect grid filtered to that AE (searchEvent deep-link)" />
          <div className="h-64 mt-2">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={symptomData} layout="vertical" margin={{ left: 30 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 10, fill: '#64748b' }} />
                <YAxis type="category" dataKey="name" tick={{ fontSize: 10, fill: '#94a3b8' }} width={100} />
                <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }} />
                <Bar
                  dataKey="value"
                  fill="#f43f5e"
                  radius={[0, 4, 4, 0]}
                  name="AE reports"
                  cursor="pointer"
                  onClick={(d) => {
                    const name = d?.name || d?.payload?.name;
                    if (!name) return;
                    goSignals({
                      searchEvent: String(name).toUpperCase(),
                      symptom: name,
                      tab: 'detect',
                    });
                  }}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card className="p-2">
          <CardHeader title="Signal strength distribution" subtitle="Click a tier → filtered signal grid" />
          <div className="h-64 mt-2">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={strengthData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="name" tick={{ fontSize: 11, fill: '#94a3b8' }} />
                <YAxis tick={{ fontSize: 10, fill: '#64748b' }} />
                <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }} />
                <Bar dataKey="value" radius={[4, 4, 0, 0]} name="Signals" cursor="pointer"
                  onClick={(d) => d?.name && goSignals({ strength: d.name })}>
                  {strengthData.map((e) => <Cell key={e.name} fill={STRENGTH_COLORS[e.name] || '#64748b'} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card className="p-2">
          <CardHeader title="MedDRA System Organ Classes" subtitle="Click a SOC → filtered signal grid" />
          <div className="h-64 mt-2">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={socData} layout="vertical" margin={{ left: 10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 10, fill: '#64748b' }} allowDecimals={false} />
                <YAxis type="category" dataKey="name" tick={{ fontSize: 9, fill: '#94a3b8' }} width={130} />
                <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }} />
                <Bar dataKey="value" fill="#a78bfa" radius={[0, 4, 4, 0]} name="Signals" cursor="pointer"
                  onClick={(d) => d?.name && goSignals({ soc: d.name })} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      {/* Worldwide row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card className="p-2">
          <CardHeader title="Geographic spread" subtitle="Click a region → filtered signals" />
          <div className="h-64 mt-2">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={regionData}
                  dataKey="value"
                  nameKey="name"
                  innerRadius={40}
                  outerRadius={80}
                  paddingAngle={3}
                  cursor="pointer"
                  onClick={(_, i) => regionData[i]?.name && goSignals({ region: regionData[i].name })}
                >
                  {regionData.map((e, i) => <Cell key={e.name} fill={REGION_COLORS[i % REGION_COLORS.length]} />)}
                </Pie>
                <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }} />
                <Legend wrapperStyle={{ fontSize: 10 }} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card className="p-2 lg:col-span-2">
          <CardHeader title="Languages detected" subtitle="Auto-translated to English" />
          <div className="h-64 mt-2">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={langData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="name" tick={{ fontSize: 9, fill: '#94a3b8' }} interval={0} angle={-20} textAnchor="end" height={50} />
                <YAxis tick={{ fontSize: 10, fill: '#64748b' }} allowDecimals={false} />
                <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }} />
                <Bar dataKey="value" fill="#22d3ee" radius={[4, 4, 0, 0]} name="Posts" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>
    </div>
  );
}
