import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { useRefresh } from '../App';
import { Badge, Button, Card, CardHeader, Spinner } from '../components/ui';

const PAGE = 24;

/** Outcome vocabulary — mirrors backend/app/analytics/remine_lab.py. */
const OUTCOMES = {
  unmasked: {
    label: 'crosses threshold',
    tone: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
    blurb: 'Became a signal of disproportionate reporting only after unmasking.',
  },
  co_reported: {
    label: 'co-reported',
    tone: 'bg-amber-500/15 text-amber-200 border-amber-500/30',
    blurb: "This product's own cases overlap the competitor's — review for confounding.",
  },
  vanished: {
    label: 'vanished',
    tone: 'bg-fuchsia-500/15 text-fuchsia-200 border-fuchsia-500/30',
    blurb: 'Every case is shared with the masker, so the pair disappears when they go.',
  },
  attenuated: {
    label: 'attenuated',
    tone: 'bg-sky-500/15 text-sky-300 border-sky-500/30',
    blurb: 'Weaker after unmasking — the association leaned on shared reporting.',
  },
  amplified: {
    label: 'comparator only',
    tone: 'bg-slate-600/25 text-slate-300 border-slate-600/40',
    blurb: 'PRR rises, but only by the factor every product on this event gets.',
  },
  stable: {
    label: 'stable',
    tone: 'bg-slate-600/25 text-slate-400 border-slate-600/40',
    blurb: 'Competition bias does not appear to drive this pair.',
  },
};

const FILTERS = [
  { id: 'all', label: 'All' },
  { id: 'actionable', label: 'Needs review' },
  { id: 'unmasked', label: 'Crosses threshold' },
  { id: 'co_reported', label: 'Co-reported' },
  { id: 'vanished', label: 'Vanished' },
  { id: 'evaluable', label: '≥3 cases' },
  { id: 'devices', label: 'Devices' },
  { id: 'amplified', label: 'Comparator only' },
];

const SORTS = [
  { id: 'impact', label: 'Impact' },
  { id: 'coreporting', label: 'Co-reporting shift' },
  { id: 'masking', label: 'Masking ratio' },
  { id: 'count', label: 'Case count' },
  { id: 'prr', label: 'PRR after' },
  { id: 'risk', label: 'Masking risk' },
];

const TIERS = {
  evaluable: { label: '≥3 cases', tone: 'text-emerald-300/80' },
  provisional: { label: '2 cases', tone: 'text-amber-300/80' },
  exploratory: { label: '1 case', tone: 'text-slate-500' },
};

const fmt = (v) => (v == null ? '—' : typeof v === 'number' ? v.toFixed(2) : v);

