import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import ForceGraph2D from 'react-force-graph-2d';
import { api } from '../api';
import { useRefresh } from '../App';
import { useProject } from '../projectContext';
import { Card, CardHeader, Spinner, Badge } from '../components/ui';
import KgStorySidebar, { computeStoryFocus } from '../components/views/KgStorySidebar';
import { filterGraph, adverseEventsForDrug, drugsForAdverseEvent } from './kgFilter';
import {
  TYPE_META,
  EDGE_META,
  seedLayeredPositions,
  getNodeDetails,
  suggestedGraphHeight,
  densifyGraph,
  shouldPaintLabel,
} from './kgLayout';

const TYPE_COLORS = {
  drug: '#38bdf8',
  symptom: '#f43f5e',
  condition: '#f59e0b',
  region: '#94a3b8',
  protein: '#14b8a6',
};
const EDGE_COLORS = {
  adverse: '#f43f5e',
  condition: '#f59e0b',
  binds: '#14b8a6',
  region: '#64748b',
  indication: '#475569',
};

/** Adverse edge color by disproportionality tier (STRONG / MODERATE / WEAK). */
const STRENGTH_EDGE_COLORS = {
  STRONG: '#f43f5e',
  MODERATE: '#f59e0b',
  Medium: '#f59e0b',
  WEAK: '#64748b',
};
const STRENGTH_EDGE_WIDTH = {
  STRONG: 2.8,
  MODERATE: 2.0,
  Medium: 2.0,
  WEAK: 1.2,
};

function strengthEdgeStyle(strength, dense = false) {
  const key = strength || 'WEAK';
  const color = STRENGTH_EDGE_COLORS[key] || STRENGTH_EDGE_COLORS.WEAK;
  const base = STRENGTH_EDGE_WIDTH[key] || STRENGTH_EDGE_WIDTH.WEAK;
  return { color, width: dense ? Math.max(1, base * 0.65) : base };
}

function StrengthBadge({ value, className = '' }) {
  if (!value) return null;
  const norm = value === 'Medium' ? 'MODERATE' : value;
  return <Badge kind="strength" value={norm} className={`!text-[10px] !px-1.5 !py-0 ${className}`} />;
}

const COLUMN_LABELS = [
  { type: 'drug', label: 'Drugs', pct: 8 },
  { type: 'protein', label: 'Targets', pct: 26 },
  { type: 'condition', label: 'Conditions', pct: 44 },
  { type: 'symptom', label: 'Adverse events', pct: 64 },
  { type: 'region', label: 'Regions', pct: 88 },
];

const EMPTY_FILTERS = { drugs: [], symptoms: [], conditions: [], countries: [], regions: [] };

