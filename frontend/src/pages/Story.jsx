import { useEffect, useMemo, useRef, useState } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import {
  Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { api, getToken } from '../api';
import { useProject } from '../projectContext';
import { Button, Card, CardHeader, Spinner } from '../components/ui';

const STEPS = [
  { n: 1, label: 'Hypothesis' },
  { n: 2, label: 'Drug A path' },
  { n: 3, label: 'Drug B contrast' },
  { n: 4, label: 'Summary' },
];

const TYPE_COLORS = {
  drug: '#38bdf8',
  symptom: '#f43f5e',
  region: '#94a3b8',
  condition: '#f59e0b',
  protein: '#14b8a6',
};

function MetricGrid({ metrics, accent }) {
  if (!metrics?.found) {
    return (
      <p className="text-sm text-amber-300/90 mt-2">
        No signal row found for this drug–event pair in the active workspace. Metrics show as zero in the chart.
      </p>
    );
  }
  const cells = [
    ['Cases', metrics.cases],
    ['PRR', metrics.prr],
    ['ROR', metrics.ror],
    ['IC₀₂₅', metrics.ic025],
    ['EBGM', metrics.ebgm],
    ['EB05', metrics.eb05],
    ['Strength', metrics.strength],
    ['Severity', metrics.severity_mix?.primary],
  ];
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3">
      {cells.map(([k, v]) => (
        <div
          key={k}
          className="rounded-lg border border-[var(--app-border)] bg-[var(--app-surface)] px-3 py-2"
          style={{ borderTopColor: accent, borderTopWidth: 2 }}
        >
          <div className="text-[10px] uppercase tracking-wide text-[var(--app-text-muted)]">{k}</div>
          <div className="text-lg font-semibold text-[var(--app-text)] tabular-nums">{v ?? '—'}</div>
        </div>
      ))}
    </div>
  );
}

function StoryGraphCanvas({ projectId, event, drugA, drugB, step }) {
  const wrapRef = useRef(null);
  const [dims, setDims] = useState({ w: 480, h: 420 });
  const [raw, setRaw] = useState(null);

  useEffect(() => {
    if (!event || !drugA || !projectId) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const [a, b] = await Promise.all([
          api.sparqlGraph(projectId, { drug: drugA, symptom: event }),
          drugB ? api.sparqlGraph(projectId, { drug: drugB, symptom: event }) : Promise.resolve(null),
        ]);
        if (cancelled) return;
        const byId = new Map();
        const edges = [];
        const edgeKeys = new Set();
        for (const g of [a, b].filter(Boolean)) {
          (g.nodes || []).forEach((n) => byId.set(n.id, n));
          (g.edges || []).forEach((e) => {
            const k = `${e.source}|${e.target}|${e.kind}`;
            if (!edgeKeys.has(k)) {
              edgeKeys.add(k);
              edges.push(e);
            }
          });
        }
        setRaw({ nodes: [...byId.values()], edges });
      } catch {
        if (!cancelled) setRaw(null);
      }
    })();
    return () => { cancelled = true; };
  }, [projectId, event, drugA, drugB]);

  useEffect(() => {
    if (!wrapRef.current) return undefined;
    const ro = new ResizeObserver((entries) => {
      const cr = entries[0].contentRect;
      setDims({ w: Math.max(280, cr.width), h: Math.max(360, cr.height) });
    });
    ro.observe(wrapRef.current);
    return () => ro.disconnect();
  }, []);

  const focusLabels = useMemo(() => {
    const set = new Set();
    if (step >= 1 && event) set.add(event.toLowerCase());
    if (step >= 2 && drugA) set.add(drugA.toLowerCase());
    if (step >= 3 && drugB) set.add(drugB.toLowerCase());
    return set;
  }, [step, event, drugA, drugB]);

  const graphData = useMemo(() => {
    if (!raw?.nodes?.length) return { nodes: [], links: [] };
    return {
      nodes: raw.nodes.map((n) => ({ ...n })),
      links: (raw.edges || []).map((e) => ({
        source: e.source,
        target: e.target,
        kind: e.kind,
        prr: e.prr,
        color: e.kind === 'adverse' ? '#f43f5e' : '#475569',
      })),
    };
  }, [raw]);

  const hotIds = useMemo(() => {
    const ids = new Set();
    graphData.nodes.forEach((n) => {
      if (focusLabels.has((n.label || '').toLowerCase())) ids.add(n.id);
    });
    graphData.links.forEach((l) => {
      const s = typeof l.source === 'object' ? l.source.id : l.source;
      const t = typeof l.target === 'object' ? l.target.id : l.target;
      if (ids.has(s)) ids.add(t);
      if (ids.has(t)) ids.add(s);
    });
    return ids;
  }, [graphData, focusLabels]);

  return (
    <div ref={wrapRef} className="h-full min-h-[420px] rounded-xl border border-[var(--app-border)] bg-[#010f1f] overflow-hidden">
      <div className="px-3 py-2 border-b border-[var(--app-border)] text-[10px] uppercase tracking-wide text-slate-500">
        Story canvas · step {step} · non-focus nodes at 15% opacity
      </div>
      {graphData.nodes.length === 0 ? (
        <div className="flex items-center justify-center h-[380px] text-sm text-slate-500">
          Select event + drugs to render the focused pathway.
        </div>
      ) : (
        <ForceGraph2D
          width={dims.w}
          height={dims.h - 36}
          graphData={graphData}
          backgroundColor="rgba(0,0,0,0)"
          nodeLabel={(n) => `${n.label} · ${n.type}`}
          linkLabel={(l) => (l.prr != null ? `PRR ${l.prr}` : l.kind)}
          cooldownTicks={60}
          d3AlphaDecay={0.08}
          nodeCanvasObject={(node, ctx, globalScale) => {
            const hot = hotIds.has(node.id);
            const r = hot ? 7 : 4;
            ctx.globalAlpha = hot ? 1 : 0.15;
            ctx.beginPath();
            ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
            ctx.fillStyle = TYPE_COLORS[node.type] || '#94a3b8';
            ctx.fill();
            if (hot) {
              const fontSize = 12 / globalScale;
              ctx.font = `${fontSize}px Sans-Serif`;
              ctx.fillStyle = '#e2e8f0';
              ctx.fillText(node.label || '', node.x + r + 2, node.y + fontSize / 3);
            }
            ctx.globalAlpha = 1;
          }}
          linkColor={(l) => {
            const s = typeof l.source === 'object' ? l.source.id : l.source;
            const t = typeof l.target === 'object' ? l.target.id : l.target;
            const hot = hotIds.has(s) && hotIds.has(t);
            return hot ? (l.color || '#f43f5e') : 'rgba(71,85,105,0.2)';
          }}
          linkWidth={(l) => {
            const s = typeof l.source === 'object' ? l.source.id : l.source;
            const t = typeof l.target === 'object' ? l.target.id : l.target;
            return hotIds.has(s) && hotIds.has(t) ? 2.2 : 0.4;
          }}
        />
      )}
    </div>
  );
}

