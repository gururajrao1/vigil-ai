import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { Badge, Card, CardHeader, Spinner, StatCard } from '../components/ui';

const TYPE_BADGE = {
  connector: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  surrogate: 'bg-slate-600/30 text-slate-300 border-slate-600/40',
};
const MODALITY_BADGE = 'bg-sky-500/10 text-sky-300 border-sky-500/20';

function SourceCard({ s }) {
  const live = s.status === 'live';
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="font-medium text-slate-100 text-sm">{s.name}</div>
        <Badge value={s.type} className={TYPE_BADGE[s.type] || ''} />
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5 text-[11px]">
        <Badge value={s.region} className="bg-slate-700/40 text-slate-300 border-slate-600/40" />
        <Badge value={s.modality} className={MODALITY_BADGE} />
        <Badge value={s.product} className="bg-violet-500/10 text-violet-300 border-violet-500/20" />
        {s.type === 'connector' && (
          <Badge value={live ? (s.key_required ? 'live · key' : 'live · no key') : (s.status || 'reference')}
                 className={live ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' : 'bg-amber-500/15 text-amber-300 border-amber-500/30'} />
        )}
      </div>
      {s.endpoint && <div className="mt-2 text-[11px] font-mono text-slate-500 truncate">{s.endpoint}</div>}
      {s.note && <div className="mt-1 text-xs text-slate-400">{s.note}</div>}
    </div>
  );
}

