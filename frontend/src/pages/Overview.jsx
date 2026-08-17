import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { api } from '../api';
import { useRefresh } from '../App';
import { useProject } from '../projectContext';
import { Button, Card, CardHeader, StatCard, Spinner } from '../components/ui';

const SENTIMENT_COLORS = { NEGATIVE: '#f43f5e', NEUTRAL: '#64748b', POSITIVE: '#10b981' };
const STRENGTH_COLORS = { STRONG: '#f43f5e', MODERATE: '#f59e0b', WEAK: '#64748b' };

export default function Overview({ embedded = false }) {
  const nav = useNavigate();
  const { tick, bump } = useRefresh();
  const { project } = useProject();
  const [stats, setStats] = useState(null);
  const [overview, setOverview] = useState(null);
  const [loadErr, setLoadErr] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setStats(null);
    setOverview(null);
    setLoadErr(null);
    setLoading(true);
    api.stats()
      .then((d) => { if (!cancelled) setStats(d); })
      .catch((e) => {
        if (!cancelled) setLoadErr(e?.message || 'Dashboard failed to load');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    api.overview()
      .then((d) => { if (!cancelled) setOverview(d); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [tick, project?.id]);

  const goSignals = (params) => {
    const q = new URLSearchParams(params).toString();
    nav(`/signals?${q}`);
  };

  if (loading && !stats) return <Spinner label="Loading dashboard…" />;
  if (loadErr && !stats) {
    return (
      <Card className="p-4 border-rose-600/40 bg-rose-600/10 text-rose-200 text-sm space-y-3">
        <div>Dashboard request failed: {loadErr}</div>
        <div className="text-rose-300/80">
          Your corpus is still on the server — this is a load error, not data loss.
        </div>
        <Button type="button" size="sm" variant="outline" onClick={() => bump()}>
          Retry dashboard
        </Button>
      </Card>
    );
  }
  if (!stats) return <Spinner label="Loading dashboard…" />;

  const empty = stats.total_posts === 0;
  const sentimentData = Object.entries(stats.sentiment_distribution || {}).map(([k, v]) => ({ name: k, value: v }));
  const strengthData = Object.entries(stats.strength_distribution || {}).map(([k, v]) => ({ name: k, value: v }));
  const drugData = (stats.top_drugs || []).map(([name, value]) => ({ name, value }));
  const symptomData = (stats.top_symptoms || []).map(([name, value]) => ({ name, value }));
  const regionData = Object.entries(stats.region_distribution || {}).map(([name, value]) => ({ name, value })).sort((a, b) => b.value - a.value);
  const socData = Object.entries(stats.soc_distribution || {}).map(([name, value]) => ({ name, value }));
  const langData = Object.entries(stats.language_distribution || {}).map(([name, value]) => ({ name, value }));
  const REGION_COLORS = ['#38bdf8', '#a78bfa', '#f43f5e', '#10b981', '#f59e0b', '#ec4899', '#22d3ee'];

  return (
    <div className="space-y-6">
      {empty && (
        <Card className="p-4 border-sky-600/40 bg-sky-600/10 text-sky-200 text-sm">
          No data yet — click <b>Load demo corpus</b> in the top bar to ingest a 21-day patient-post dataset,
          then <b>Stream batch</b> to simulate real-time arrivals.
        </Card>
      )}

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        <StatCard label="Posts ingested" value={stats.total_posts} sub={`${stats.processed_posts} processed`} />
        <StatCard label="Adverse events" value={stats.ae_posts} sub={`${(stats.ae_rate * 100).toFixed(1)}% AE rate`} accent="text-rose-300" />
        <StatCard label="Safety signals" value={stats.signal_count} sub={`${stats.strength_distribution?.STRONG || 0} strong`} accent="text-sky-300" />
        <StatCard label="Active alerts" value={stats.alert_count} accent="text-amber-300" />
        <StatCard label="Spikes detected" value={stats.spike_count} sub="emerging trends" accent="text-violet-300" />
        <StatCard label="Countries" value={stats.country_count || 0} sub={`${stats.language_count || 0} languages`} accent="text-emerald-300" />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Critical signals" value={stats.severity_distribution?.Critical || 0} sub="high-severity" accent="text-rose-400" />
        <StatCard label="Translated posts" value={stats.translated_posts || 0} sub="non-English → EN" accent="text-sky-300" />
        <StatCard label="Regions covered" value={Object.keys(stats.region_distribution || {}).length} sub="worldwide reach" accent="text-violet-300" />
        <StatCard label="Organ classes" value={Object.keys(stats.soc_distribution || {}).length} sub="MedDRA SOC" accent="text-amber-300" />
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
          <CardHeader title="Sentiment mix" subtitle="Across all processed posts" />
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
                    // Deep-link token for the Detect grid (searchEvent) + symptom filter for API
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