/** Corpus-wide competition-bias playground — searchable, filterable, paged. */
export default function RemineLab({ embedded = false }) {
  const { tick, bump } = useRefresh();
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [runningKey, setRunningKey] = useState(null);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState(null);
  const [showMethod, setShowMethod] = useState(false);

  const [draft, setDraft] = useState('');
  const [q, setQ] = useState('');
  const [only, setOnly] = useState('all');
  const [sort, setSort] = useState('impact');
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    const t = setTimeout(() => { setQ(draft.trim()); setOffset(0); }, 300);
    return () => clearTimeout(t);
  }, [draft]);

  const load = useCallback(() => {
    setLoading(true);
    api.remineLab({ limit: PAGE, offset, q, only, sort })
      .then((d) => setData((prev) => (
        offset > 0 && prev ? { ...d, cards: [...prev.cards, ...d.cards] } : d
      )))
      .catch(() => setData({ cards: [], needs_demo_seed: true, headline: 'Could not load remine lab.' }))
      .finally(() => setLoading(false));
  }, [offset, q, only, sort]);

  useEffect(() => { load(); }, [load, tick]);

  const loadDemo = async () => {
    setBusy(true);
    setErr(null);
    try {
      await api.ingestPvDemo({ recompute: true });
      bump?.();
      setOffset(0);
      load();
    } catch (e) {
      setErr(e?.message || String(e));
    }
    setBusy(false);
  };

  const runRemine = async (card) => {
    const key = `${card.drug}|${card.event}`;
    setRunningKey(key);
    setErr(null);
    try {
      // Pair-based remine works even when the pair has no persisted signal row
      const r = card.signal_id
        ? await api.signalUnmask(card.signal_id, card.maskers || [])
        : await api.remineRunPair(card.drug, card.event, card.maskers || []);
      setResult({ ...r, card });
    } catch (e) {
      setErr(e?.message || String(e));
    }
    setRunningKey(null);
  };

  if (!data) return <Spinner label="Screening corpus for competition bias…" />;

  const cards = data.cards || [];
  const facets = data.facets || {};
  const method = data.method || {};
  const totalMatching = data.total_matching ?? cards.length;
  const totalEligible = data.total_eligible ?? cards.length;
  // An API predating corpus-wide screening returns no facets/method
  const legacyApi = data.total_eligible == null;
  const methodRows = [
    ['Dataset', method.dataset],
    ['Eligibility', method.eligibility],
    ['Technique', method.technique],
    ['Reading the numbers', method.metrics],
    ['Evidence tiers', method.tiers],
  ].filter(([, v]) => v);

  return (
    <div className="space-y-5">
      {!embedded && (
        <div>
          <h2 className="text-xl font-bold text-slate-100">Competition-bias remine lab</h2>
          <p className="text-sm text-slate-400 mt-1">{data.how_to_use}</p>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <p className="text-sm text-slate-200 flex-1 min-w-[16rem]">{data.headline}</p>
        <Button variant="ghost" onClick={() => setShowMethod((v) => !v)}>
          {showMethod ? 'Hide method' : 'What is this?'}
        </Button>
        <Button variant="primary" disabled={busy} onClick={loadDemo}>
          {busy ? 'Loading…' : 'Load PV demo pack'}
        </Button>
      </div>

      {showMethod && (
        <Card className="p-4 space-y-2 text-sm text-slate-300 border-sky-700/30 bg-sky-500/[0.03]">
          {methodRows.length ? methodRows.map(([label, text]) => (
            <div key={label}>
              <span className="text-slate-500 uppercase text-[10px] tracking-wide">{label}</span>
              <p className="mt-0.5">{text}</p>
            </div>
          )) : (
            <p className="text-slate-400">
              This API build predates corpus-wide screening, so it returns only a
              handful of pre-picked cards. Redeploy the backend to screen every
              eligible product–event pair.
            </p>
          )}
        </Card>
      )}

      {err && <p className="text-sm text-rose-300">{err}</p>}

      {/* Search + sort */}
      <div className="flex flex-col sm:flex-row gap-2">
        <div className="relative flex-1">
          <input
            type="search"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Search product, event, or masker… e.g. warfarin, haemorrhage, pacemaker"
            className="w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2.5 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-1 focus:ring-sky-500/60"
            aria-label="Search remine candidates"
            list="remine-products"
          />
          <datalist id="remine-products">
            {(data.products || []).map((p) => <option key={p} value={p} />)}
          </datalist>
          {draft && (
            <button
              type="button"
              onClick={() => setDraft('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-slate-400 hover:text-slate-200 px-1.5 py-0.5"
            >
              Clear
            </button>
          )}
        </div>
        <select
          value={sort}
          onChange={(e) => { setSort(e.target.value); setOffset(0); }}
          className="sm:w-52 rounded-lg bg-slate-900 border border-slate-700 px-3 py-2.5 text-sm text-slate-100 focus:outline-none focus:ring-1 focus:ring-sky-500/60"
          aria-label="Sort remine candidates"
        >
          {SORTS.map((s) => <option key={s.id} value={s.id}>Sort: {s.label}</option>)}
        </select>
      </div>

      {/* Outcome filters */}
      <div className={`flex flex-wrap gap-1.5 ${legacyApi ? 'hidden' : ''}`}>
        {FILTERS.map((f) => {
          const n = f.id === 'all' ? facets.all : facets[f.id];
          const active = only === f.id;
          return (
            <button
              key={f.id}
              type="button"
              onClick={() => { setOnly(f.id); setOffset(0); }}
              className={`rounded-full border px-3 py-1 text-xs transition ${
                active
                  ? 'bg-sky-500/20 text-sky-200 border-sky-500/40'
                  : 'bg-slate-900 text-slate-400 border-slate-700 hover:text-slate-200'
              }`}
            >
              {f.label}{n != null && <span className="ml-1.5 text-slate-500">{n}</span>}
            </button>
          );
        })}
      </div>

      <p className="text-xs text-slate-500">
        Showing {cards.length} of {totalMatching} matching · {totalEligible} eligible pairs screened
        {legacyApi && ' · API build predates corpus-wide screening'}
      </p>

      {cards.length === 0 ? (
        <Card className="p-4 text-sm text-slate-400">
          {q || only !== 'all'
            ? 'No pairs match this search or filter. Try “All”, or clear the search box.'
            : <>No shared events with competitors in this workspace yet. Click <span className="text-slate-200">Load PV demo pack</span>, wait for recompute, then remine from the cards that appear.</>}
        </Card>
      ) : (
        <div className="space-y-3">
          {cards.map((c) => {
            const key = `${c.drug}|${c.event}`;
            const oc = OUTCOMES[c.outcome] || OUTCOMES.stable;
            const tier = TIERS[c.evidence_tier] || TIERS.exploratory;
            return (
              <Card key={key} className="p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium text-slate-100 capitalize flex items-center gap-2 flex-wrap">
                      {c.drug} <span className="text-slate-600">→</span> {c.event}
                      {c.evidence_tier && <span className={`text-[10px] ${tier.tone}`}>{tier.label}</span>}
                      {c.product_type === 'device' && (
                        <span className="text-[10px] text-slate-500 uppercase">device</span>
                      )}
                    </div>
                    <p className="mt-1 text-sm text-slate-300 leading-relaxed">{c.interpretation}</p>

                    <div className="mt-2 grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-1 text-[11px]">
                      <div><span className="text-slate-500">PRR </span><span className="text-slate-300">{fmt(c.before_prr)} → {fmt(c.after_prr)}</span></div>
                      <div><span className="text-slate-500">IC025 </span><span className="text-slate-300">{fmt(c.before_ic025)} → {fmt(c.after_ic025)}</span></div>
                      <div title="Pair-specific: this product's own event rate after removing shared cases">
                        <span className="text-slate-500">co-reporting </span>
                        <span className="text-slate-300">{fmt(c.coreporting_ratio)}×</span>
                      </div>
                      <div title="Shared by every product reporting this event — not pair-specific evidence">
                        <span className="text-slate-500">comparator </span>
                        <span className="text-slate-500">{fmt(c.comparator_ratio)}×</span>
                      </div>
                    </div>

                    <div className="mt-2 text-[11px] text-slate-500">
                      Exclude: {(c.maskers || []).join(', ') || '—'}
                      {c.event_total != null && ` · ${c.target_count} of ${c.event_total} reports of this event`}
                      {c.credible_masker === false && <span className="text-slate-600"> · no dominant competitor</span>}
                    </div>
                  </div>

                  <div className="flex flex-col gap-2 items-end shrink-0">
                    <Badge
                      value={c.outcome ? oc.label : (c.masking_risk || 'ready')}
                      className={oc.tone}
                    />
                    <Button
                      variant="primary"
                      disabled={runningKey === key}
                      onClick={() => runRemine(c)}
                    >
                      {runningKey === key ? 'Remining…' : 'Run remine now'}
                    </Button>
                    {c.signal_id && (
                      <Link to={`/signals/${c.signal_id}`} className="text-xs text-sky-300 hover:underline">
                        Open signal →
                      </Link>
                    )}
                  </div>
                </div>
              </Card>
            );
          })}

          {data.has_more && (
            <div className="flex justify-center pt-1">
              <Button variant="ghost" disabled={loading} onClick={() => setOffset(offset + PAGE)}>
                {loading ? 'Loading…' : `Show more (${totalMatching - cards.length} left)`}
              </Button>
            </div>
          )}
        </div>
      )}

      {result && (
        <Card className="p-4 border-orange-600/40 bg-orange-500/[0.04]">
          <CardHeader
            title="Latest remine result"
            subtitle={result.card ? `${result.card.drug} → ${result.card.event}` : ''}
          />
          <p className="mt-3 text-sm text-slate-100">{result.interpretation}</p>
          <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
            <div><div className="text-[10px] text-slate-500 uppercase">Before PRR</div><div className="text-slate-100">{fmt(result.baseline?.prr)}</div></div>
            <div><div className="text-[10px] text-slate-500 uppercase">After PRR</div><div className="text-emerald-300">{fmt(result.unmasked?.prr)}</div></div>
            <div><div className="text-[10px] text-slate-500 uppercase">Before IC025</div><div className="text-slate-100">{fmt(result.baseline?.ic025)}</div></div>
            <div><div className="text-[10px] text-slate-500 uppercase">After IC025</div><div className="text-slate-100">{fmt(result.unmasked?.ic025)}</div></div>
          </div>
          <div className="mt-2 text-[11px] text-slate-500">
            Masking ratio {fmt(result.masking_ratio)}× = co-reporting {fmt(result.coreporting_ratio)}× × comparator {fmt(result.comparator_ratio)}× ·
            {' '}{result.reports_before} → {result.reports_after} reports
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
