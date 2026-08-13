import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { useAuth, useRefresh } from '../App';
import { Badge, Button, Card, CardHeader } from '../components/ui';

const EXAMPLES = [
  'help',
  'crawl google news about ozempic side effects',
  'fetch reddit for accutane depression',
  'pull faers limit 10',
  'search pubmed for myocarditis vaccine',
  'europe pmc abstracts about statin myalgia',
  'semantic scholar pharmacovigilance signal',
  'cochrane central vaccine safety',
  'life science news',
  'pull maude',
  'hacker news about drug safety',
];

export default function Command({ embedded = false }) {
  const { user } = useAuth();
  const { bump } = useRefresh();
  const [message, setMessage] = useState(EXAMPLES[0]);
  const [busy, setBusy] = useState(false);
  const [log, setLog] = useState([]);
  const [chain, setChain] = useState(null);
  const bottom = useRef(null);

  useEffect(() => {
    api.auditChain().then(setChain).catch(() => setChain(null));
  }, []);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth' });
  }, [log]);

  if (!user) {
    return (
      <Card className="p-6 text-sm text-slate-300">
        Agent console requires sign-in. <Link to="/login" className="text-sky-400 hover:underline">Sign in</Link>
      </Card>
    );
  }

  const send = async (text) => {
    const msg = (text || message).trim();
    if (!msg || busy) return;
    setBusy(true);
    setLog((L) => [...L, { role: 'user', text: msg }]);
    try {
      const res = await api.agentChat(msg, true);
      setLog((L) => [...L, {
        role: 'agent',
        text: res.reply || JSON.stringify(res),
        meta: res,
      }]);
      bump();
    } catch (e) {
      setLog((L) => [...L, { role: 'agent', text: `Error: ${e.message}` }]);
    }
    setBusy(false);
  };

  return (
    <div className="space-y-4">
      <Card className="p-5">
        <CardHeader
          title="Command Center · MCP-lite crawl dispatch"
          subtitle="Chat → parse source + query → crawl → ingest. Ask help for commands. Recompute signals from the Demo bar when ready."
        />
        <div className="mt-3 flex flex-wrap gap-2">
          {EXAMPLES.map((ex) => (
            <Button key={ex} type="button" size="sm" variant="outline" onClick={() => setMessage(ex)}>
              {ex}
            </Button>
          ))}
        </div>
        <div className="mt-3 flex gap-2">
          <input className="flex-1 rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-slate-100"
            value={message} onChange={(e) => setMessage(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') send(); }}
            placeholder='e.g. fetch google news about ozempic · help · pull faers limit 10' />
          <Button variant="primary" disabled={busy} onClick={() => send()}>
            {busy ? 'Running…' : '▶ Dispatch'}
          </Button>
        </div>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card className="p-4 lg:col-span-2 max-h-[420px] overflow-y-auto space-y-3">
          <CardHeader title="Session log" />
          {log.length === 0 && (
            <p className="text-xs text-slate-500 mt-2">No dispatches yet — pick an example or type a crawl command.</p>
          )}
          {log.map((m, i) => (
            <div key={i} className={`rounded-lg border p-3 text-sm ${
              m.role === 'user'
                ? 'border-sky-800/40 bg-sky-950/20 text-sky-100'
                : 'border-slate-800 bg-slate-950/40 text-slate-200'
            }`}>
              <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1">{m.role}</div>
              <div className="whitespace-pre-wrap">{m.text}</div>
              {m.meta?.parsed?.slots && (
                <div className="mt-2 flex flex-wrap gap-2 text-[11px]">
                  <Badge value={`source:${m.meta.parsed.slots.source}`} className="bg-teal-500/10 text-teal-300 border-teal-500/20" />
                  {m.meta.parsed.slots.query && (
                    <Badge value={`q:${m.meta.parsed.slots.query}`} className="bg-slate-700/30 text-slate-300 border-slate-600/40" />
                  )}
                  {m.meta.ingested != null && (
                    <Badge value={`ingested ${m.meta.ingested}`} className="bg-emerald-500/10 text-emerald-300 border-emerald-500/20" />
                  )}
                </div>
              )}
            </div>
          ))}
          <div ref={bottom} />
        </Card>

        <Card className="p-4 space-y-3">
          <CardHeader title="Ed25519 audit chain" subtitle="Cryptographic integrity of verified signals" />
          {chain ? (
            <div className="space-y-2 text-sm">
              <div className="flex items-center gap-2">
                <Badge
                  value={chain.valid ? '✓ chain valid' : '✗ broken'}
                  className={chain.valid
                    ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
                    : 'bg-rose-500/15 text-rose-300 border-rose-500/30'}
                />
              </div>
              <Row k="Envelopes" v={chain.count ?? chain.envelopes?.length ?? '—'} />
              <Row k="Broken links" v={chain.broken ?? 0} />
              <p className="text-[11px] text-slate-500 pt-2">
                Open any Safety Signal → <strong>Verify chain</strong> to append an envelope, then refresh here.
              </p>
              <Button variant="ghost" onClick={() => api.auditChain().then(setChain)}>Refresh chain</Button>
            </div>
          ) : (
            <p className="text-xs text-slate-500">No audit envelopes yet. Verify a signal to mint the first link.</p>
          )}
        </Card>
      </div>
    </div>
  );
}

function Row({ k, v }) {
  return (
    <div className="flex justify-between text-xs border-b border-slate-800/50 pb-1">
      <span className="text-slate-500">{k}</span>
      <span className="text-slate-200">{String(v)}</span>
    </div>
  );
}
