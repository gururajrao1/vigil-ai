import { useEffect, useState } from 'react';
import { api } from '../api';
import { Badge, Button, Card, CardHeader, Spinner } from '../components/ui';
import ConceptMappingTrace from '../modules/normalization/ConceptMappingTrace';
import GeographicResolutionTag from '../modules/normalization/GeographicResolutionTag';

/** Module 2 — Deep Medical Concept Normalization playground. */
export default function MCN({ embedded = false }) {
  const [clinical, setClinical] = useState('hard to stay awake');
  const [location, setLocation] = useState('Madras');
  const [busy, setBusy] = useState(false);
  const [trace, setTrace] = useState(null);
  const [geo, setGeo] = useState(null);
  const [cohort, setCohort] = useState(null);
  const [evalGate, setEvalGate] = useState(null);
  const [status, setStatus] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    api.normalizationStatus().then(setStatus).catch(() => setStatus(null));
    api.normalizationEval().then(setEvalGate).catch(() => setEvalGate(null));
  }, []);

  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      const [t, g, agg] = await Promise.all([
        api.normalizationTrace(clinical.trim()),
        api.normalizationGeo(location.trim()),
        api.normalizationAggregate([
          { verbatim: 'diabetic', patient_count: 2 },
          { verbatim: 'Type 2 diabetic mellitus', patient_count: 3 },
          { verbatim: 'diabetes', patient_count: 5 },
        ]),
      ]);
      setTrace(t);
      setGeo(g);
      setCohort(agg);
    } catch (e) {
      const msg = e.message || String(e);
      setErr(/404|Not Found/i.test(msg)
        ? 'MCN API not on this backend yet — deploy the latest API, then refresh.'
        : msg);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      {!embedded && (
        <div>
          <h2 className="text-xl font-bold text-slate-100">Medical Concept Normalization</h2>
          <p className="text-sm text-slate-400 mt-1">
            SapBERT + FAISS UMLS linking with MedDRA / SNOMED dual map and geographic alias resolution.
          </p>
        </div>
      )}

      <Card className="p-4">
        <CardHeader
          title="MCN playground"
          subtitle="Consumer slang and municipal aliases → UMLS CUI, MedDRA PT, SNOMED-CT, and city centroids."
          right={
            <div className="flex flex-wrap gap-1.5">
              {status?.encoder_backend && (
                <Badge value={status.encoder_backend} className="bg-cyan-500/10 text-cyan-200 border-cyan-500/30 text-[10px]" />
              )}
              {status?.faiss_enabled != null && (
                <Badge
                  value={status.faiss_enabled ? 'FAISS on' : 'numpy cosine'}
                  className="bg-slate-700/40 text-slate-300 border-slate-600/40 text-[10px]"
                />
              )}
              {evalGate && (
                <Badge
                  value={evalGate.pass_gate ? `F1 gate ✓ ${evalGate.clinical?.f1}` : `F1 gate ✗`}
                  className={evalGate.pass_gate
                    ? 'bg-emerald-500/15 text-emerald-200 border-emerald-500/30 text-[10px]'
                    : 'bg-rose-500/15 text-rose-200 border-rose-500/30 text-[10px]'}
                />
              )}
            </div>
          }
        />
        <form
          className="mt-3 flex flex-wrap gap-2"
          onSubmit={(e) => { e.preventDefault(); run(); }}
        >
          <input
            value={clinical}
            onChange={(e) => setClinical(e.target.value)}
            placeholder="Clinical slang — hard to stay awake"
            className="min-w-[220px] flex-1 rounded-md border border-slate-800 bg-slate-950/60 px-3 py-2 text-sm text-slate-100"
          />
          <input
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            placeholder="City alias — Madras"
            className="w-44 rounded-md border border-slate-800 bg-slate-950/60 px-3 py-2 text-sm text-slate-100"
          />
          <Button type="submit" disabled={busy}>{busy ? 'Normalizing…' : 'Normalize'}</Button>
        </form>
        {err && <p className="mt-3 text-sm text-rose-300">{err}</p>}
      </Card>

      {busy && !trace && <Spinner label="Embedding + linking…" />}

      {trace && (
        <Card className="p-4">
          <CardHeader title="Concept mapping trace" subtitle="Embed → cosine k-NN → MedNorm dual map" />
          <div className="mt-3">
            <ConceptMappingTrace trace={trace} />
          </div>
        </Card>
      )}

      {geo && (
        <Card className="p-4">
          <CardHeader title="Geographic resolution" subtitle="GeoNames-style municipal alias → canonical city" />
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <GeographicResolutionTag resolution={geo} />
            {geo.country && <span className="text-xs text-slate-500">{geo.admin1}, {geo.country}</span>}
            {geo.geonames_id && <span className="font-mono text-[11px] text-slate-500">{geo.geonames_id}</span>}
          </div>
        </Card>
      )}

      {cohort && (
        <Card className="p-4">
          <CardHeader
            title="Cohort aggregation"
            subtitle="diabetic(2) + Type 2 diabetic mellitus(3) + diabetes(5) → unified N"
            right={<Badge value={`N=${cohort.total_patients}`} className="bg-amber-500/15 text-amber-200 border-amber-500/30 text-[10px]" />}
          />
          <div className="mt-3 space-y-2">
            {(cohort.cohorts || []).map((c) => (
              <div key={c.cui} className="rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-slate-100">{c.preferred}</span>
                  <span className="font-mono text-amber-200">N={c.patient_count}</span>
                </div>
                <div className="mt-1 font-mono text-[11px] text-cyan-300/80">{c.cui}</div>
                <div className="mt-1 text-xs text-slate-500">
                  Variants: {(c.variants || []).join(' · ')}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
