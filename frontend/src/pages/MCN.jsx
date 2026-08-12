import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { Badge, Button, Card, CardHeader, Spinner } from '../components/ui';
import ConceptMappingTrace from '../modules/normalization/ConceptMappingTrace';
import GeographicResolutionTag from '../modules/normalization/GeographicResolutionTag';

/** Module 2 — Deep MCN: useful as search expansion + cohort counting, not a city dictionary. */
export default function MCN({ embedded = false }) {
  const [query, setQuery] = useState('Chennai Glycomet diarrhea');
  const [busy, setBusy] = useState(false);
  const [traceTerm, setTraceTerm] = useState('hard to stay awake');
  const [trace, setTrace] = useState(null);
  const [corpus, setCorpus] = useState(null);
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
      const clinicalGuess = query.trim().split(/\s+/).slice(-2).join(' ') || 'hard to stay awake';
      const [t, c, agg] = await Promise.all([
        api.normalizationTrace(traceTerm.trim() || clinicalGuess),
        api.normalizationCorpus(query.trim()),
        api.normalizationAggregate([
          { verbatim: 'diabetic', patient_count: 2 },
          { verbatim: 'Type 2 diabetic mellitus', patient_count: 3 },
          { verbatim: 'diabetes', patient_count: 5 },
        ]),
      ]);
      setTrace(t);
      setCorpus(c);
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

  const expansion = corpus?.expansion;
  const geoMatches = expansion?.geo?.matches || [];
  const teaching = corpus?.teaching;

  return (
    <div className="space-y-5">
      {!embedded && (
        <div>
          <h2 className="text-xl font-bold text-slate-100">Medical Concept Normalization</h2>
          <p className="text-sm text-slate-400 mt-1">
            Makes search and disproportionality honest — not a static city list.
          </p>
        </div>
      )}

      <Card className="p-4 border-amber-700/25">
        <CardHeader
          title="Why this exists (Pattabhi / RWD meet)"
          subtitle="Ontology is useful when it changes what you retrieve and how you count — not when it only shows a badge."
        />
        <ul className="mt-3 space-y-2 text-sm text-slate-300 list-disc pl-5">
          <li>
            <strong className="text-slate-100">Geo:</strong> search «Chennai» must also find narratives that say «Madras»
            (same for Bangalore/Bengaluru). Aliases expand the search bag.
          </li>
          <li>
            <strong className="text-slate-100">Clinical:</strong> diabetic + Type 2 diabetic mellitus + diabetes → one CUI;
            sum patient counts (2+3+5 → N=10) before PRR/ROR so vertical frequency tables do not fragment.
          </li>
          <li>
            <strong className="text-slate-100">Brand (Omni-Search):</strong> Janumet → chemicals + peer brands as Universe vs Subset.
            Use <Link className="text-cyan-400 hover:text-cyan-300" to="/signals">Safety Signals → Detect</Link> for brand / RxCUI Omni-Search.
          </li>
        </ul>
        {teaching && (
          <p className="mt-3 text-xs text-slate-500">{teaching.headline}</p>
        )}
      </Card>

      <Card className="p-4">
        <CardHeader
          title="Live expansion → corpus retrieval"
          subtitle="Type a city alias, disease slang, or both. We expand synonyms, then OR-search post title/body."
          right={
            <div className="flex flex-wrap gap-1.5">
              {status?.places != null && (
                <Badge value={`${status.places} cities`} className="bg-slate-700/40 text-slate-300 border-slate-600/40 text-[10px]" />
              )}
              {evalGate?.pass_gate && (
                <Badge value={`F1 ✓ ${evalGate.clinical?.f1}`} className="bg-emerald-500/15 text-emerald-200 border-emerald-500/30 text-[10px]" />
              )}
            </div>
          }
        />
        <form
          className="mt-3 flex flex-wrap gap-2"
          onSubmit={(e) => { e.preventDefault(); run(); }}
        >
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Chennai · Madras · Bangalore · diabetic Glycomet"
            className="min-w-[240px] flex-1 rounded-md border border-slate-800 bg-slate-950/60 px-3 py-2 text-sm text-slate-100"
          />
          <input
            value={traceTerm}
            onChange={(e) => setTraceTerm(e.target.value)}
            placeholder="Trace term — hard to stay awake"
            className="w-52 rounded-md border border-slate-800 bg-slate-950/60 px-3 py-2 text-sm text-slate-100"
          />
          <Button type="submit" disabled={busy}>{busy ? 'Expanding…' : 'Expand & search'}</Button>
        </form>
        <div className="mt-2 flex flex-wrap gap-1.5 text-[11px] text-slate-500">
          {['Chennai', 'Madras', 'Bengaluru', 'Bangalore', 'diabetic', 'Kyiv', 'Peking'].map((ex) => (
            <button
              key={ex}
              type="button"
              className="rounded border border-slate-700 px-1.5 py-0.5 text-slate-300 hover:border-slate-500"
              onClick={() => { setQuery(ex); }}
            >
              {ex}
            </button>
          ))}
        </div>
        {err && <p className="mt-3 text-sm text-rose-300">{err}</p>}
      </Card>

      {busy && !corpus && <Spinner label="Expanding + searching corpus…" />}

      {corpus && (
        <Card className="p-4">
          <CardHeader
            title="Expanded search bag → hits"
            subtitle={`${corpus.n_posts || 0} posts · ${corpus.n_signals || 0} signals`}
            right={
              <Link to="/sources" className="text-xs text-cyan-400 hover:text-cyan-300">
                Need hits? Load demo pack →
              </Link>
            }
          />
          {geoMatches.length > 0 && (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              {geoMatches.map((m) => (
                <GeographicResolutionTag key={m.canonical} resolution={m.resolution} />
              ))}
            </div>
          )}
          <div className="mt-3 flex flex-wrap gap-1">
            {(expansion?.search_terms || []).slice(0, 20).map((t) => (
              <Badge key={t} value={t} className="bg-slate-700/40 text-slate-300 border-slate-600/40 text-[10px]" />
            ))}
          </div>
          {(expansion?.why || []).map((w) => (
            <p key={w} className="mt-2 text-xs text-slate-400">{w}</p>
          ))}
          {(corpus.post_hits || []).length === 0 ? (
            <p className="mt-3 text-sm text-slate-400">
              Expansion worked, but this workspace has no narratives with these aliases yet.
              Demo pack now seeds Madras / Bangalore / Bombay / Calcutta / Peking / Trivandrum bodies —
              reload the pack, then search <strong className="text-slate-200">Chennai</strong>.
            </p>
          ) : (
            <div className="mt-3 space-y-2">
              {(corpus.post_hits || []).slice(0, 8).map((p) => (
                <div key={p.id} className="rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2 text-sm">
                  <div className="flex flex-wrap gap-1.5">
                    {(p.matched_terms || []).map((t) => (
                      <Badge key={t} value={t} className="bg-emerald-500/15 text-emerald-200 border-emerald-500/30 text-[10px]" />
                    ))}
                  </div>
                  <div className="mt-1 text-slate-200">{p.title}</div>
                  <div className="text-xs text-slate-400">{p.excerpt}</div>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

      {cohort && (
        <Card className="p-4">
          <CardHeader
            title="Cohort aggregation (disproportionality-ready N)"
            subtitle="Same disease, fragmented labels → one CUI, summed patients"
            right={<Badge value={`N=${cohort.total_patients}`} className="bg-amber-500/15 text-amber-200 border-amber-500/30 text-[10px]" />}
          />
          <div className="mt-3 space-y-2">
            {(cohort.cohorts || []).map((c) => (
              <div key={c.cui} className="rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-slate-100">{c.preferred}</span>
                  <span className="font-mono text-amber-200">N={c.patient_count}</span>
                </div>
                <div className="mt-1 text-xs text-slate-500">Variants: {(c.variants || []).join(' · ')}</div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {trace && (
        <Card className="p-4">
          <CardHeader title="Concept mapping trace" subtitle="Embed → cosine → MedDRA PT (debug)" />
          <div className="mt-3">
            <ConceptMappingTrace trace={trace} />
          </div>
        </Card>
      )}
    </div>
  );
}
