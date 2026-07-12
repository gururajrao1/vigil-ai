import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { useAuth } from '../App';
import { Badge, Button, Card, CardHeader, Spinner } from '../components/ui';

const REGIONS = ['Global', 'North America', 'Europe', 'Asia', 'South America', 'Africa', 'Oceania'];
const PLATFORMS = ['reddit', 'twitter', 'forum'];

function scoreColor(v) {
  if (v >= 85) return 'text-emerald-300';
  if (v >= 70) return 'text-amber-300';
  return 'text-rose-300';
}

export default function Forge() {
  const { user } = useAuth();
  const [form, setForm] = useState({ drug: 'isotretinoin', condition: 'acne', platform: 'reddit', region: 'Global', records: 5 });
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const generate = async () => {
    setBusy(true); setErr('');
    try {
      const res = await api.forgeGenerate({ ...form, records: Number(form.records) });
      setResult(res);
    } catch (e) {
      setErr(e.message);
    }
    setBusy(false);
  };

  if (!user) {
    return (
      <Card className="p-6 text-sm text-slate-300">
        The Data Forge requires an analyst account. <Link to="/login" className="text-sky-400 hover:underline">Sign in</Link> to generate synthetic patient posts.
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <Card className="p-5">
        <CardHeader title="Synthetic Data Forge"
          subtitle="Agentic generation of realistic (fictional) patient posts with multi-judge quality scoring + repair."
          right={result
            ? <span className={`text-[11px] rounded-lg px-2 py-0.5 border ${result.llm ? 'bg-emerald-900/30 border-emerald-700/40 text-emerald-300' : 'bg-slate-700/30 border-slate-600/40 text-slate-400'}`}>
                {result.llm_backend || (result.llm ? 'LLM' : 'Deterministic')}
              </span>
            : null}
        />
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mt-4">
          <div className="col-span-2 sm:col-span-1"><label className="text-[10px] uppercase text-slate-500">Drug</label>
            <input className="w-full rounded-lg bg-slate-900 border border-slate-700 px-2 py-1.5 text-sm text-slate-100" value={form.drug} onChange={set('drug')} /></div>
          <div className="col-span-2 sm:col-span-1"><label className="text-[10px] uppercase text-slate-500">Condition</label>
            <input className="w-full rounded-lg bg-slate-900 border border-slate-700 px-2 py-1.5 text-sm text-slate-100" value={form.condition} onChange={set('condition')} /></div>
          <div><label className="text-[10px] uppercase text-slate-500">Platform</label>
            <select className="w-full rounded-lg bg-slate-900 border border-slate-700 px-2 py-1.5 text-sm text-slate-100" value={form.platform} onChange={set('platform')}>
              {PLATFORMS.map((p) => <option key={p}>{p}</option>)}</select></div>
          <div><label className="text-[10px] uppercase text-slate-500">Region</label>
            <select className="w-full rounded-lg bg-slate-900 border border-slate-700 px-2 py-1.5 text-sm text-slate-100" value={form.region} onChange={set('region')}>
              {REGIONS.map((r) => <option key={r}>{r}</option>)}</select></div>
          <div><label className="text-[10px] uppercase text-slate-500">Records</label>
            <input type="number" min="1" max="10" className="w-full rounded-lg bg-slate-900 border border-slate-700 px-2 py-1.5 text-sm text-slate-100" value={form.records} onChange={set('records')} /></div>
          <div className="flex items-end"><Button variant="primary" disabled={busy} onClick={generate} className="w-full">{busy ? 'Forging…' : '⚗ Generate'}</Button></div>
        </div>
        {err && <div className="text-xs text-rose-400 mt-2">{err}</div>}
      </Card>

      {busy && <Spinner label="Generating & scoring synthetic records…" />}

      {result && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Card className="p-4"><div className="text-xs text-slate-400">Generated</div><div className="text-2xl font-bold text-slate-100">{result.generated}</div></Card>
            <Card className="p-4"><div className="text-xs text-slate-400">Export-ready</div><div className="text-2xl font-bold text-emerald-300">{result.export_ready}</div></Card>
            <Card className="p-4"><div className="text-xs text-slate-400">Avg quality</div><div className={`text-2xl font-bold ${scoreColor(result.avg_quality)}`}>{result.avg_quality}</div></Card>
            <Card className="p-4"><div className="text-xs text-slate-400">Engine</div><div className="text-lg font-bold text-slate-100">{result.llm ? 'Ollama LLM' : 'Deterministic'}</div></Card>
          </div>

          <div className="flex gap-2">
            <a href={api.forgeJsonlUrl(result.batch_id)} target="_blank" rel="noreferrer"><Button variant="ghost">⬇ Export JSONL</Button></a>
            <a href={api.forgeCsvUrl(result.batch_id)} target="_blank" rel="noreferrer"><Button variant="ghost">⬇ Export CSV</Button></a>
          </div>

          <div className="space-y-3">
            {result.records.map((r, i) => (
              <Card key={i} className="p-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2 text-xs text-slate-400">
                    <Badge value={r.platform} className="bg-slate-700/40 text-slate-300 border-slate-600/40" />
                    <span>{r.region} · {r.scenario?.age}yo {r.scenario?.gender} · {r.scenario?.emotion}</span>
                    {r.repaired && <Badge value="repaired" className="bg-amber-500/15 text-amber-300 border-amber-500/30" />}
                    <Badge value={r.source} className="bg-slate-700/40 text-slate-300 border-slate-600/40" />
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={`text-sm font-bold ${scoreColor(r.quality_score)}`}>Q {r.quality_score}</span>
                    {r.export_ready && <span className="text-emerald-400 text-xs">✓ ready</span>}
                  </div>
                </div>
                <p className="text-sm text-slate-200 leading-relaxed">{r.post_text}</p>
                <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-slate-500">
                  <span>medical {r.scores?.medical}</span>
                  <span>realism {r.scores?.realism}</span>
                  <span>hallucination {r.scores?.hallucination}</span>
                  <span>PII {r.scores?.pii}</span>
                </div>
              </Card>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