/* VigiLyze-style exploration over OUR OWN signal store. */
function Explorer() {
  const nav = useNavigate();
  const [signals, setSignals] = useState(null);
  const [product, setProduct] = useState('ALL');
  const [region, setRegion] = useState('ALL');
  const [soc, setSoc] = useState('ALL');
  const [q, setQ] = useState('');

  useEffect(() => { api.signals({ limit: 80, sort: 'prr' }).then((d) => setSignals(d.signals)).catch(() => setSignals([])); }, []);

  const { regions, socs } = useMemo(() => {
    const r = new Set(), sc = new Set();
    (signals || []).forEach((s) => {
      Object.keys(s.regions || {}).forEach((x) => r.add(x));
      if (s.meddra?.soc) sc.add(s.meddra.soc);
    });
    return { regions: ['ALL', ...[...r].sort()], socs: ['ALL', ...[...sc].sort()] };
  }, [signals]);

  const rows = useMemo(() => (signals || []).filter((s) => {
    if (product !== 'ALL' && (s.product_type || 'drug') !== product) return false;
    if (region !== 'ALL' && !(region in (s.regions || {}))) return false;
    if (soc !== 'ALL' && s.meddra?.soc !== soc) return false;
    if (q && !(`${s.drug} ${s.symptom} ${s.meddra?.pt || ''}`.toLowerCase().includes(q.toLowerCase()))) return false;
    return true;
  }).sort((a, b) => (b.eb05 || 0) - (a.eb05 || 0)), [signals, product, region, soc, q]);

  if (!signals) return <Spinner />;

  return (
    <Card className="p-4">
      <CardHeader title="VigiLyze-style exploration" subtitle="Top 80 pairs by PRR over VigilAI's own store (emulates UMC VigiLyze; VigiBase itself is licensed). Full register remains in Detect." />
      <div className="mt-3 flex flex-wrap gap-2">
        <select value={product} onChange={(e) => setProduct(e.target.value)} className="rounded-lg bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs text-slate-200">
          {['ALL', 'drug', 'device', 'combination'].map((p) => <option key={p} value={p}>{p === 'ALL' ? 'All products' : p}</option>)}
        </select>
        <select value={region} onChange={(e) => setRegion(e.target.value)} className="rounded-lg bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs text-slate-200">
          {regions.map((r) => <option key={r} value={r}>{r === 'ALL' ? 'All regions' : r}</option>)}
        </select>
        <select value={soc} onChange={(e) => setSoc(e.target.value)} className="rounded-lg bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs text-slate-200">
          {socs.map((s) => <option key={s} value={s}>{s === 'ALL' ? 'All SOCs' : s}</option>)}
        </select>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search product / event…"
               className="flex-1 min-w-[160px] rounded-lg bg-slate-800 border border-slate-700 px-3 py-1.5 text-xs text-slate-200 placeholder-slate-500" />
      </div>
      <div className="mt-3 app-table-scroll">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-slate-400 border-b border-slate-800">
              <th className="px-3 py-2">Product → Event</th>
              <th className="px-3 py-2">Type</th>
              <th className="px-3 py-2">PRR</th>
              <th className="px-3 py-2">EB05</th>
              <th className="px-3 py-2">IC025</th>
              <th className="px-3 py-2">N</th>
              <th className="px-3 py-2">SDR</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && <tr><td colSpan={7} className="px-3 py-6 text-center text-slate-500">No signals match. Load the demo corpus.</td></tr>}
            {rows.slice(0, 60).map((s) => (
              <tr key={s.id} onClick={() => nav(`/signals/${s.id}`)} className="border-b border-slate-800/50 hover:bg-slate-800/40 cursor-pointer">
                <td className="px-3 py-2 capitalize text-slate-100">{s.drug} <span className="text-slate-500">→</span> {s.meddra?.pt || s.symptom}</td>
                <td className="px-3 py-2"><Badge value={s.product_type || 'drug'} className={(s.product_type === 'device') ? 'bg-amber-500/15 text-amber-300 border-amber-500/30' : 'bg-sky-500/10 text-sky-300 border-sky-500/20'} /></td>
                <td className="px-3 py-2 font-mono text-slate-200">{s.prr?.toFixed(1)}</td>
                <td className="px-3 py-2 font-mono text-slate-300">{s.eb05?.toFixed(2) ?? '—'}</td>
                <td className="px-3 py-2 font-mono text-slate-400">{s.ic025?.toFixed(2) ?? '—'}</td>
                <td className="px-3 py-2 text-slate-300">{s.post_count}</td>
                <td className="px-3 py-2">{s.sdr_flag ? <Badge value="SDR" className="bg-rose-500/15 text-rose-300 border-rose-500/30" /> : <span className="text-slate-600 text-xs">—</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

export function SurveillanceRegistry({ embedded = false }) {
  const [reg, setReg] = useState(null);

  useEffect(() => { api.surveillanceSources().then(setReg).catch(() => setReg(null)); }, []);

  if (!reg) return <Spinner label="Loading surveillance registry…" />;

  const connectors = reg.sources.filter((s) => s.type === 'connector');
  const surrogates = reg.sources.filter((s) => s.type === 'surrogate');
  const c = reg.counts || {};

  return (
    <div className="space-y-6">
      {!embedded && (
        <div>
          <h2 className="text-xl font-bold text-slate-100">Worldwide Surveillance Network Registry</h2>
          <p className="text-xs text-slate-500 mt-0.5">{reg.note}</p>
        </div>
      )}
      {embedded && reg.note && (
        <p className="text-xs text-[var(--app-text-muted)]">{reg.note}</p>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Networks modeled" value={c.total ?? 0} accent="text-slate-100" />
        <StatCard label="Live connectors" value={c.live_connectors ?? 0} sub="queried live, keyless" accent="text-emerald-300" />
        <StatCard label="Connectors" value={c.connectors ?? 0} accent="text-sky-300" />
        <StatCard label="Surrogate/reference" value={c.surrogates ?? 0} sub="licensed / distributed infra" accent="text-slate-300" />
      </div>

      <Card className="p-4">
        <CardHeader title="Live connectors" subtitle="Real APIs VigilAI queries with no key (FAERS, MAUDE, drug labels, RxNorm; ICD-11 optional)." />
        <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3">
          {connectors.map((s) => <SourceCard key={s.id} s={s} />)}
        </div>
      </Card>

      <Card className="p-4">
        <CardHeader title="Surrogate / reference networks" subtitle="Licensed or distributed-infrastructure systems represented for architecture fidelity — not ingested offline." />
        <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3">
          {surrogates.map((s) => <SourceCard key={s.id} s={s} />)}
        </div>
      </Card>
    </div>
  );
}

export default function Surveillance({ embedded = false }) {
  return (
    <div className="space-y-6">
      <SurveillanceRegistry embedded={embedded} />
      <Explorer />
    </div>
  );
}
