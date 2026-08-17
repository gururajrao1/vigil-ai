import { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import { Badge, Button, Card, CardHeader, PaginationBar, Spinner } from '../components/ui';

const DEMO_TEXT =
  'Started Accutane (isotretinoin) last month and my mood dropped into depression. Denies chest pain. Terrible headaches.';

const MATRIX_PAGE = 25;

/** Collapse cohort rows into densest product→event pairs for filter chips. */
function topPairsFromMatrix(rows, limit = 12) {
  const ctr = new Map();
  for (const r of rows || []) {
    const p = (r.product || '').trim();
    const e = (r.event || '').trim();
    if (!p || !e) continue;
    const key = `${p}|${e}`;
    const prev = ctr.get(key) || { product_id: p, target_ae_pt: e, n: 0 };
    prev.n += Number(r.n_cases) || 0;
    ctr.set(key, prev);
  }
  return [...ctr.values()].sort((a, b) => b.n - a.n).slice(0, limit);
}

/**
 * Phase 1–2 predictive intelligence workbench:
 * Feature Store (X) · 4-gate NLP · OMOP staging · privacy hygiene.
 */
export default function PredictiveIntelligence({ embedded = false }) {
  const [tab, setTab] = useState('matrix');
  const [matrix, setMatrix] = useState(null);
  const [pairChips, setPairChips] = useState([]);
  const [productId, setProductId] = useState('');
  const [targetAe, setTargetAe] = useState('');
  const [gateText, setGateText] = useState(DEMO_TEXT);
  const [gateOut, setGateOut] = useState(null);
  const [useOptionalBionlp, setUseOptionalBionlp] = useState(false);
  const [omop, setOmop] = useState(null);
  const [hygiene, setHygiene] = useState(null);
  const [benchmark, setBenchmark] = useState(null);
  const [backends, setBackends] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [bootstrapped, setBootstrapped] = useState(false);
  const [matrixPage, setMatrixPage] = useState(1);

  const loadMatrix = (pid = productId, ae = targetAe) => {
    setBusy(true);
    setErr(null);
    const p = (pid ?? productId).trim();
    const a = (ae ?? targetAe).trim();
    api.featureStoreMatrix({
      productId: p || undefined,
      targetAe: a || undefined,
      includeExplainability: false,
    })
      .then((d) => {
        setMatrix(d);
        if (!p && !a) {
          const chips = topPairsFromMatrix(d.matrix || [], 12);
          setPairChips(chips);
          // Auto-focus densest pair without a second full-corpus matrix build
          if (!bootstrapped && chips[0]) {
            setBootstrapped(true);
            setProductId(chips[0].product_id);
            setTargetAe(chips[0].target_ae_pt);
            setMatrix({
              ...d,
              matrix: (d.matrix || []).filter(
                (r) =>
                  String(r.product || '').toLowerCase() === String(chips[0].product_id).toLowerCase()
                  && String(r.event || '').toLowerCase() === String(chips[0].target_ae_pt).toLowerCase()
              ),
            });
          }
        } else if (pairChips.length === 0) {
          setPairChips(topPairsFromMatrix(d.matrix || [], 12));
        }
      })
      .catch((e) => setErr(e?.message || 'Feature matrix failed'))
      .finally(() => setBusy(false));
  };

  const applyPair = (p, e) => {
    setProductId(p);
    setTargetAe(e);
    setMatrixPage(1);
    loadMatrix(p, e);
  };

  const clearFilters = () => {
    setProductId('');
    setTargetAe('');
    setMatrixPage(1);
    loadMatrix('', '');
  };

  const runFourGate = () => {
    setBusy(true);
    setErr(null);
    api.fourGate(gateText, { useOptionalBionlp })
      .then(setGateOut)
      .catch((e) => setErr(e?.message || '4-gate failed'))
      .finally(() => setBusy(false));
  };

  const loadOmop = () => {
    setBusy(true);
    setErr(null);
    Promise.all([api.omopStats(), api.optionalBackends()])
      .then(([stats, be]) => {
        setOmop(stats);
        setBackends(be);
      })
      .catch((e) => setErr(e?.message || 'OMOP stats failed'))
      .finally(() => setBusy(false));
  };

  const syncOmop = () => {
    setBusy(true);
    setErr(null);
    api.omopSync({ limit: 200 })
      .then((s) => {
        setOmop(s);
        return api.omopStats();
      })
      .then((stats) => setOmop((prev) => ({ ...prev, ...stats })))
      .catch((e) => setErr(e?.message || 'OMOP sync failed'))
      .finally(() => setBusy(false));
  };

  const runHygiene = () => {
    setBusy(true);
    setErr(null);
    api.privacyHygiene({
      title: 'Forum post',
      body: gateText,
      author: 'patient_user_demo',
    })
      .then(setHygiene)
      .catch((e) => setErr(e?.message || 'Hygiene failed'))
      .finally(() => setBusy(false));
  };

  const runBenchmark = () => {
    setBusy(true);
    setErr(null);
    api.bioieBenchmark()
      .then(setBenchmark)
      .catch((e) => setErr(e?.message || 'Benchmark failed'))
      .finally(() => setBusy(false));
  };

  useEffect(() => {
    if (tab === 'matrix' && !matrix) loadMatrix('', '');
    if (tab === 'omop' && !omop) loadOmop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  const rows = matrix?.matrix || [];
  const shown = useMemo(() => {
    const start = (Math.max(1, matrixPage) - 1) * MATRIX_PAGE;
    return rows.slice(start, start + MATRIX_PAGE);
  }, [rows, matrixPage]);
  const chips = pairChips.length ? pairChips : topPairsFromMatrix(rows, 24);

  const tabs = [
    { id: 'matrix', label: 'Feature matrix X' },
    { id: 'gates', label: '4-gate NLP' },
    { id: 'omop', label: 'OMOP · privacy' },
    { id: 'eval', label: 'BioIE eval' },
  ];

  const shell = (
    <div className={embedded ? 'space-y-4' : 'space-y-5 max-w-6xl'}>
      {!embedded && (
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Predictive intelligence</h1>
          <p className="text-sm text-slate-400 mt-1">
            Phase 1–2 spine: privacy hygiene → OMOP staging → 4-gate NLP → Product–Event–Cohort feature matrix.
          </p>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {tabs.map((t) => (
          <Button
            key={t.id}
            type="button"
            size="sm"
            variant={tab === t.id ? 'gradient' : 'ghost'}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </Button>
        ))}
      </div>

      {err && (
        <div className="rounded border border-rose-700/40 bg-rose-950/30 px-3 py-2 text-sm text-rose-300">
          {err}
        </div>
      )}

      {tab === 'matrix' && (
        <Card className="p-4">
          <CardHeader
            title="Product–Event–Cohort feature matrix"
            subtitle="PRR / ROR / χ² / EB05 / IC025 + demographics + comorbidities + GNN centrality"
            right={
              <div className="flex gap-2">
                <Button onClick={clearFilters} disabled={busy}>All pairs</Button>
                <Button variant="primary" onClick={() => loadMatrix()} disabled={busy}>
                  {busy ? 'Loading…' : 'Apply filter'}
                </Button>
              </div>
            }
          />
          <div className="mt-3 flex flex-wrap gap-2 items-center">
            <input
              className="bg-slate-950 border border-slate-700 rounded px-2 py-1.5 text-sm text-slate-200 w-44"
              placeholder="Product filter"
              value={productId}
              onChange={(e) => setProductId(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && loadMatrix()}
            />
            <input
              className="bg-slate-950 border border-slate-700 rounded px-2 py-1.5 text-sm text-slate-200 w-44"
              placeholder="Event / PT filter"
              value={targetAe}
              onChange={(e) => setTargetAe(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && loadMatrix()}
            />
            <span className="text-[11px] text-slate-500">
              Tip: pick a chip below, or type e.g. isotretinoin + depression
            </span>
          </div>
          {chips.length > 0 && (
            <div className="mt-3">
              <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1.5">
                Dense pairs in corpus — click to filter
              </div>
              <div className="flex flex-wrap gap-1.5">
                {chips.map((p) => {
                  const on =
                    productId === p.product_id && targetAe === p.target_ae_pt;
                  return (
                    <Button
                      key={`${p.product_id}|${p.target_ae_pt}`}
                      type="button"
                      size="sm"
                      variant={on ? 'glass' : 'outline'}
                      onClick={() => applyPair(p.product_id, p.target_ae_pt)}
                      className="capitalize"
                    >
                      {p.product_id} → {p.target_ae_pt}{' '}
                      <span className="opacity-60">n={p.n}</span>
                    </Button>
                  );
                })}
              </div>
            </div>
          )}
          {busy && !matrix ? (
            <Spinner label="Building feature matrix…" />
          ) : matrix ? (
            <div className="mt-4 space-y-3">
              <div className="flex flex-wrap gap-3 text-xs text-slate-500">
                <span>
                  rows: <span className="text-slate-200">{matrix.n_rows}</span>
                </span>
                <span>
                  AE posts: <span className="text-slate-200">{matrix.n_source_ae_posts}</span>
                </span>
                <span>
                  features: <span className="text-slate-200">{matrix.feature_names?.length}</span>
                </span>
                {(productId || targetAe) && (
                  <span className="text-sky-300/80 capitalize">
                    filter: {productId || 'any'} → {targetAe || 'any'}
                  </span>
                )}
              </div>
              <PaginationBar
                page={matrixPage}
                pageSize={MATRIX_PAGE}
                total={rows.length}
                onPageChange={setMatrixPage}
                label="cohort rows"
              />
              {shown.length === 0 ? (
                <p className="text-sm text-slate-400">
                  No cohort rows for this filter — try another chip or Clear.
                </p>
              ) : (
                <div className="max-h-[28rem] overflow-auto rounded border border-slate-800">
                  <table className="min-w-full text-xs">
                    <thead className="bg-slate-950 text-slate-400 sticky top-0 z-10">
                      <tr>
                        <th className="text-left p-2">Product</th>
                        <th className="text-left p-2">Event</th>
                        <th className="text-left p-2">Cohort</th>
                        <th className="text-right p-2">n</th>
                        <th className="text-right p-2">PRR</th>
                        <th className="text-right p-2">ROR</th>
                        <th className="text-right p-2">χ²</th>
                        <th className="text-right p-2">EB05</th>
                        <th className="text-right p-2">IC025</th>
                        <th className="text-right p-2">GNN</th>
                      </tr>
                    </thead>
                    <tbody>
                      {shown.map((r, i) => (
                        <tr key={i} className="border-t border-slate-800/80 text-slate-300">
                          <td className="p-2 capitalize">{r.product}</td>
                          <td className="p-2 capitalize">{r.event}</td>
                          <td className="p-2 font-mono text-[10px] text-slate-500">{r.cohort}</td>
                          <td className="p-2 text-right tabular-nums">{r.n_cases}</td>
                          <td className="p-2 text-right tabular-nums">{Number(r.prr_score || 0).toFixed(2)}</td>
                          <td className="p-2 text-right tabular-nums">{Number(r.ror_score || 0).toFixed(2)}</td>
                          <td className="p-2 text-right tabular-nums">{Number(r.chi_square || 0).toFixed(1)}</td>
                          <td className="p-2 text-right tabular-nums">{Number(r.eb05_score || 0).toFixed(2)}</td>
                          <td className="p-2 text-right tabular-nums">{Number(r.ic025_score || 0).toFixed(2)}</td>
                          <td className="p-2 text-right tabular-nums">{Number(r.gnn_degree_centrality || 0).toFixed(3)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <PaginationBar
                page={matrixPage}
                pageSize={MATRIX_PAGE}
                total={rows.length}
                onPageChange={setMatrixPage}
                label="cohort rows"
              />
              <p className="text-[11px] text-slate-500">{matrix.disclaimer}</p>
            </div>
          ) : null}
        </Card>
      )}

      {tab === 'gates' && (
        <Card className="p-4">
          <CardHeader
            title="4-gate deterministic NLP"
            subtitle="Brand→generic · ontology map · polarity · non-negation"
            right={
              <Button variant="primary" onClick={runFourGate} disabled={busy}>
                {busy ? 'Running…' : 'Run 4-gate'}
              </Button>
            }
          />
          <textarea
            className="mt-3 w-full h-28 bg-slate-950 border border-slate-700 rounded p-2 text-sm text-slate-200"
            value={gateText}
            onChange={(e) => setGateText(e.target.value)}
          />
          <label className="mt-2 flex items-center gap-2 text-xs text-slate-500">
            <input
              type="checkbox"
              checked={useOptionalBionlp}
              onChange={(e) => setUseOptionalBionlp(e.target.checked)}
            />
            Use optional RoBERTa / scispaCy when cached locally (slower first load)
          </label>
          {gateOut && (
            <div className="mt-4 space-y-3">
              <div className="flex flex-wrap gap-2 items-center">
                <Badge
                  value={gateOut.ae_flag ? `AE ${(gateOut.ae_confidence * 100).toFixed(0)}%` : 'No AE'}
                  className={
                    gateOut.ae_flag
                      ? 'bg-rose-500/15 text-rose-300 border-rose-500/30'
                      : 'bg-slate-600/25 text-slate-300 border-slate-600/40'
                  }
                />
                <span className="text-xs text-slate-400">{gateOut.reason}</span>
                {gateOut.sentiment && (
                  <Badge
                    value={`${gateOut.sentiment.label} · ${gateOut.sentiment.model || 'vader'}`}
                    className="bg-sky-500/15 text-sky-300 border-sky-500/30"
                  />
                )}
              </div>
              <div className="space-y-1.5">
                {(gateOut.gate_trace || []).map((g) => (
                  <div key={g.gate} className="text-xs flex gap-2 items-start">
                    <span className={(g.passed || g.status) ? 'text-emerald-400' : 'text-rose-400'}>
                      {(g.passed || g.status) ? '✓' : '✕'}
                    </span>
                    <span className="text-slate-300">
                      Gate {g.gate}: {g.bioie_name || g.name}
                      <span className="text-slate-500"> — {g.detail}</span>
                    </span>
                  </div>
                ))}
              </div>
              <div className="text-[11px] text-slate-500">
                drugs: {(gateOut.entities?.drugs || []).map((d) => d.generic || d.normalized).join(', ') || '—'}
                {' · '}
                symptoms: {(gateOut.entities?.symptoms || []).map((s) => s.pt || s.normalized).join(', ') || '—'}
              </div>
            </div>
          )}
        </Card>
      )}

      {tab === 'omop' && (
        <div className="space-y-4">
          <Card className="p-4">
            <CardHeader
              title="OMOP CDM v5.4 staging"
              subtitle="person · drug_exposure · device_exposure · condition_occurrence"
              right={
                <div className="flex gap-2">
                  <Button onClick={loadOmop} disabled={busy}>Refresh</Button>
                  <Button variant="primary" onClick={syncOmop} disabled={busy}>
                    {busy ? 'Syncing…' : 'Sync from corpus'}
                  </Button>
                </div>
              }
            />
            {omop ? (
              <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                {[
                  ['Persons', omop.persons],
                  ['Drug exposures', omop.drug_exposures],
                  ['Device exposures', omop.device_exposures],
                  ['Conditions', omop.condition_occurrences],
                ].map(([k, v]) => (
                  <div key={k} className="rounded border border-slate-800 bg-slate-950/50 p-3">
                    <div className="text-[11px] text-slate-500">{k}</div>
                    <div className="text-xl font-mono text-slate-100">{v ?? 0}</div>
                  </div>
                ))}
              </div>
            ) : busy ? <Spinner label="Loading OMOP…" /> : null}
            {omop?.disclaimer && (
              <p className="mt-3 text-[11px] text-slate-500">{omop.disclaimer}</p>
            )}
            {backends && (
              <div className="mt-3 text-[11px] text-slate-500">
                Optional BioNLP: transformers={String(backends.transformers_installed)} ·
                RoBERTa loaded={String(backends.roberta_loaded)} ·
                scispaCy loaded={String(backends.scispacy_loaded)}
              </div>
            )}
          </Card>

          <Card className="p-4">
            <CardHeader
              title="Privacy hygiene preview"
              subtitle="HMAC author hash · PII tokens · content hash (does not write)"
              right={
                <Button variant="primary" onClick={runHygiene} disabled={busy}>
                  Scrub demo text
                </Button>
              }
            />
            {hygiene && (
              <div className="mt-3 space-y-2 text-xs text-slate-400">
                <div>action: <span className="text-slate-200">{hygiene.action}</span></div>
                <div className="font-mono break-all">author_hash: {hygiene.author_hash}</div>
                <div className="font-mono break-all">content_hash: {hygiene.content_hash}</div>
                <div>tokens: {(hygiene.tokens_applied || []).join(', ') || '—'}</div>
                <div>pii types: {(hygiene.pii_types || []).join(', ') || '—'}</div>
                <p className="text-slate-300 whitespace-pre-wrap border-t border-slate-800 pt-2">
                  {hygiene.scrubbed_text}
                </p>
              </div>
            )}
          </Card>
        </div>
      )}

      {tab === 'eval' && (
        <Card className="p-4">
          <CardHeader
            title="BioIE benchmark adapter"
            subtitle="BC5CDR / NCBI Disease–style P/R/F1 (embedded fixture offline)"
            right={
              <Button variant="primary" onClick={runBenchmark} disabled={busy}>
                {busy ? 'Evaluating…' : 'Run eval'}
              </Button>
            }
          />
          {benchmark && (
            <div className="mt-4 space-y-2 text-sm">
              <div className="flex flex-wrap gap-3 text-xs text-slate-500">
                <span>docs: <span className="text-slate-200">{benchmark.n_documents}</span></span>
                <span>P: <span className="text-slate-200">{benchmark.micro?.precision}</span></span>
                <span>R: <span className="text-slate-200">{benchmark.micro?.recall}</span></span>
                <span>F1: <span className="text-emerald-300">{benchmark.micro?.f1}</span></span>
              </div>
              <p className="text-[11px] text-slate-500">{benchmark.note}</p>
            </div>
          )}
        </Card>
      )}
    </div>
  );

  return shell;
}
