import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { useAuth } from '../App';
import { Badge, Button, Card, CardHeader, Spinner } from '../components/ui';

export default function Onboarding({ embedded = false }) {
  const { user } = useAuth();
  const [url, setUrl] = useState('https://www.reddit.com/r/AskDocs/');
  const [cfg, setCfg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [ingesting, setIngesting] = useState(false);
  const [err, setErr] = useState('');

  const run = async (ingest = false) => {
    if (ingest) setIngesting(true);
    else setBusy(true);
    setErr('');
    if (!ingest) setCfg(null);
    try {
      const res = await api.onboardForum(url, ingest);
      setCfg(res);
    } catch (e) {
      setErr(e.message);
    }
    setBusy(false);
    setIngesting(false);
  };

  if (!user) {
    return (
      <Card className="p-6 text-sm text-slate-300">
        Forum onboarding requires an analyst account. <Link to="/login" className="text-sky-400 hover:underline">Sign in</Link> to continue.
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <Card className="p-5">
        <CardHeader title="Agentic Forum Onboarding" subtitle="Point VigilAI at any patient forum URL; it analyzes the page, proposes extraction selectors, then can ingest scrubbed samples into the signal pipeline." />
        <div className="flex gap-2 mt-4 flex-wrap">
          <input className="flex-1 min-w-[220px] rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-slate-100"
                 value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://forum.example.com/…" />
          <Button variant="primary" disabled={busy || ingesting} onClick={() => run(false)}>
            {busy ? 'Analyzing…' : '🌐 Propose config'}
          </Button>
          <Button variant="ghost" disabled={busy || ingesting} onClick={() => run(true)}>
            {ingesting ? 'Ingesting…' : '⚡ Analyze + ingest samples'}
          </Button>
        </div>
        {err && <div className="text-xs text-rose-400 mt-2">{err}</div>}
        {cfg?.ingested > 0 && (
          <div className="text-xs text-emerald-400 mt-2">
            Ingested {cfg.ingested} scrubbed sample post(s) into the pipeline — check Live Feed / Signals.
          </div>
        )}
      </Card>

      {(busy || ingesting) && <Spinner label="Fetching & analyzing forum structure…" />}

      {cfg && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Card className="p-4">
            <CardHeader title="Proposed extraction config" right={<Badge value={`${Math.round((cfg.confidence || 0) * 100)}% confidence`} className="bg-sky-500/15 text-sky-300 border-sky-500/30" />} />
            <div className="mt-3 space-y-2 text-sm">
              <Row k="Method" v={cfg.method} />
              <Row k="Forum type" v={cfg.forum_type} />
              <Row k="Post selector" v={cfg.post_selector} mono />
              <Row k="Title selector" v={cfg.title_selector} mono />
              <Row k="Date selector" v={cfg.date_selector} mono />
              <Row k="Content selector" v={cfg.content_selector} mono />
              <Row k="Posts/page (est.)" v={cfg.estimated_posts_per_page} />
              {cfg.llm_suggested && <Row k="LLM refined" v="yes" />}
              {cfg.ingest_requested && <Row k="Ingested" v={cfg.ingested ?? 0} />}
            </div>
          </Card>
          <Card className="p-4">
            <CardHeader title="Sample extracted posts" subtitle="PII already scrubbed" />
            <div className="mt-3 space-y-2">
              {(cfg.sample_posts || []).length === 0 && <div className="text-xs text-slate-500">No samples extracted (page may be JS-rendered).</div>}
              {(cfg.sample_posts || []).map((p, i) => (
                <div key={i} className="rounded-lg border border-slate-800 bg-slate-950/40 p-3 text-xs text-slate-300">{p.content}</div>
              ))}
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}

function Row({ k, v, mono }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-slate-800/50 pb-1.5">
      <span className="text-slate-500">{k}</span>
      <span className={`text-slate-200 text-right ${mono ? 'font-mono text-xs' : ''}`}>{String(v ?? '—')}</span>
    </div>
  );
}
