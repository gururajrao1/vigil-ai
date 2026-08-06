import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { useRefresh } from '../App';
import { Badge, Button, Card, Spinner } from '../components/ui';

/** Proactive risk stratification + REM ranking of high-risk subpopulations. */
export default function RiskPopulations({ embedded = false }) {
  const { tick, bump } = useRefresh();
  const [mode, setMode] = useState('rank'); // 'rank' | 'predict'
  const [data, setData] = useState(null);
  const [productId, setProductId] = useState('');
  const [targetAe, setTargetAe] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const loadRank = (pid, ae) => {
    if (!pid?.trim() || !ae?.trim()) {
      // Bootstrap candidates then rank densest pair
      setBusy(true);
      setErr(null);
      api.riskStrata({})
        .then((boot) => {
          const pairs = boot.candidate_pairs || [];
          const p = pid || boot.product_id || pairs[0]?.product_id;
          const a = ae || boot.target_ae_pt || pairs[0]?.target_ae_pt;
          if (!p || !a) {
            setData({
              ...boot,
              ranked: [],
              findings: [],
              needs_demo_seed: true,
              headline: boot.headline || 'No AE corpus — load PV demo pack.',
              method: 'risk_elevation_multiplier',
            });
            return;
          }
          setProductId(p);
          setTargetAe(a);
          return api.riskStrataRank(p, a, 8).then((d) => {
            setData({ ...d, candidate_pairs: pairs.length ? pairs : d.candidate_pairs });
          });
        })
        .catch((e) => {
          setData(null);
          setErr(e?.message || 'Failed to rank risk strata');
        })
        .finally(() => setBusy(false));
      return;
    }
    setBusy(true);
    setErr(null);
    api.riskStrataRank(pid.trim(), ae.trim(), 8)
      .then(setData)
      .catch((e) => {
        setData(null);
        setErr(e?.message || 'Failed to rank risk strata');
      })
      .finally(() => setBusy(false));
  };

  const loadPredict = (pid, ae) => {
    setBusy(true);
    setErr(null);
    const params = {};
    if (pid) params.product_id = pid;
    if (ae) params.target_ae_pt = ae;
    api.riskStrata(params)
      .then((d) => {
        setData(d);
        if (d?.product_id && !pid) setProductId(d.product_id);
        if (d?.target_ae_pt && !ae) setTargetAe(d.target_ae_pt);
      })
      .catch((e) => {
        setData(null);
        setErr(e?.message || 'Failed to load risk strata');
      })
      .finally(() => setBusy(false));
  };

  const load = (pid, ae) => {
    if (mode === 'rank') loadRank(pid, ae);
    else loadPredict(pid, ae);
  };

  useEffect(() => {
    const sp = new URLSearchParams(window.location.search);
    const pid = sp.get('product_id') || '';
    const ae = sp.get('target_ae_pt') || '';
    if (pid) setProductId(pid);
    if (ae) setTargetAe(ae);
    load(pid || undefined, ae || undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, mode]);

  const run = () => {
    if (!productId.trim() || !targetAe.trim()) {
      setErr('Enter both a product and a target AE (MedDRA-style PT).');
      return;
    }
    load(productId.trim(), targetAe.trim());
  };

  const loadDemo = async () => {
    setBusy(true);
    try {
      await api.ingestPvDemo({ recompute: true });
      bump?.();
      load();
    } catch (e) {
      setErr(e?.message || String(e));
    }
    setBusy(false);
  };

  if (!data && busy) return <Spinner label="Ranking high-risk subpopulations…" />;
  if (!data && err) {
    return (
      <Card className="p-4">
        <p className="text-sm text-rose-300">{err}</p>
        <Button className="mt-3" onClick={() => load()}>Retry</Button>
      </Card>
    );
  }
  if (!data) return <Spinner label="Ranking high-risk subpopulations…" />;

  const findings = data.ranked || data.findings || data.segments || [];
  const pairs = data.candidate_pairs || [];
  const isRank = mode === 'rank' || data.method === 'risk_elevation_multiplier';

  return (
    <div className="space-y-5">
      {!embedded && (
        <div>
          <h2 className="text-xl font-bold text-slate-100">Proactive risk populations</h2>
          <p className="text-sm text-slate-400 mt-1">
            {data.how_to_use
              || 'Rank subpopulations by Risk Elevation Multiplier before severe harm accumulates.'}
          </p>
        </div>
      )}

      <div className="flex flex-wrap gap-1.5">
        {[
          { id: 'rank', label: 'REM ranking' },
          { id: 'predict', label: 'Logistic segments' },
        ].map((m) => (
          <button
            key={m.id}
            type="button"
            onClick={() => setMode(m.id)}
            className={`rounded-full border px-3 py-1 text-xs transition ${
              mode === m.id
                ? 'bg-sky-500/20 text-sky-200 border-sky-500/40'
                : 'bg-slate-900 text-slate-400 border-slate-700 hover:text-slate-200'
            }`}
          >
            {m.label}
          </button>
        ))}
      </div>

      <div className="flex flex-col sm:flex-row gap-2">
        <input
          type="text"
          value={productId}
          onChange={(e) => setProductId(e.target.value)}
          placeholder="Product (drug / vaccine / device)…"
          className="flex-1 rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500"
        />
        <input
          type="text"
          value={targetAe}
          onChange={(e) => setTargetAe(e.target.value)}
          placeholder="Target AE (MedDRA-style PT)…"
          className="flex-1 rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500"
        />
        <Button variant="primary" disabled={busy} onClick={run}>
          {busy ? 'Scoring…' : (isRank ? 'Rank strata' : 'Predict segments')}
        </Button>
        <Button disabled={busy} onClick={loadDemo}>Load PV demo</Button>
      </div>

      <p className="text-sm text-slate-200">{data.headline || data.verdict}</p>
      {isRank && data.formula && (
        <p className="text-[11px] font-mono text-slate-500">{data.formula}</p>
      )}
      <div className="flex flex-wrap gap-2 text-[11px] text-slate-500">
        {data.model && <span>model: {data.model}</span>}
        {data.method && <span>method: {data.method}</span>}
        {data.n_drug_exposed != null && <span>· n_exposed={data.n_drug_exposed}</span>}
        {data.n_training_rows != null && <span>· n={data.n_training_rows}</span>}
        {data.baseline_p_ae != null && <span>· baseline P(AE)={data.baseline_p_ae}</span>}
        {data.baseline_risk != null && <span>· baseline={data.baseline_risk}</span>}
        {data.product_domain && <span>· domain={data.product_domain}</span>}
      </div>
      {err && <p className="text-sm text-rose-300">{err}</p>}

      {pairs.length > 0 && (
        <Card className="p-3">
          <div className="text-[10px] uppercase text-slate-500 mb-2">Candidate pairs in corpus</div>
          <div className="flex flex-wrap gap-1.5">
            {pairs.slice(0, 10).map((p) => (
              <button
                key={`${p.product_id}|${p.target_ae_pt}`}
                type="button"
                onClick={() => {
                  setProductId(p.product_id);
                  setTargetAe(p.target_ae_pt);
                  load(p.product_id, p.target_ae_pt);
                }}
                className="rounded-md border border-slate-700 bg-slate-900/60 px-2 py-1 text-[11px] text-slate-300 hover:border-sky-600/50 hover:text-sky-200 capitalize"
              >
                {p.product_id} → {p.target_ae_pt} <span className="text-slate-500">n={p.n}</span>
              </button>
            ))}
          </div>
        </Card>
      )}

      {findings.length === 0 ? (
        <Card className="p-4 text-sm text-slate-400">
          {data.needs_demo_seed
            ? 'Sparse corpus — load the PV demo pack, then pick a candidate pair.'
            : 'No elevated strata cleared the gates for this pair.'}
        </Card>
      ) : (
        <div className="space-y-3">
          {findings.map((s, idx) => {
            const rem = s.risk_elevation_multiplier ?? s.relative_risk_elevation;
            const mit = s.mitigation;
            return (
              <Card key={s.segment_id || s.stratum_id || s.label} className="p-4 border-amber-700/25">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium text-slate-100 flex items-center gap-2 flex-wrap">
                      {isRank && (
                        <span className="text-[10px] text-slate-500 font-mono">#{idx + 1}</span>
                      )}
                      {s.label}
                      {s.passes_gates === false && (
                        <span className="text-[10px] text-amber-400/80">exploratory</span>
                      )}
                    </div>
                    <p className="mt-1 text-[12px] text-slate-400 capitalize">
                      {s.product} → {s.target_ae_pt}
                      {s.product_domain ? ` · ${s.product_domain}` : ''}
                    </p>
                    {s.attribution_narrative && (
                      <p className="mt-2 text-sm text-amber-100/90 leading-relaxed">
                        {s.attribution_narrative}
                      </p>
                    )}
                    <p className="mt-2 text-sm text-slate-300 leading-relaxed">
                      {s.actionable_insight}
                    </p>
                    {(s.top_contributing_factors || []).length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {s.top_contributing_factors.map((f) => (
                          <span
                            key={`${f.factor}-${f.shap_value}`}
                            className={`rounded px-1.5 py-0.5 text-[10px] border ${
                              f.direction === 'elevates'
                                ? 'bg-rose-500/10 text-rose-300 border-rose-500/25'
                                : 'bg-sky-500/10 text-sky-300 border-sky-500/25'
                            }`}
                            title={f.note}
                          >
                            {f.factor}
                            {f.attribution_pct != null
                              ? ` ${f.attribution_pct}%`
                              : ` ${f.shap_value > 0 ? '+' : ''}${f.shap_value}`}
                          </span>
                        ))}
                      </div>
                    )}
                    {mit?.recommendations?.length > 0 && (
                      <div className="mt-3 rounded-lg border border-slate-700/80 bg-slate-950/40 p-3">
                        <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1">
                          Mitigation · {mit.trigger}
                          {mit.labeling_section ? ` · ${mit.labeling_section}` : ''}
                        </div>
                        <ul className="space-y-1 text-[12px] text-slate-300 list-disc list-inside">
                          {mit.recommendations.map((r) => (
                            <li key={r.slice(0, 48)}>{r}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                  <div className="flex flex-col gap-1.5 items-end shrink-0">
                    {isRank ? (
                      <>
                        <Badge
                          value={`REM ${rem}×`}
                          className={
                            rem >= 2
                              ? 'bg-rose-500/15 text-rose-300 border-rose-500/30'
                              : 'bg-amber-500/15 text-amber-300 border-amber-500/30'
                          }
                        />
                        <div className="text-[11px] text-slate-400">
                          χ² {s.chi_square_yates ?? '—'}
                        </div>
                        <div className="text-[10px] text-slate-500">
                          P(AE|sub) {s.p_ae_subpopulation} · n={s.n_cases ?? s.n_ae_in_subpopulation}
                        </div>
                      </>
                    ) : (
                      <>
                        <Badge
                          value={`risk ${s.predicted_risk_score}`}
                          className={
                            s.predicted_risk_score >= 0.7
                              ? 'bg-rose-500/15 text-rose-300 border-rose-500/30'
                              : 'bg-amber-500/15 text-amber-300 border-amber-500/30'
                          }
                        />
                        <div className="text-[11px] text-amber-200/90">
                          {s.relative_risk_elevation}× baseline
                        </div>
                        <div className="text-[10px] text-slate-500">n={s.n_cases} cases</div>
                      </>
                    )}
                    <Link
                      to={`/signals?q=${encodeURIComponent(s.product)}&symptom=${encodeURIComponent(s.target_ae_pt || '')}`}
                      className="text-xs text-sky-300 hover:underline"
                    >
                      Open in Detect →
                    </Link>
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      {data.ontology_stack?.length > 0 && (
        <p className="text-[10px] text-slate-500">
          Ontologies: {(data.ontology_stack || []).join(' · ')}
        </p>
      )}
      {data.disclaimer && <p className="text-[10px] text-slate-500 leading-relaxed">{data.disclaimer}</p>}
    </div>
  );
}
