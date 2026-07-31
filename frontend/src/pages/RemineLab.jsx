import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { useRefresh } from '../App';
import { Badge, Button, Card, CardHeader, Spinner } from '../components/ui';

/** Always-on remine playground — never a dead disabled button. */
export default function RemineLab({ embedded = false }) {
  const { tick, bump } = useRefresh();
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [runningId, setRunningId] = useState(null);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState(null);

  const load = () => {
    api.remineLab()
      .then(setData)
      .catch(() => setData({ cards: [], needs_demo_seed: true, headline: 'Could not load remine lab.' }));
  };

  useEffect(() => { load(); }, [tick]);

  const loadDemo = async () => {
    setBusy(true);
    setErr(null);
    try {
      await api.ingestPvDemo({ recompute: true });
      bump?.();
      load();
    } catch (e) {
      setErr(e?.message || String(e));
    }
    setBusy(false);
  };

  const runRemine = async (card) => {
    if (!card.signal_id) {
      setErr('No persisted signal row yet — load the PV demo pack, then retry.');
      return;
    }
    setRunningId(card.signal_id);
    setErr(null);
    try {
      const r = await api.signalUnmask(card.signal_id, card.maskers || []);
      setResult({ ...r, card });
    } catch (e) {
      setErr(e?.message || String(e));
    }
    setRunningId(null);
  };

  if (!data) return <Spinner label="Building remine lab…" />;
  const cards = data.cards || [];

  return (
    <div className="space-y-5">
      {!embedded && (
        <div>
          <h2 className="text-xl font-bold text-slate-100">Competition-bias remine lab</h2>
          <p className="text-sm text-slate-400 mt-1">{data.how_to_use}</p>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <p className="text-sm text-slate-200 flex-1">{data.headline}</p>
        <Button variant="primary" disabled={busy} onClick={loadDemo}>
          {busy ? 'Loading…' : 'Load PV demo pack'}
        </Button>
      </div>
      {err && <p className="text-sm text-rose-300">{err}</p>}

      {cards.length === 0 ? (
        <Card className="p-4 text-sm text-slate-400">
          No shared events with competitors in this workspace yet. Click <span className="text-slate-200">Load PV demo pack</span>,
          wait for recompute, then remine from the cards that appear.
        </Card>
      ) : (
        <div className="space-y-3">
          {cards.map((c) => (
            <Card key={`${c.drug}|${c.event}|${c.signal_id}`} className="p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium text-slate-100 capitalize">
                    {c.drug} → {c.event}
                  </div>
                  <p className="mt-1 text-sm text-slate-300 leading-relaxed">{c.action}</p>
                  <div className="mt-2 text-[11px] text-slate-500">
                    Exclude: {(c.maskers || []).join(', ') || '—'}
                    {c.before_prr != null && <> · before PRR {c.before_prr}</>}
                    {c.after_prr != null && <> · after PRR {c.after_prr}</>}
                    {c.delta_prr != null && <> · Δ {c.delta_prr}</>}
                  </div>
                </div>
                <div className="flex flex-col gap-2 items-end">
                  <Badge
                    value={c.signal_strengthened ? 'strengthens' : (c.masking_risk || 'ready')}
                    className={
                      c.signal_strengthened
                        ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
                        : 'bg-orange-500/15 text-orange-200 border-orange-500/30'
                    }
                  />
                  <Button
                    variant="primary"
                    disabled={runningId === c.signal_id || !c.signal_id}
                    onClick={() => runRemine(c)}
                  >
                    {runningId === c.signal_id ? 'Remining…' : 'Run remine now'}
                  </Button>
                  {c.signal_id && (
                    <Link to={`/signals/${c.signal_id}`} className="text-xs text-sky-300 hover:underline">
                      Open signal →
                    </Link>
                  )}
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {result && (
        <Card className="p-4 border-orange-600/40 bg-orange-500/[0.04]">
          <CardHeader title="Latest remine result" subtitle={result.card ? `${result.card.drug} → ${result.card.event}` : ''} />
          <p className="mt-3 text-sm text-slate-100">{result.interpretation}</p>
          <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
            <div><div className="text-[10px] text-slate-500 uppercase">Before PRR</div><div className="text-slate-100">{result.baseline?.prr ?? '—'}</div></div>
            <div><div className="text-[10px] text-slate-500 uppercase">After PRR</div><div className="text-emerald-300">{result.unmasked?.prr ?? '—'}</div></div>
            <div><div className="text-[10px] text-slate-500 uppercase">Before IC025</div><div className="text-slate-100">{result.baseline?.ic025 ?? '—'}</div></div>
            <div><div className="text-[10px] text-slate-500 uppercase">After IC025</div><div className="text-slate-100">{result.unmasked?.ic025 ?? '—'}</div></div>
          </div>
          {result.card?.signal_id && (
            <Link to={`/signals/${result.card.signal_id}`} className="inline-block mt-3 text-sm text-sky-300 hover:underline">
              Continue on signal detail (SAR / lifecycle) →
            </Link>
          )}
        </Card>
      )}

      {data.disclaimer && <p className="text-[10px] text-slate-500">{data.disclaimer}</p>}
    </div>
  );
}