async function loadFilterOptions(projectId) {
  try {
    const opts = await api.kgFilters(projectId);
    if (opts?.drugs?.length || opts?.symptoms?.length) return opts;
  } catch { /* fall through */ }
  try {
    const opts = await api.kgFilters(null);
    if (opts?.drugs?.length || opts?.symptoms?.length) return opts;
  } catch { /* fall through */ }
  try {
    const { signals } = await api.signals();
    const drugs = new Set();
    const symptoms = new Set();
    const regions = new Set();
    (signals || []).forEach((s) => {
      if (s.drug) drugs.add(s.drug);
      const sym = s.meddra?.pt || s.symptom;
      if (sym) symptoms.add(sym);
      Object.keys(s.regions || {}).forEach((r) => regions.add(r));
      if (s.primary_region) regions.add(s.primary_region);
    });
    const sort = (a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' });
    return {
      drugs: [...drugs].sort(sort),
      symptoms: [...symptoms].sort(sort),
      conditions: [],
      countries: [...regions].sort(sort),
      regions: [...regions].sort(sort),
    };
  } catch {
    return EMPTY_FILTERS;
  }
}

function FilterSelect({ label, value, options, onChange }) {
  const count = options?.length ?? 0;
  return (
    <div className="min-w-[140px] sm:min-w-[150px] flex-1 basis-[140px]">
      <label className="text-[11px] text-[var(--app-text-muted)]">
        {label} {count > 0 && <span className="text-[var(--app-text-faint)]">({count})</span>}
      </label>
      <select
        className="app-input app-select block mt-1 w-full text-sm"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={count === 0}
      >
        <option value="">{count === 0 ? 'No data yet' : 'All'}</option>
        {(options || []).map((o) => (
          <option key={o} value={o}>{o}</option>
        ))}
      </select>
    </div>
  );
}

function ActiveFilterPills({ drug, symptom, condition, country, strength, onClear }) {
  const pills = [
    drug && { key: 'drug', label: `Drug: ${drug}` },
    symptom && { key: 'symptom', label: `AE: ${symptom}` },
    condition && { key: 'condition', label: `Condition: ${condition}` },
    country && { key: 'country', label: `Region: ${country}` },
    strength && { key: 'strength', label: `Strength: ${strength}` },
  ].filter(Boolean);
  if (!pills.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 mt-3">
      <span className="text-[10px] uppercase tracking-wide text-[var(--app-text-faint)]">Active</span>
      {pills.map((p) => (
        <span key={p.key} className="rounded-md px-2.5 py-0.5 text-xs bg-teal-500/15 text-teal-300 border border-teal-500/30">
          {p.label}
        </span>
      ))}
      <button type="button" onClick={onClear} className="text-xs text-teal-400">Clear all</button>
    </div>
  );
}

function displayLabel(node) {
  const raw = (node?.label || '').trim();
  if (raw && !/^https?:/i.test(raw)) return raw;
  // Fallback: last path segment of URI id → human-ish name
  const id = String(node?.id || '');
  const seg = id.split('/').pop() || id;
  return seg.replace(/_/g, ' ').trim() || 'Unnamed';
}

function InspectorEmpty() {
  return (
    <div className="w-full lg:w-[340px] shrink-0 border-l border-[#3c4947] bg-[#0d1c2d]/80 flex flex-col items-center justify-center p-8 text-center min-h-[420px]">
      <div className="w-14 h-14 rounded-full border border-dashed border-[#3c4947] flex items-center justify-center text-[#859490] mb-3 text-2xl">⬡</div>
      <p className="text-sm text-[#d4e4fa] font-medium">Select a node</p>
      <p className="text-xs text-[#859490] mt-2 leading-relaxed max-w-[220px]">
        Click any drug, AE, condition, region, or STITCH target for identity, metrics, and neighbors.
      </p>
    </div>
  );
}

function NodeDetailPanel({
  details,
  onClose,
  onFocus,
  onSelectNeighbor,
  isFocused,
  onFilterDrug,
  onFilterAe,
}) {
  if (!details) return <InspectorEmpty />;
  const { node, meta, degree, neighbors, byKind, relatedPaths, neighborTypeCounts, stats } = details;
  const aeNeighbors = (byKind.adverse || []).filter((n) => n.node.type === 'symptom');
  const isDrug = node.type === 'drug';
  const isAe = node.type === 'symptom';

  return (
    <aside className="w-full lg:w-[360px] shrink-0 border-l border-[#3c4947] bg-[#122131] flex flex-col max-h-[640px]">
      <div className="px-4 py-3 border-b border-[#3c4947] bg-[#1c2b3c]/50 flex items-center justify-between">
        <h2 className="text-[10px] uppercase tracking-[0.12em] font-bold text-[#859490]">Entity inspector</h2>
        <button
          type="button"
          onClick={onClose}
          className="text-[#859490] hover:text-[#d4e4fa] text-lg leading-none px-1"
          aria-label="Close inspector"
        >
          ×
        </button>
      </div>
      <div className="p-4 border-b border-[#3c4947]">
        <div className="min-w-0">
          <span
            className="inline-block text-[10px] uppercase tracking-wider px-2 py-0.5 rounded mb-2 font-bold"
            style={{ background: `${meta.color}18`, color: meta.color, border: `1px solid ${meta.color}40` }}
          >
            {meta.label}
          </span>
          <h3 className="text-xl font-semibold text-[#d4e4fa] leading-snug break-words">{displayLabel(node)}</h3>
        </div>
        <p className="text-[11px] text-[#bbcac6] mt-2 leading-relaxed">{meta.description}</p>

        <div className="flex flex-wrap gap-2 mt-3">
          {isDrug && onFilterDrug && (
            <button
              type="button"
              onClick={() => onFilterDrug(displayLabel(node))}
              className="text-[10px] rounded px-2 py-1 bg-sky-500/15 text-sky-300 border border-sky-500/30 hover:bg-sky-500/25"
            >
              Filter graph to this drug
            </button>
          )}
          {isAe && onFilterAe && (
            <button
              type="button"
              onClick={() => onFilterAe(displayLabel(node))}
              className="text-[10px] rounded px-2 py-1 bg-rose-500/15 text-rose-300 border border-rose-500/30 hover:bg-rose-500/25"
            >
              Filter graph to this AE
            </button>
          )}
        </div>

        <div className="grid grid-cols-2 gap-2 mt-3">
          <div className="rounded-md border border-slate-700/70 bg-slate-900/60 p-2">
            <div className="text-[9px] uppercase tracking-wider text-slate-500 mb-0.5">Degree</div>
            <div className="text-lg font-semibold tabular-nums text-teal-300">{degree}</div>
          </div>
          <div className="rounded-md border border-slate-700/70 bg-slate-900/60 p-2">
            <div className="text-[9px] uppercase tracking-wider text-slate-500 mb-0.5">Avg PRR</div>
            <div className="text-lg font-semibold tabular-nums text-teal-300">{stats.avgPrr ?? '—'}</div>
          </div>
          <div className="rounded-md border border-slate-700/70 bg-slate-900/60 p-2">
            <div className="text-[9px] uppercase tracking-wider text-slate-500 mb-0.5">Max PRR</div>
            <div className="text-lg font-semibold tabular-nums text-rose-300/90">{stats.maxPrr ?? '—'}</div>
          </div>
          <div className="rounded-md border border-slate-700/70 bg-slate-900/60 p-2">
            <div className="text-[9px] uppercase tracking-wider text-slate-500 mb-0.5">Top strength</div>
            <div className="mt-0.5">
              {stats.topStrength
                ? <StrengthBadge value={stats.topStrength} />
                : <span className="text-lg font-semibold text-slate-500">—</span>}
            </div>
          </div>
        </div>

        {(isDrug || isAe) && stats.strengthCounts && (stats.adverseLinks > 0) && (
          <div className="mt-2 flex flex-wrap gap-1.5 text-[10px]">
            {['STRONG', 'MODERATE', 'WEAK'].map((tier) => (
              <span
                key={tier}
                className={`rounded-md border px-2 py-0.5 ${
                  tier === 'STRONG'
                    ? 'border-rose-500/30 text-rose-300 bg-rose-500/10'
                    : tier === 'MODERATE'
                      ? 'border-amber-500/30 text-amber-300 bg-amber-500/10'
                      : 'border-slate-600 text-slate-400 bg-slate-800/60'
                }`}
              >
                {stats.strengthCounts[tier] || 0} {tier}
              </span>
            ))}
            <span className="text-slate-600 self-center">{stats.adverseLinks} AE link{stats.adverseLinks === 1 ? '' : 's'}</span>
          </div>
        )}

        {Object.keys(neighborTypeCounts).length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {Object.entries(neighborTypeCounts).map(([t, n]) => (
              <span
                key={t}
                className="inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-[10px] bg-slate-800/80 text-slate-300 border border-slate-700/60"
              >
                <span className="w-1.5 h-1.5 rounded-full" style={{ background: TYPE_COLORS[t] || '#94a3b8' }} />
                {n} {TYPE_META[t]?.label || t}
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-5">
        {isDrug && aeNeighbors.length > 0 && (
          <section>
            <h4 className="text-[10px] uppercase tracking-wider text-rose-300/90 mb-2 font-medium">
              Adverse events for this drug ({aeNeighbors.length})
            </h4>
            <p className="text-[10px] text-slate-500 mb-2">
              Ranked by signal strength (STRONG → WEAK), then PRR.
            </p>
            <ul className="space-y-1">
              {aeNeighbors.map(({ node: nb, edge }) => (
                <li key={nb.id}>
                  <div className="flex items-stretch gap-1">
                    <button
                      type="button"
                      onClick={() => onSelectNeighbor(nb.id)}
                      className="flex-1 text-left text-xs rounded-lg px-2.5 py-2 hover:bg-slate-800 border border-slate-700/50"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-rose-300 font-medium">{displayLabel(nb)}</span>
                        <StrengthBadge value={edge.strength} />
                      </div>
                      <div className="mt-1 flex flex-wrap gap-2 text-[10px] text-slate-500">
                        {edge.prr != null && <span className="text-rose-300/80">PRR {edge.prr}</span>}
                        {edge.ror != null && <span>ROR {edge.ror}</span>}
                        {edge.post_count != null && <span>{edge.post_count} posts</span>}
                        {edge.severity && (
                          <Badge kind="severity" value={edge.severity} className="!text-[9px] !px-1.5 !py-0" />
                        )}
                      </div>
                    </button>
                    {edge.signal_id && (
                      <Link
                        to={`/signals/${edge.signal_id}`}
                        title="Open signal detail"
                        className="shrink-0 text-[10px] px-2 rounded-lg border border-sky-500/30 text-sky-300 hover:bg-sky-500/15 flex items-center"
                        onClick={(e) => e.stopPropagation()}
                      >
                        Signal
                      </Link>
                    )}
                    {onFilterAe && (
                      <button
                        type="button"
                        title="Filter graph to this AE"
                        onClick={() => onFilterAe(displayLabel(nb))}
                        className="shrink-0 text-[10px] px-2 rounded-lg border border-rose-500/30 text-rose-300 hover:bg-rose-500/15"
                      >
                        Filter
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </section>
        )}

        {relatedPaths.length > 0 && (
          <section>
            <h4 className="text-[10px] uppercase tracking-wider text-slate-500 mb-2 font-medium">
              {isDrug ? 'Signal paths from this drug' : 'Signal paths'}
            </h4>
            <ul className="space-y-1.5">
              {relatedPaths.map((p) => (
                <li
                  key={`${p.drug}-${p.symptom}-${p.prr}`}
                  className="text-xs rounded-lg px-2.5 py-2 bg-slate-800/50 border border-slate-700/40 text-slate-300"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-x-1">
                      <span className="text-sky-300 font-medium">{p.drug}</span>
                      <span className="text-slate-600">→</span>
                      <span className="text-rose-300 font-medium">{p.symptom}</span>
                    </div>
                    <StrengthBadge value={p.strength} />
                  </div>
                  <div className="mt-1 flex flex-wrap gap-2 text-[10px] text-slate-500">
                    {p.prr != null && <span className="text-rose-300/80">PRR {p.prr}</span>}
                    {p.post_count != null && <span>{p.post_count} posts</span>}
                    {p.severity && <Badge kind="severity" value={p.severity} className="!text-[9px] !px-1.5 !py-0" />}
                  </div>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section>
          <h4 className="text-[10px] uppercase tracking-wider text-slate-500 mb-2 font-medium">
            Neighbors ({neighbors.length})
          </h4>
          {neighbors.length === 0 ? (
            <p className="text-xs text-slate-500">No connections in the current filtered view.</p>
          ) : (
            Object.entries(byKind).map(([kind, items]) => {
              if (isDrug && kind === 'adverse') return null; // already shown above
              const em = EDGE_META[kind] || EDGE_META.adverse;
              return (
                <div key={kind} className="mb-4 last:mb-0">
                  <div className="flex items-baseline justify-between gap-2 mb-1">
                    <h5 className="text-[11px] font-medium text-slate-300">{em.label}</h5>
                    <span className="text-[10px] text-slate-600">{items.length}</span>
                  </div>
                  <ul className="space-y-1">
                    {items.map(({ node: nb, edge, direction }) => (
                      <li key={`${nb.id}-${kind}-${direction}`}>
                        <button
                          type="button"
                          onClick={() => onSelectNeighbor(nb.id)}
                          className="w-full text-left text-xs rounded-lg px-2.5 py-2 hover:bg-slate-800 border border-transparent hover:border-slate-700/80 transition-colors group"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="flex items-center gap-2 min-w-0">
                              <span
                                className="w-2 h-2 rounded-full shrink-0"
                                style={{ background: TYPE_COLORS[nb.type] }}
                              />
                              <span className="truncate text-slate-100 group-hover:text-white font-medium">{displayLabel(nb)}</span>
                            </span>
                            <span className="text-[9px] uppercase tracking-wide text-slate-600 shrink-0">
                              {direction === 'outgoing' ? 'out' : 'in'}
                            </span>
                          </div>
                          <div className="mt-1 flex flex-wrap items-center gap-2 text-[10px] text-slate-500 pl-4">
                            <span>{TYPE_META[nb.type]?.label || nb.type}</span>
                            {edge.prr != null && <span className="text-rose-300/90">PRR {edge.prr}</span>}
                            {edge.strength && <StrengthBadge value={edge.strength} />}
                          </div>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })
          )}
        </section>
      </div>

      <div className="p-3 border-t border-[var(--app-border)] flex gap-2 bg-slate-950/80">
        <button
          type="button"
          onClick={onFocus}
          className="flex-1 text-xs rounded-lg px-3 py-2.5 bg-teal-500/15 text-teal-200 border border-teal-500/35 hover:bg-teal-500/25 font-medium"
        >
          {isFocused ? 'Show full graph' : 'Focus 1-hop neighborhood'}
        </button>
      </div>
    </aside>
  );
}

export default function KnowledgeGraph({ embedded = false }) {
  const { tick } = useRefresh();
  const { project } = useProject();
  const [rawKg, setRawKg] = useState(null);
  const [engine, setEngine] = useState('loading');
  const [filterOpts, setFilterOpts] = useState(EMPTY_FILTERS);
  const [drug, setDrug] = useState('');
  const [symptom, setSymptom] = useState('');
  const [condition, setCondition] = useState('');
  const [country, setCountry] = useState('');
  const [selectedNodeId, setSelectedNodeId] = useState(null);
  const [focusNode, setFocusNode] = useState(null);
  const [labelMode, setLabelMode] = useState('auto'); // auto | all | hubs
  const [hubsOnly, setHubsOnly] = useState(true); // densify when crowded
  const [strengthFilter, setStrengthFilter] = useState(''); // '' | STRONG | MODERATE | WEAK
  const [activeStoryStep, setActiveStoryStep] = useState(0);
  const [storyTargetDrug, setStoryTargetDrug] = useState('');
  const wrapRef = useRef(null);
  const [dims, setDims] = useState({ w: 800, h: 600 });

  useEffect(() => {
    loadFilterOptions(project?.id).then(setFilterOpts);
  }, [project?.id, tick]);

  const loadBaseGraph = useCallback(async () => {
    const hasServerFilter = Boolean(drug || symptom || condition || country);
    // Only blank the canvas on first load / project switch — keep prior graph while refining filters
    if (!rawKg) setEngine('loading');
    try {
      if (project?.id) {
        const data = await api.sparqlGraph(project.id, {
          drug,
          symptom,
          condition,
          country,
        });
        setRawKg(data);
        setEngine('sparql');
        if (data?.filter_options?.drugs?.length) setFilterOpts(data.filter_options);
        // Auto-select the filtered drug/AE node when present
        if (drug) {
          const n = data.nodes?.find(
            (x) => x.type === 'drug' && x.label?.toLowerCase() === drug.toLowerCase(),
          );
          if (n) setSelectedNodeId(n.id);
        } else if (symptom) {
          const n = data.nodes?.find(
            (x) => x.type === 'symptom' && x.label?.toLowerCase() === symptom.toLowerCase(),
          );
          if (n) setSelectedNodeId(n.id);
        } else if (!hasServerFilter) {
          setSelectedNodeId(null);
          setFocusNode(null);
        }
        return;
      }
    } catch (err) {
      console.warn('Project SPARQL graph failed, trying global KG:', err?.message || err);
    }
    try {
      const data = await api.kg();
      setRawKg(data);
      setEngine(project?.id ? 'fallback' : 'global');
      if (data?.filter_options?.drugs?.length) {
        setFilterOpts(data.filter_options);
      } else {
        loadFilterOptions(project?.id).then(setFilterOpts);
      }
    } catch {
      setRawKg(null);
      setEngine('error');
    }
  // rawKg intentionally omitted — used only as a presence check for loading UX
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.id, tick, drug, symptom, condition, country]);

  useEffect(() => { loadBaseGraph(); }, [loadBaseGraph]);

  const kg = useMemo(() => {
    if (!rawKg) return null;
    // Server already applies drug/AE/geo filters when using SPARQL; client filter still
    // handles focus + legacy/global payloads.
    let filtered = filterGraph(rawKg, { drug, symptom, condition, country }, focusNode);
    if (strengthFilter && filtered?.edges) {
      const want = strengthFilter === 'MODERATE' ? new Set(['MODERATE', 'Medium']) : new Set([strengthFilter]);
      const keepAdverse = new Set();
      const nextEdges = filtered.edges.filter((e) => {
        if (e.kind !== 'adverse') return true;
        const ok = want.has(e.strength || 'WEAK');
        if (ok) {
          keepAdverse.add(typeof e.source === 'object' ? e.source.id : e.source);
          keepAdverse.add(typeof e.target === 'object' ? e.target.id : e.target);
        }
        return ok;
      });
      // Keep non-AE nodes only if still connected, plus any drug/AE endpoints of kept adverse edges
      const connected = new Set();
      nextEdges.forEach((e) => {
        connected.add(typeof e.source === 'object' ? e.source.id : e.source);
        connected.add(typeof e.target === 'object' ? e.target.id : e.target);
      });
      const nextNodes = (filtered.nodes || []).filter((n) => connected.has(n.id));
      const nextPaths = (filtered.paths || []).filter((p) => {
        const s = p.strength === 'Medium' ? 'MODERATE' : (p.strength || 'WEAK');
        return s === strengthFilter || (strengthFilter === 'MODERATE' && p.strength === 'Medium');
      });
      filtered = {
        ...filtered,
        nodes: nextNodes,
        edges: nextEdges,
        paths: nextPaths,
        stats: { ...(filtered.stats || {}), node_count: nextNodes.length, edge_count: nextEdges.length },
        filtered: true,
      };
    }
    const crowded = (filtered?.nodes?.length || 0) > 55;
    if (hubsOnly && crowded && !focusNode) {
      const keepIds = [selectedNodeId].filter(Boolean);
      (filtered?.nodes || []).forEach((n) => {
        if (drug && n.type === 'drug' && n.label?.toLowerCase() === drug.toLowerCase()) keepIds.push(n.id);
        if (symptom && n.type === 'symptom' && n.label?.toLowerCase() === symptom.toLowerCase()) keepIds.push(n.id);
      });
      return densifyGraph(filtered, {
        maxPerColumn: 12,
        keepIds,
      });
    }
    return filtered;
  }, [rawKg, drug, symptom, condition, country, focusNode, hubsOnly, selectedNodeId, strengthFilter]);

  const nodeDetails = useMemo(
    () => (selectedNodeId && kg ? getNodeDetails(selectedNodeId, kg) : null),
    [selectedNodeId, kg],
  );

  const neighborIds = useMemo(() => {
    if (!nodeDetails) return new Set();
    return new Set(nodeDetails.neighbors.map((n) => n.node.id));
  }, [nodeDetails]);

  const storyFocus = useMemo(
    () => computeStoryFocus(kg, {
      activeStoryStep,
      targetDrug: storyTargetDrug || drug,
    }),
    [kg, activeStoryStep, storyTargetDrug, drug],
  );

  // Keep story target in sync when user filters to a drug
  useEffect(() => {
    if (drug && !storyTargetDrug) setStoryTargetDrug(drug);
  }, [drug, storyTargetDrug]);

  const canvasH = useMemo(
    () => suggestedGraphHeight(kg?.nodes || [], 560, 1100),
    [kg?.nodes],
  );

  // Full (unfiltered) source for drug→AE catalog
  const drugAeCatalog = useMemo(
    () => (drug && rawKg ? adverseEventsForDrug(rawKg, drug) : []),
    [rawKg, drug],
  );
  const aeDrugCatalog = useMemo(
    () => (symptom && rawKg ? drugsForAdverseEvent(rawKg, symptom) : []),
    [rawKg, symptom],
  );
  const symptomFilterOptions = useMemo(() => {
    if (drug && drugAeCatalog.length) return drugAeCatalog.map((a) => a.symptom);
    return filterOpts.symptoms;
  }, [drug, drugAeCatalog, filterOpts.symptoms]);

  const graphKey = `${drug}|${symptom}|${condition}|${country}|${strengthFilter}|${focusNode || ''}|${dims.w}|${canvasH}|${labelMode}|${hubsOnly}|${kg?.nodes?.length || 0}`;

  useEffect(() => {
    if (!wrapRef.current) return;
    const ro = new ResizeObserver((entries) => {
      const cr = entries[0].contentRect;
      setDims({ w: cr.width, h: Math.max(cr.height, canvasH) });
    });
    ro.observe(wrapRef.current);
    return () => ro.disconnect();
  }, [kg, canvasH]);

  const clearFilters = () => {
    setDrug('');
    setSymptom('');
    setCondition('');
    setCountry('');
    setStrengthFilter('');
    setFocusNode(null);
    setSelectedNodeId(null);
  };

  const graphData = useMemo(() => {
    if (!kg) return { nodes: [], links: [] };
    const h = Math.max(dims.h, canvasH);
    const seeded = seedLayeredPositions(kg.nodes, dims.w, h);
    const dense = (kg.nodes?.length || 0) > 50;
    return {
      nodes: seeded.map((n) => ({
        ...n,
        val: dense ? 1 + (n.degree || 1) * 0.25 : 1.4 + (n.degree || 1) * 0.4,
        fx: n.__colX,
        fy: n.__seedY,
      })),
      links: kg.edges.map((e) => {
        const adverseStyle = e.kind === 'adverse' ? strengthEdgeStyle(e.strength, dense) : null;
        return {
          source: e.source,
          target: e.target,
          color: adverseStyle?.color || EDGE_COLORS[e.kind] || '#475569',
          width: adverseStyle?.width ?? (dense
            ? (e.kind === 'adverse' ? 1.4 : 1)
            : (e.kind === 'adverse' ? 2.2 : e.kind === 'binds' ? 1.8 : 1.3)),
          kind: e.kind,
          prr: e.prr,
          ror: e.ror,
          strength: e.strength,
          confidence: e.confidence,
          severity: e.severity,
          post_count: e.post_count,
          signal_id: e.signal_id,
        };
      }),
    };
  }, [kg, dims.w, dims.h, canvasH]);

  const handleNodeClick = (n) => {
    setSelectedNodeId(n.id);
    if (n.type === 'drug') {
      setDrug(n.label || displayLabel(n));
      setSymptom('');
      setFocusNode(null);
    } else if (n.type === 'symptom') {
      setSymptom(n.label || displayLabel(n));
      setFocusNode(null);
    }
  };

  const toggleFocus = () => {
    if (focusNode === selectedNodeId) {
      setFocusNode(null);
    } else if (selectedNodeId) {
      setFocusNode(selectedNodeId);
    }
  };

  if (!kg) return <Spinner label="Building knowledge graph…" />;

  const hasFilters = drug || symptom || condition || country || strengthFilter;
  const fullNodeCount = rawKg?.stats?.node_count ?? kg.stats.node_count;
  const isFiltered = kg.filtered || hasFilters || focusNode;

  return (
    <div className="space-y-4">
{!embedded && (
      <div>
        <h2 className="text-lg font-semibold text-[var(--app-text)]">Knowledge Graph</h2>
        <p className="text-sm text-[var(--app-text-muted)] mt-1">
          Layered surveillance ontology — click a node for identity, metrics, and neighbors.
          {project?.name && <> Project: <strong>{project.name}</strong>.</>}
          {engine === 'fallback' && (
            <span className="text-amber-400/90"> (project SPARQL timed out — showing global graph fallback)</span>
          )}
          {engine === 'error' && (
            <span className="text-rose-400/90"> (graph failed to load — check backend is running)</span>
          )}
        </p>
      </div>

)}
      {kg.story && (kg.story.summary || kg.story.text || kg.story.top_paths?.length > 0) && (
        <Card className="p-4 border-[var(--app-border)]">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <CardHeader
                title="Pathway summary"
                subtitle={`${kg.story.path_count ?? kg.paths?.length ?? 0} drug→AE paths · ${kg.story.node_count ?? kg.stats?.node_count ?? 0} nodes · ${isFiltered ? 'filtered' : 'full'} view`}
              />
            </div>
            <span className="text-[10px] uppercase tracking-wide text-slate-500 mt-1">
              {kg.story.source === 'llm' ? 'legacy llm' : 'deterministic'}
            </span>
          </div>
          <p className="text-sm text-[var(--app-text-secondary)] mt-2 leading-relaxed">
            {kg.story.summary || kg.story.text}
          </p>
          {kg.story.top_paths?.length > 0 && (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="text-[10px] uppercase tracking-wide text-slate-500 border-b border-[var(--app-border)]">
                    <th className="py-1.5 pr-3 font-medium">Drug</th>
                    <th className="py-1.5 pr-3 font-medium">Adverse event</th>
                    <th className="py-1.5 pr-3 font-medium">PRR</th>
                    <th className="py-1.5 pr-3 font-medium">Tier</th>
                    <th className="py-1.5 font-medium">Regions</th>
                  </tr>
                </thead>
                <tbody>
                  {kg.story.top_paths.slice(0, 6).map((p) => (
                    <tr
                      key={`${p.drug}-${p.symptom}-${p.prr}`}
                      className="border-b border-[var(--app-border)]/60 text-slate-300 hover:bg-slate-800/40 cursor-pointer"
                      onClick={() => {
                        const match = kg.nodes?.find(
                          (n) => n.type === 'drug' && n.label?.toLowerCase() === (p.drug || '').toLowerCase(),
                        );
                        if (match) setSelectedNodeId(match.id);
                      }}
                    >
                      <td className="py-1.5 pr-3 text-sky-300 font-medium">{p.drug}</td>
                      <td className="py-1.5 pr-3 text-rose-300">{p.symptom}</td>
                      <td className="py-1.5 pr-3 tabular-nums">{p.prr ?? '—'}</td>
                      <td className="py-1.5 pr-3">
                        <span className={`rounded px-1.5 py-0.5 text-[10px] ${
                          p.strength === 'STRONG'
                            ? 'bg-rose-500/15 text-rose-300'
                            : p.strength === 'MODERATE'
                              ? 'bg-amber-500/15 text-amber-300'
                              : 'bg-slate-700/60 text-slate-400'
                        }`}
                        >
                          {p.strength || '—'}
                        </span>
                      </td>
                      <td className="py-1.5 text-slate-500 truncate max-w-[160px]">
                        {(p.regions || []).slice(0, 3).join(', ') || '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {kg.story.disclaimer && (
            <p className="text-[10px] text-slate-500 mt-3 leading-relaxed">{kg.story.disclaimer}</p>
          )}
        </Card>
      )}

      <Card className="p-4">
        <div className="flex flex-wrap gap-3 items-end">
          <FilterSelect
            label="Drug"
            value={drug}
            options={filterOpts.drugs}
            onChange={(v) => {
              setDrug(v);
              setSymptom('');
              setFocusNode(null);
              setSelectedNodeId(null);
              if (v && rawKg) {
                const n = rawKg.nodes?.find(
                  (x) => x.type === 'drug' && x.label?.toLowerCase() === v.toLowerCase(),
                );
                if (n) setSelectedNodeId(n.id);
              }
            }}
          />
          <FilterSelect
            label={drug ? `AEs for ${drug}` : 'Symptom / AE'}
            value={symptom}
            options={symptomFilterOptions}
            onChange={(v) => {
              setSymptom(v);
              setFocusNode(null);
              if (v && rawKg) {
                const n = rawKg.nodes?.find(
                  (x) => x.type === 'symptom' && x.label?.toLowerCase() === v.toLowerCase(),
                );
                if (n) setSelectedNodeId(n.id);
              } else {
                setSelectedNodeId(null);
              }
            }}
          />
          <FilterSelect label="Condition" value={condition} options={filterOpts.conditions}
            onChange={(v) => { setCondition(v); setFocusNode(null); setSelectedNodeId(null); }} />
          <FilterSelect label="Country / region" value={country}
            options={[...new Set([...filterOpts.countries, ...filterOpts.regions])].sort()}
            onChange={(v) => { setCountry(v); setFocusNode(null); setSelectedNodeId(null); }} />
          <FilterSelect
            label="Signal strength"
            value={strengthFilter}
            options={['STRONG', 'MODERATE', 'WEAK']}
            onChange={(v) => setStrengthFilter(v)}
          />
        </div>
        <ActiveFilterPills
          drug={drug}
          symptom={symptom}
          condition={condition}
          country={country}
          strength={strengthFilter}
          onClear={clearFilters}
        />
        {drug && (
          <div className="mt-4 rounded-lg border border-rose-500/25 bg-rose-500/5 p-3">
            <div className="flex items-center justify-between gap-2 mb-2">
              <h4 className="text-xs font-semibold text-rose-200">
                Adverse events linked to <span className="text-sky-300">{drug}</span>
                <span className="text-slate-500 font-normal ml-1">({drugAeCatalog.length})</span>
              </h4>
              {symptom && (
                <button type="button" className="text-[10px] text-teal-400" onClick={() => setSymptom('')}>
                  Clear AE filter
                </button>
              )}
            </div>
            {drugAeCatalog.length === 0 ? (
              <p className="text-xs text-slate-500">No AE paths for this drug in the current workspace graph.</p>
            ) : (
              <div className="flex flex-wrap gap-1.5 max-h-36 overflow-y-auto">
                {drugAeCatalog.map((a) => (
                  <button
                    key={a.symptom}
                    type="button"
                    onClick={() => {
                      setSymptom(a.symptom);
                      setFocusNode(null);
                      if (a.nodeId) setSelectedNodeId(a.nodeId);
                      else {
                        const n = rawKg?.nodes?.find(
                          (x) => x.type === 'symptom' && x.label?.toLowerCase() === a.symptom.toLowerCase(),
                        );
                        if (n) setSelectedNodeId(n.id);
                      }
                    }}
                    className={`rounded-md px-2.5 py-1 text-[11px] border transition-colors ${
                      symptom === a.symptom
                        ? 'bg-rose-500/25 border-rose-400/50 text-rose-100'
                        : 'bg-slate-900/60 border-slate-700 text-slate-300 hover:border-rose-500/40 hover:text-rose-200'
                    }`}
                  >
                    {a.symptom}
                    {a.prr != null && (
                      <span className="ml-1.5 tabular-nums text-slate-500">PRR {a.prr}</span>
                    )}
                    {a.strength && (
                      <span className="ml-1.5 inline-block align-middle">
                        <StrengthBadge value={a.strength} />
                      </span>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        {!drug && symptom && (
          <div className="mt-4 rounded-lg border border-sky-500/25 bg-sky-500/5 p-3">
            <h4 className="text-xs font-semibold text-sky-200 mb-2">
              Drugs reporting <span className="text-rose-300">{symptom}</span>
              <span className="text-slate-500 font-normal ml-1">({aeDrugCatalog.length})</span>
            </h4>
            {aeDrugCatalog.length === 0 ? (
              <p className="text-xs text-slate-500">No linked products for this AE in the current workspace graph.</p>
            ) : (
              <div className="flex flex-wrap gap-1.5 max-h-36 overflow-y-auto">
                {aeDrugCatalog.map((d) => (
                  <button
                    key={d.drug}
                    type="button"
                    onClick={() => {
                      setDrug(d.drug);
                      setFocusNode(null);
                      if (d.nodeId) setSelectedNodeId(d.nodeId);
                      else {
                        const n = rawKg?.nodes?.find(
                          (x) => x.type === 'drug' && x.label?.toLowerCase() === d.drug.toLowerCase(),
                        );
                        if (n) setSelectedNodeId(n.id);
                      }
                    }}
                    className="rounded-md px-2.5 py-1 text-[11px] border bg-slate-900/60 border-slate-700 text-slate-300 hover:border-sky-500/40"
                  >
                    {d.drug}
                    {d.prr != null && <span className="ml-1.5 text-slate-500">PRR {d.prr}</span>}
                    {d.strength && (
                      <span className="ml-1.5 inline-block align-middle">
                        <StrengthBadge value={d.strength} />
                      </span>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        <div className="flex flex-wrap gap-4 mt-3 text-[10px] text-[var(--app-text-faint)]">
          <div className="flex flex-wrap gap-3">
            {Object.entries(TYPE_META).map(([k, v]) => (
              <span key={k} className="flex items-center gap-1.5">
                <span className="inline-block w-2 h-2 rounded-full" style={{ background: v.color }} />
                {v.label}
              </span>
            ))}
          </div>
          <div className="flex flex-wrap gap-3 border-l border-slate-700 pl-4">
            <span className="text-slate-500 self-center">AE edge strength</span>
            {[
              { k: 'STRONG', c: STRENGTH_EDGE_COLORS.STRONG },
              { k: 'MODERATE', c: STRENGTH_EDGE_COLORS.MODERATE },
              { k: 'WEAK', c: STRENGTH_EDGE_COLORS.WEAK },
            ].map(({ k, c }) => (
              <span key={k} className="flex items-center gap-1.5">
                <span className="inline-block w-4 h-0.5 rounded" style={{ background: c }} />
                {k}
              </span>
            ))}
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Card className="p-3">
          <div className="text-[10px] uppercase tracking-wide text-slate-500">Nodes</div>
          <div className="text-2xl font-bold text-slate-100 tabular-nums">
            {kg.stats.node_count}
            {isFiltered && fullNodeCount !== kg.stats.node_count && (
              <span className="text-sm font-normal text-slate-500 ml-1">/ {fullNodeCount}</span>
            )}
          </div>
        </Card>
        <Card className="p-3">
          <div className="text-[10px] uppercase tracking-wide text-slate-500">Edges</div>
          <div className="text-2xl font-bold text-slate-100 tabular-nums">{kg.stats.edge_count ?? kg.edges?.length ?? 0}</div>
        </Card>
        <Card className="p-3">
          <div className="text-[10px] uppercase tracking-wide text-slate-500">Paths</div>
          <div className="text-2xl font-bold text-slate-100 tabular-nums">{kg.paths?.length ?? 0}</div>
        </Card>
        <Card className="p-3">
          <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1.5">Hubs — click to inspect</div>
          <div className="flex flex-wrap gap-1 max-h-[52px] overflow-y-auto">
            {(kg.hubs || []).slice(0, 8).map((h) => (
              <button
                key={h.id}
                type="button"
                onClick={() => setSelectedNodeId(h.id)}
                className={`rounded-md px-2 py-0.5 text-[10px] border transition-colors ${
                  selectedNodeId === h.id
                    ? 'bg-teal-500/20 border-teal-500/40 text-teal-200'
                    : 'bg-slate-800/80 border-slate-700/50 text-slate-300 hover:border-slate-500'
                }`}
              >
                <span className="w-1.5 h-1.5 rounded-full inline-block mr-1" style={{ background: TYPE_COLORS[h.type] }} />
                {h.label}
              </button>
            ))}
          </div>
        </Card>
      </div>

      <Card className="p-0 overflow-hidden border-[#3c4947] bg-[#051424]">
        <div className="px-4 pt-4 pb-2 flex flex-wrap items-end justify-between gap-2">
          <div>
            <h3 className="text-base font-semibold text-[#d4e4fa] flex items-center gap-2">
              <span className="text-[#4fdbc8]">⬡</span> Knowledge Graph Explorer
            </h3>
            <p className="text-xs text-[#859490] mt-1">
              Squares = drugs · diamonds = AEs · circles = targets/regions.
              Drug→AE edges are colored by strength (rose STRONG · amber MODERATE · slate WEAK).
              Click a drug to rank its AEs by tier.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2 mb-1">
            <div className="flex rounded border border-[#3c4947] overflow-hidden text-[10px]">
              {['auto', 'hubs', 'all'].map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setLabelMode(m)}
                  className={`px-2.5 py-1 uppercase tracking-wide ${
                    labelMode === m ? 'bg-[#14b8a6]/25 text-[#4fdbc8]' : 'text-[#859490] hover:bg-[#1c2b3c]'
                  }`}
                >
                  Labels: {m}
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={() => setHubsOnly((v) => !v)}
              className={`text-[10px] uppercase tracking-wide px-2.5 py-1 rounded border ${
                hubsOnly
                  ? 'border-[#4fdbc8]/50 text-[#4fdbc8] bg-[#14b8a6]/10'
                  : 'border-[#3c4947] text-[#859490]'
              }`}
              title="When crowded, keep top-degree nodes per column"
            >
              {hubsOnly ? 'Hubs density ON' : 'Hubs density OFF'}
            </button>
            {selectedNodeId && (
              <span className="text-[10px] text-[#4fdbc8]">Inspector open</span>
            )}
          </div>
        </div>
        {kg.densified && (
          <div className="px-4 pb-2 text-[11px] text-amber-300/90">
            Showing top hubs ({kg.stats.node_count} nodes)
            {kg.hidden_count ? ` · ${kg.hidden_count} lower-degree nodes hidden` : ''}.
            Turn off “Hubs density” or focus a neighborhood to see more.
          </div>
        )}
        <div className="flex flex-col xl:flex-row border-t border-[#3c4947]">
          <div className="xl:w-[30%] shrink-0 border-b xl:border-b-0 xl:border-r border-[#3c4947] p-3 bg-[#04101c]">
            <KgStorySidebar
              activeStoryStep={activeStoryStep}
              setActiveStoryStep={setActiveStoryStep}
              targetDrug={storyTargetDrug || drug}
              contrastDrugs={storyFocus.contrastDrugLabels}
              targetAes={storyFocus.targetAeLabels}
              drugOptions={filterOpts.drugs}
              onPickTarget={(v) => {
                setStoryTargetDrug(v);
                setDrug(v);
                setSymptom('');
                setFocusNode(null);
                if (v && rawKg) {
                  const n = rawKg.nodes?.find(
                    (x) => x.type === 'drug' && x.label?.toLowerCase() === v.toLowerCase(),
                  );
                  if (n) setSelectedNodeId(n.id);
                }
                if (v && activeStoryStep === 0) setActiveStoryStep(1);
              }}
            />
          </div>
          <div className="xl:w-[70%] flex flex-col lg:flex-row flex-1 min-w-0">
          <div className="flex-1 min-w-0 relative bg-[#010f1f]">
            <div className="h-8 flex border-b border-[#3c4947] bg-[#1c2b3c]/70 backdrop-blur-sm z-10 relative">
              {COLUMN_LABELS.map((c) => (
                <div
                  key={c.type}
                  className="flex-1 flex items-center justify-center text-[9px] uppercase tracking-wider text-[#859490] font-bold border-r border-[#3c4947] last:border-r-0"
                >
                  <span className="w-1.5 h-1.5 rounded-full mr-1.5" style={{ background: TYPE_COLORS[c.type] }} />
                  {c.label}
                </div>
              ))}
            </div>
            <div className="absolute inset-x-0 top-8 bottom-0 pointer-events-none z-[1] flex">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="flex-1 border-r border-dashed border-[#3c4947]/45" />
              ))}
              <div className="flex-1" />
            </div>
            {focusNode && (
              <button
                type="button"
                onClick={() => setFocusNode(null)}
                className="absolute top-10 left-3 z-10 text-xs text-[#4fdbc8] bg-[#051424]/95 px-2.5 py-1 rounded border border-[#4fdbc8]/40"
              >
                Clear neighborhood focus
              </button>
            )}
            <div ref={wrapRef} className="overflow-hidden relative z-[2]" style={{ height: canvasH }}>
              {graphData.nodes.length === 0 ? (
                <div className="flex items-center justify-center h-full text-sm text-[#859490]">
                  No nodes match filters — try clearing or ingest more data.
                </div>
              ) : (
                <ForceGraph2D
                  key={graphKey}
                  width={dims.w}
                  height={Math.max(dims.h, canvasH)}
                  graphData={graphData}
                  backgroundColor="rgba(0,0,0,0)"
                  nodeLabel={(n) => `${displayLabel(n)} · ${TYPE_META[n.type]?.label || n.type} · ${n.degree || 0} links`}
                  linkLabel={(l) => {
                    const em = EDGE_META[l.kind] || EDGE_META.adverse;
                    const bits = [em.label];
                    if (l.strength) bits.push(l.strength);
                    if (l.prr != null) bits.push(`PRR ${l.prr}`);
                    if (l.post_count != null) bits.push(`${l.post_count} posts`);
                    if (l.confidence != null) bits.push(`conf ${l.confidence}`);
                    return bits.join(' · ');
                  }}
                  nodeColor={(n) => TYPE_COLORS[n.type] || '#94a3b8'}
                  linkColor={(l) => {
                    const s = typeof l.source === 'object' ? l.source.id : l.source;
                    const t = typeof l.target === 'object' ? l.target.id : l.target;
                    if (activeStoryStep > 0 && storyFocus.hotIds.size) {
                      const hot = storyFocus.hotIds.has(s) && storyFocus.hotIds.has(t);
                      return hot ? l.color : 'rgba(60,73,71,0.18)';
                    }
                    if (!selectedNodeId) return l.color;
                    const hot = s === selectedNodeId || t === selectedNodeId;
                    return hot ? l.color : 'rgba(60,73,71,0.28)';
                  }}
                  linkWidth={(l) => {
                    const s = typeof l.source === 'object' ? l.source.id : l.source;
                    const t = typeof l.target === 'object' ? l.target.id : l.target;
                    if (activeStoryStep > 0 && storyFocus.hotIds.size) {
                      return (storyFocus.hotIds.has(s) && storyFocus.hotIds.has(t))
                        ? l.width + 1.4
                        : 0.4;
                    }
                    if (!selectedNodeId) return l.width;
                    const hot = s === selectedNodeId || t === selectedNodeId;
                    return hot ? l.width + 1.2 : 0.5;
                  }}
                  onNodeClick={handleNodeClick}
                  onBackgroundClick={() => { setSelectedNodeId(null); setFocusNode(null); }}
                  onNodeDrag={(node) => { node.fx = node.x; node.fy = node.y; }}
                  onNodeDragEnd={(node) => { node.fx = node.__colX; node.fy = node.__seedY; }}
                  linkDirectionalParticles={(l) => {
                    if (!selectedNodeId) return 0;
                    const s = typeof l.source === 'object' ? l.source.id : l.source;
                    const t = typeof l.target === 'object' ? l.target.id : l.target;
                    return (s === selectedNodeId || t === selectedNodeId) ? 2 : 0;
                  }}
                  linkDirectionalParticleWidth={2}
                  cooldownTicks={80}
                  d3AlphaDecay={0.06}
                  d3VelocityDecay={0.5}
                  nodeCanvasObject={(node, ctx, globalScale) => {
                    const isSelected = node.id === selectedNodeId;
                    const isNeighbor = neighborIds.has(node.id);
                    const storyOn = activeStoryStep > 0 && storyFocus.hotIds.size > 0;
                    const storyHot = storyOn && storyFocus.hotIds.has(node.id);
                    const dimmed = storyOn
                      ? !storyHot
                      : selectedNodeId && !isSelected && !isNeighbor;
                    const nCount = graphData.nodes.length;
                    const dense = nCount > 50;
                    const baseR = (dense ? 3.5 : 5) + Math.min(dense ? 5 : 7, (node.degree || 1) * (dense ? 0.35 : 0.55));
                    const r = isSelected || storyHot ? baseR + 3 : isNeighbor ? baseR + 1 : baseR;
                    const color = TYPE_COLORS[node.type] || '#94a3b8';
                    const name = displayLabel(node);
                    const paintLabel = shouldPaintLabel(node, {
                      mode: labelMode,
                      nodeCount: nCount,
                      isSelected: isSelected || storyHot,
                      isNeighbor: isNeighbor || storyHot,
                      hubDegree: dense ? 3 : 2,
                    });

                    ctx.globalAlpha = dimmed ? 0.15 : dense && !paintLabel && !isSelected && !storyHot ? 0.55 : 1.0;
                    if (isSelected || (storyHot && activeStoryStep === 1 && node.type === 'drug')) {
                      ctx.beginPath();
                      ctx.arc(node.x, node.y, r + 6, 0, 2 * Math.PI);
                      ctx.fillStyle = 'rgba(79, 219, 200, 0.22)';
                      ctx.fill();
                    }

                    ctx.fillStyle = color;
                    ctx.strokeStyle = isSelected ? '#5eead4' : storyHot ? '#fbbf24' : isNeighbor ? '#94a3b8' : 'rgba(0,0,0,0.35)';
                    ctx.lineWidth = (isSelected || storyHot ? 2.4 : 1) / globalScale;
                    ctx.beginPath();
                    if (node.type === 'drug') {
                      ctx.rect(node.x - r, node.y - r, r * 2, r * 2);
                    } else if (node.type === 'symptom') {
                      ctx.moveTo(node.x, node.y - r);
                      ctx.lineTo(node.x + r, node.y);
                      ctx.lineTo(node.x, node.y + r);
                      ctx.lineTo(node.x - r, node.y);
                      ctx.closePath();
                    } else if (node.type === 'condition') {
                      const w = r * 1.6;
                      const h = r * 0.9;
                      ctx.rect(node.x - w, node.y - h, w * 2, h * 2);
                    } else {
                      ctx.arc(node.x, node.y, r, 0, 2 * Math.PI, false);
                    }
                    ctx.fill();
                    ctx.stroke();
                    ctx.globalAlpha = 1;

                    if (!paintLabel) return;

                    const fontSize = Math.max(8, (isSelected || storyHot ? 12 : dense ? 9 : 10) / globalScale);
                    ctx.font = `${isSelected || storyHot ? '600' : '500'} ${fontSize}px Inter, "Segoe UI", sans-serif`;
                    const maxChars = isSelected || storyHot ? 26 : dense ? 12 : 16;
                    const label = name.length > maxChars ? `${name.slice(0, maxChars - 1)}…` : name;
                    const textW = ctx.measureText(label).width;
                    const padX = 3 / globalScale;
                    const padY = 1.5 / globalScale;
                    const side = node.__labelSide || 'right';
                    let tx = node.x;
                    let ty = node.y + r + fontSize + 2;
                    let align = 'center';
                    if (dense && !isSelected && !storyHot) {
                      align = side === 'left' ? 'right' : 'left';
                      tx = side === 'left' ? node.x - r - 4 : node.x + r + 4;
                      ty = node.y + fontSize / 3;
                    }
                    ctx.textAlign = align;
                    ctx.textBaseline = 'alphabetic';
                    if (!dense || isSelected || storyHot) {
                      ctx.fillStyle = dimmed ? 'rgba(5,20,36,0.35)' : 'rgba(5,20,36,0.9)';
                      const boxX = align === 'center' ? tx - textW / 2 - padX
                        : align === 'left' ? tx - padX
                          : tx - textW - padX;
                      ctx.fillRect(boxX, ty - fontSize + padY, textW + padX * 2, fontSize + padY * 2 + 1);
                    }
                    ctx.fillStyle = isSelected || storyHot ? '#f0fdfa' : dimmed ? '#64748b' : '#d4e4fa';
                    ctx.fillText(label || 'Unnamed', tx, ty);
                  }}
                />
              )}
            </div>
          </div>
          <NodeDetailPanel
            details={nodeDetails}
            onClose={() => { setSelectedNodeId(null); setFocusNode(null); }}
            onFocus={toggleFocus}
            onSelectNeighbor={(id) => setSelectedNodeId(id)}
            isFocused={focusNode === selectedNodeId}
            onFilterDrug={(label) => {
              setDrug(label);
              setStoryTargetDrug(label);
              setSymptom('');
              setFocusNode(null);
            }}
            onFilterAe={(label) => {
              setSymptom(label);
              setFocusNode(null);
            }}
          />
          </div>
        </div>
      </Card>
    </div>
  );
}