export default function Story({ embedded = false }) {
  const { project } = useProject();
  const [candidates, setCandidates] = useState([]);
  const [event, setEvent] = useState('');
  const [drugA, setDrugA] = useState('');
  const [drugB, setDrugB] = useState('');
  const [step, setStep] = useState(1);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');

  useEffect(() => {
    const load = project?.id
      ? api.storyCandidates(project.id)
      : api.storyCandidatesGlobal();
    load.then((rows) => {
      setCandidates(rows || []);
      if (rows?.length) {
        setEvent(rows[0].event);
        setDrugA(rows[0].pair[0]);
        setDrugB(rows[0].pair[1]);
      } else {
        setEvent('');
        setDrugA('');
        setDrugB('');
      }
    }).catch(() => setCandidates([]));
  }, [project?.id]);

  const selected = useMemo(
    () => candidates.find((c) => c.event === event) || null,
    [candidates, event],
  );
  const drugOptions = selected?.drugs || [];

  const onEventChange = (ev) => {
    setEvent(ev);
    const c = candidates.find((x) => x.event === ev);
    if (c?.pair?.length >= 2) {
      setDrugA(c.pair[0]);
      setDrugB(c.pair[1]);
    } else {
      setDrugA('');
      setDrugB('');
    }
  };

  const onDrugAChange = (d) => {
    setDrugA(d);
    if (d === drugB) {
      const alt = drugOptions.find((x) => x !== d);
      if (alt) setDrugB(alt);
    }
  };

  const onDrugBChange = (d) => {
    setDrugB(d);
    if (d === drugA) {
      const alt = drugOptions.find((x) => x !== d);
      if (alt) setDrugA(alt);
    }
  };

  const run = () => {
    if (!event || !drugA || !drugB || drugA === drugB) return;
    setLoading(true);
    setErr('');
    setStep(1);
    const drugs = `${drugA},${drugB}`;
    const req = project?.id
      ? api.story(project.id, event, drugs)
      : api.storyGlobal(event, drugs);
    req
      .then(setData)
      .catch((e) => { setData(null); setErr(e.message || 'Story failed'); })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (event && drugA && drugB && drugA !== drugB) run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [event, drugA, drugB, project?.id]);

  const chartData = useMemo(() => data?.chart || [], [data]);
  const stepPayload = data?.steps?.find((s) => s.step === step);

  const downloadPdf = async () => {
    const drugs = `${drugA},${drugB}`;
    const url = project?.id
      ? api.storyPdfUrl(project.id, event, drugs)
      : api.storyPdfUrlGlobal(event, drugs);
    const headers = {};
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    if (project?.id) headers['X-Project-Id'] = String(project.id);
    const res = await fetch(url, { headers });
    if (!res.ok) throw new Error(`PDF ${res.status}`);
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `vigilai_story_${event.replace(/\s+/g, '_')}.pdf`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  if (!project && candidates.length === 0 && !data) {
    return <Spinner label="Loading story candidates…" />;
  }

  return (
    <div className="space-y-4">
      {!embedded && (
        <div>
          <h2 className="text-lg font-semibold text-[var(--app-text)]">Signal Validation Story</h2>
          <p className="text-sm text-[var(--app-text-muted)] mt-1">
            Guided A/B comparison with a live graph canvas — Next Step isolates Drug A, then brings Drug B in for contrast.
          </p>
        </div>
      )}

      <div className="grid lg:grid-cols-2 gap-4 items-stretch">
        <div className="space-y-4">
          <Card className="p-4 space-y-3">
            <CardHeader title="Comparator setup" subtitle="Event and both drugs from workspace signals" />
            {!candidates.length && (
              <p className="text-sm text-amber-300/90">
                No shared drug–event pairs yet. Ingest more AE posts, then reopen Story.
              </p>
            )}
            <div className="grid gap-3">
              <label className="text-xs text-[var(--app-text-muted)] block">
                Event (MedDRA PT / symptom)
                <select className="mt-1 w-full" value={event}
                  onChange={(e) => onEventChange(e.target.value)} disabled={!candidates.length}>
                  {candidates.map((c) => (
                    <option key={c.event} value={c.event}>{c.event} ({c.n_drugs} drugs)</option>
                  ))}
                </select>
              </label>
              <div className="grid grid-cols-2 gap-2">
                <label className="text-xs text-[var(--app-text-muted)] block">
                  Drug A
                  <select className="mt-1 w-full" value={drugA}
                    onChange={(e) => onDrugAChange(e.target.value)} disabled={!drugOptions.length}>
                    {drugOptions.map((d) => <option key={`a-${d}`} value={d}>{d}</option>)}
                  </select>
                </label>
                <label className="text-xs text-[var(--app-text-muted)] block">
                  Drug B
                  <select className="mt-1 w-full" value={drugB}
                    onChange={(e) => onDrugBChange(e.target.value)} disabled={!drugOptions.length}>
                    {drugOptions.filter((d) => d !== drugA).map((d) => (
                      <option key={`b-${d}`} value={d}>{d}</option>
                    ))}
                  </select>
                </label>
              </div>
            </div>
            <div className="flex flex-wrap gap-2 pt-1">
              {STEPS.map((s) => (
                <Button
                  key={s.n}
                  type="button"
                  size="sm"
                  variant={step === s.n ? 'gradient' : 'ghost'}
                  onClick={() => setStep(s.n)}
                >
                  {s.n}. {s.label}
                </Button>
              ))}
            </div>
            <div className="flex gap-2">
              <Button type="button" variant="outline" disabled={step <= 1}
                onClick={() => setStep((s) => Math.max(1, s - 1))}>
                Previous
              </Button>
              <Button type="button" variant="gradient" disabled={step >= 4}
                onClick={() => setStep((s) => Math.min(4, s + 1))}>
                Next Step
              </Button>
            </div>
            {err && <p className="text-sm text-rose-400">{err}</p>}
          </Card>

          {loading && <Spinner label="Building validation story…" />}

          {data && !loading && stepPayload && (
            <Card className="p-5 min-h-[180px]">
              <CardHeader title={`Step ${step}: ${stepPayload.title}`} />
              {step === 1 && (
                <div className="mt-3 space-y-2 text-sm text-[var(--app-text-secondary)]">
                  <p>{stepPayload.hypothesis}</p>
                  <p className="text-[var(--app-text-muted)] italic">{stepPayload.null}</p>
                </div>
              )}
              {step === 2 && <MetricGrid metrics={stepPayload.metrics} accent="#14b8a6" />}
              {step === 3 && <MetricGrid metrics={stepPayload.metrics} accent="#f59e0b" />}
              {step === 4 && (
                <div className="mt-3 space-y-3">
                  <p className="text-sm leading-relaxed text-[var(--app-text-secondary)]">{stepPayload.summary}</p>
                  <Button type="button" variant="gradient"
                    onClick={() => downloadPdf().catch((e) => setErr(e.message))}>
                    Download PDF report
                  </Button>
                </div>
              )}
            </Card>
          )}

          {data && !loading && (
            <Card className="p-4">
              <CardHeader title="Side-by-side metrics" subtitle={data.disclaimer} />
              <div className="h-56 mt-3">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="metric" tick={{ fontSize: 11 }} stroke="#64748b" />
                    <YAxis tick={{ fontSize: 10 }} stroke="#64748b" />
                    <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #334155' }} />
                    <Legend />
                    <Bar dataKey="drug_a" name={data.drugs?.[0] || 'Drug A'} fill="#14b8a6" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="drug_b" name={data.drugs?.[1] || 'Drug B'} fill="#f59e0b" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
          )}
        </div>

        <StoryGraphCanvas
          projectId={project?.id}
          event={event}
          drugA={drugA}
          drugB={drugB}
          step={step}
        />
      </div>
    </div>
  );
}
