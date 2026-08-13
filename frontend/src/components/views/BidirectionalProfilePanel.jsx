import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../../api';
import { Badge, Button, Card, Spinner } from '../ui';

const TIER_ORDER = ['Critical', 'High', 'Moderate', 'Mild'];
const TIER_TONE = {
  Critical: 'err',
  High: 'warn',
  Moderate: 'info',
  Mild: 'muted',
};

/**
 * Forward / inverse clinical cross-section panel.
 * mode: 'drug' → GET /api/analytics/drug-to-events/{name}
 * mode: 'event' → GET /api/analytics/event-to-drugs/{name}
 */
export default function BidirectionalProfilePanel({ mode, query, onClose }) {
  const nav = useNavigate();
  const [data, setData] = useState(null);
  const [err, setErr] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!query || !mode) return undefined;
    let cancelled = false;
    setLoading(true);
    setErr('');
    setData(null);
    const run = mode === 'drug'
      ? api.drugToEvents(query)
      : api.eventToDrugs(query);
    run
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => { if (!cancelled) setErr(e.message || 'Failed to load profile'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [mode, query]);

  const title = mode === 'drug'
    ? `Drug profile · ${query}`
    : `Event profile · ${query}`;
  const subtitle = mode === 'drug'
    ? 'All adverse events linked to this product, bucketed by severity tier'
    : 'All products reporting this event, ranked by PRR / ROR';

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50 backdrop-blur-sm" onClick={onClose}>
      <aside
        className="w-full max-w-lg h-full overflow-y-auto border-l border-slate-700 bg-slate-950 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 z-10 flex items-start justify-between gap-3 border-b border-slate-800 bg-slate-950/95 px-4 py-3 backdrop-blur">
          <div>
            <h3 className="text-sm font-semibold text-slate-100">{title}</h3>
            <p className="text-[11px] text-slate-500 mt-0.5">{subtitle}</p>
          </div>
          <Button type="button" variant="outline" size="sm" onClick={onClose} aria-label="Close profile panel">
            Close
          </Button>
        </div>

        <div className="p-4 space-y-4">
          {loading && <Spinner label="Loading cross-section…" />}
          {err && <Card className="p-3 text-sm text-rose-300 border-rose-700/40">{err}</Card>}

          {!loading && !err && data && mode === 'drug' && (
            <DrugTiers data={data} onOpenSignal={(id) => nav(`/signals/${id}`)} />
          )}
          {!loading && !err && data && mode === 'event' && (
            <EventDrugList data={data} onOpenSignal={(id) => nav(`/signals/${id}`)} />
          )}
        </div>
      </aside>
    </div>
  );
}

function DrugTiers({ data, onOpenSignal }) {
  const tiers = data.tiers || {};
  const total = data.total ?? 0;
  return (
    <>
      <div className="text-xs text-slate-400">
        <span className="text-sky-300 font-medium">{data.drug || data.query}</span>
        {' · '}
        {total} signal{total === 1 ? '' : 's'} across severity tiers
      </div>
      {TIER_ORDER.map((tier) => {
        const rows = tiers[tier] || [];
        if (!rows.length) return null;
        return (
          <Card key={tier} className="p-3" variant="flat">
            <div className="flex items-center justify-between mb-2">
              <Badge tone={TIER_TONE[tier] || 'muted'} value={tier} />
              <span className="text-[10px] text-[var(--cds-sys-text-tertiary)]">{rows.length}</span>
            </div>
            <ul className="space-y-1.5">
              {rows.map((r) => (
                <li key={r.id}>
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => onOpenSignal(r.id)}
                    className="w-full justify-start text-left h-auto py-1.5"
                  >
                    <div className="min-w-0">
                      <div className="text-sm capitalize">{r.symptom || r.meddra_pt}</div>
                      <div className="flex flex-wrap gap-2 text-[10px] text-[var(--cds-sys-text-tertiary)] mt-0.5">
                        <span>PRR {r.prr?.toFixed?.(1) ?? r.prr}</span>
                        {r.strength && <Badge kind="strength" value={r.strength} />}
                        {r.sdr_flag && <Badge value="SDR" tone="err" />}
                        <span>{r.post_count} reports</span>
                      </div>
                    </div>
                  </Button>
                </li>
              ))}
            </ul>
          </Card>
        );
      })}
      {total === 0 && (
        <p className="text-sm text-slate-500">No signals for this product in the active workspace.</p>
      )}
    </>
  );
}

function EventDrugList({ data, onOpenSignal }) {
  const drugs = data.drugs || [];
  return (
    <>
      <div className="text-xs text-slate-400">
        Event <span className="text-rose-300 font-medium">{data.event || data.query}</span>
        {' · '}
        {drugs.length} product{drugs.length === 1 ? '' : 's'} (rank-ordered)
      </div>
      {drugs.length === 0 && (
        <p className="text-sm text-slate-500">No products report this event in the active workspace.</p>
      )}
      <ol className="space-y-2">
        {drugs.map((r, i) => (
          <li key={r.id}>
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenSignal(r.id)}
              className="w-full justify-start text-left h-auto py-2.5"
            >
              <div className="min-w-0 w-full">
                <div className="flex items-center gap-2">
                  <span className="text-[10px] tabular-nums text-[var(--cds-sys-text-tertiary)] w-5">{i + 1}.</span>
                  <span className="text-sm font-medium capitalize">{r.drug}</span>
                  {r.tier && (
                    <Badge tone={TIER_TONE[r.tier] || 'muted'} value={r.tier} className="ml-auto" />
                  )}
                </div>
                <div className="flex flex-wrap gap-2 text-[10px] text-[var(--cds-sys-text-tertiary)] mt-1 pl-7">
                  <span>PRR {r.prr?.toFixed?.(1) ?? r.prr}</span>
                  {r.ror != null && <span>ROR {Number(r.ror).toFixed(1)}</span>}
                  {r.strength && <Badge kind="strength" value={r.strength} />}
                  {r.sdr_flag && <Badge value="SDR" tone="err" />}
                  <span>{r.post_count} reports</span>
                </div>
              </div>
            </Button>
          </li>
        ))}
      </ol>
    </>
  );
}
