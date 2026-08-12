import { useState } from 'react';
import { api } from '../api';
import { Badge, Card, CardHeader } from '../components/ui';
import OmniSearchGateway from '../modules/search/OmniSearchGateway';
import UniverseVersusSubsetFilter from '../modules/search/UniverseVersusSubsetFilter';
import ATCClassExplorer from '../modules/search/ATCClassExplorer';
import GeographicResolutionTag from '../modules/normalization/GeographicResolutionTag';
import { usePharmacovigilance } from '../context/PharmacovigilanceContext';

/** Module 1 — Unified Search & Global Brand-to-Chemical Mapping (+ MCN expansions). */
export default function OmniSearch({ embedded = false }) {
  const { setFromOmniSearch } = usePharmacovigilance();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [result, setResult] = useState(null);
  const [selected, setSelected] = useState([]);

  const run = async (term, subsetList) => {
    setBusy(true);
    setErr(null);
    try {
      const subset = (subsetList || selected).join(',');
      const data = await api.searchOmni(term, { subset, includeAnalytics: true });
      setResult(data);
      const brands = data?.resolution?.subset_brands || [];
      const brand = data?.resolution?.brand_name;
      if (!subsetList && selected.length === 0) {
        setSelected(brand ? [brand] : brands.slice(0, 2));
      }
      const rxcui =
        data?.resolution?.ingredients?.[0]?.rxcui
        || data?.resolution?.brand_rxcui
        || null;
      setFromOmniSearch({
        term,
        rxcui,
        brands: brands,
        meddraPt: data?.extracted?.find((s) => s.kind === 'event')?.normalized_hint || null,
      });
    } catch (e) {
      const msg = e.message || String(e);
      setErr(/404|Not Found/i.test(msg)
        ? 'Omni-Search API not on this backend yet — deploy the latest API, then refresh.'
        : msg);
    } finally {
      setBusy(false);
    }
  };

  const resolution = result?.resolution;
  const report = result?.universe_subset;
  const expansions = result?.expansions;
  const corpus = result?.corpus_hits;
  const geoMatches = expansions?.geo?.matches || [];
  const clinicalMatches = expansions?.clinical?.matches || [];
  const searchTerms = expansions?.search_terms || [];

  return (
    <div className="space-y-5">
      {!embedded && (
        <div>
          <h2 className="text-xl font-bold text-slate-100">Omni-Search</h2>
          <p className="text-sm text-slate-400 mt-1">
            One search box for brand / chemical / device / disease slang / city alias —
            expands ontologies, then retrieves matching corpus reports.
          </p>
        </div>
      )}

      <Card className="p-4">
        <CardHeader
          title="Unified search gateway"
          subtitle="Pattabhi pattern: Janumet → chemicals + peer brands (Universe vs Subset); Chennai → also Madras; diabetic → Diabetes mellitus cohort N."
        />
        <div className="mt-3">
          <OmniSearchGateway onResolved={(term) => run(term)} busy={busy} />
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5 text-[11px] text-slate-500">
          <span>Try:</span>
          {['Janumet', 'Chennai adverse events', 'Bangalore', 'diabetic', 'ozmpic', 'Coumadin'].map((ex) => (
            <button
              key={ex}
              type="button"
              className="rounded border border-slate-700 px-1.5 py-0.5 text-slate-300 hover:border-slate-500"
              onClick={() => run(ex)}
            >
              {ex}
            </button>
          ))}
        </div>
        {err && <p className="mt-3 text-sm text-rose-300">{err}</p>}
      </Card>

      {expansions && (geoMatches.length > 0 || clinicalMatches.length > 0 || searchTerms.length > 1) && (
        <Card className="p-4 border-cyan-700/30">
          <CardHeader
            title="Ontology expansions (what the search actually queries)"
            subtitle="Aliases are for retrieval — not a static dictionary. Every chip below is OR-matched against post title/body and signals."
          />
          {geoMatches.length > 0 && (
            <div className="mt-3">
              <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1.5">Geographic synonyms</div>
              <div className="flex flex-wrap gap-2">
                {geoMatches.map((m) => (
                  <GeographicResolutionTag key={m.canonical} resolution={m.resolution} />
                ))}
              </div>
              <p className="mt-2 text-xs text-slate-400">
                {geoMatches[0]?.why}
              </p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {(geoMatches[0]?.aliases || []).map((a) => (
                  <Badge key={a} value={a} className="bg-emerald-500/10 text-emerald-200 border-emerald-500/30 text-[10px]" />
                ))}
              </div>
            </div>
          )}
          {clinicalMatches.length > 0 && (
            <div className="mt-4">
              <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1.5">Clinical synonym collapse</div>
              {clinicalMatches.map((m) => (
                <div key={m.cui} className="mb-2 rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-slate-100">{m.meddra_pt}</span>
                    <span className="font-mono text-[11px] text-cyan-300">{m.cui}</span>
                  </div>
                  <p className="mt-1 text-xs text-slate-400">{m.patient_count_rule}</p>
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {(m.aliases || []).slice(0, 10).map((a) => (
                      <Badge key={a} value={a} className="bg-amber-500/10 text-amber-100 border-amber-500/30 text-[10px]" />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
          {searchTerms.length > 0 && (
            <div className="mt-3 pt-3 border-t border-slate-800">
              <div className="text-[11px] text-slate-500 mb-1">Full search bag ({searchTerms.length} terms)</div>
              <div className="flex flex-wrap gap-1">
                {searchTerms.slice(0, 24).map((t) => (
                  <Badge key={t} value={t} className="bg-slate-700/40 text-slate-300 border-slate-600/40 text-[10px]" />
                ))}
              </div>
            </div>
          )}
        </Card>
      )}

      {corpus && (
        <Card className="p-4">
          <CardHeader
            title="Corpus hits from expanded terms"
            subtitle={`${corpus.n_posts || 0} posts · ${corpus.n_signals || 0} signals — proof the alias expansion retrieves real reports`}
            right={
              <Link to="/sources" className="text-xs text-cyan-400 hover:text-cyan-300">
                Load demo pack →
              </Link>
            }
          />
          {(corpus.post_hits || []).length === 0 && (corpus.signal_hits || []).length === 0 && (
            <p className="mt-3 text-sm text-slate-400">
              No narrative hits yet for these aliases. Load the PV demo pack (includes Madras / Bangalore /
              Bombay city-alias injects), then search <strong className="text-slate-200">Chennai</strong> or{' '}
              <strong className="text-slate-200">Bengaluru</strong> again.
            </p>
          )}
          {(corpus.post_hits || []).length > 0 && (
            <div className="mt-3 space-y-2">
              {(corpus.post_hits || []).slice(0, 6).map((p) => (
                <div key={p.id} className="rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2 text-sm">
                  <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                    <span>{p.platform}</span>
                    <span>·</span>
                    <span>{p.country || p.region || '—'}</span>
                    {(p.matched_terms || []).slice(0, 4).map((t) => (
                      <Badge key={t} value={t} className="bg-emerald-500/15 text-emerald-200 border-emerald-500/30 text-[10px]" />
                    ))}
                  </div>
                  <div className="mt-1 text-slate-200">{p.title || 'Untitled'}</div>
                  <div className="mt-0.5 text-xs text-slate-400 line-clamp-2">{p.excerpt}</div>
                </div>
              ))}
            </div>
          )}
          {(corpus.signal_hits || []).length > 0 && (
            <div className="mt-4">
              <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1.5">Matching signals</div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="text-slate-500">
                    <tr className="text-left">
                      <th className="py-1 pr-3">Product</th>
                      <th className="py-1 pr-3">Event</th>
                      <th className="py-1 pr-3">PT</th>
                      <th className="py-1 pr-3 text-right">N</th>
                      <th className="py-1 pr-3">Strength</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(corpus.signal_hits || []).slice(0, 8).map((s) => (
                      <tr key={s.id} className="border-t border-slate-800/70">
                        <td className="py-1.5 pr-3 text-slate-200">{s.drug}</td>
                        <td className="py-1.5 pr-3 text-slate-300">{s.event}</td>
                        <td className="py-1.5 pr-3 text-slate-400">{s.meddra_pt || '—'}</td>
                        <td className="py-1.5 pr-3 text-right tabular-nums">{s.post_count}</td>
                        <td className="py-1.5 pr-3">{s.strength}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </Card>
      )}

      {resolution?.matched && (
        <Card className="p-4">
          <CardHeader
            title="Brand → chemical resolution"
            subtitle={resolution.match_method}
            right={
              <div className="flex flex-wrap gap-1.5">
                {resolution.status && (
                  <Badge
                    value={resolution.status}
                    className={resolution.status === 'discontinued'
                      ? 'bg-amber-500/15 text-amber-200 border-amber-500/30 text-[10px]'
                      : 'bg-emerald-500/15 text-emerald-200 border-emerald-500/30 text-[10px]'}
                  />
                )}
                <Badge value="offline RxE" className="bg-slate-700/40 text-slate-300 border-slate-600/40 text-[10px]" />
              </div>
            }
          />
          <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3 text-xs text-slate-400">
            <div>
              <div className="text-[11px] uppercase tracking-wide text-slate-500">Query</div>
              <div className="text-slate-200">{resolution.query_term}</div>
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-wide text-slate-500">Brand RxCUI</div>
              <div className="font-mono text-slate-200">{resolution.brand_rxcui || '—'}</div>
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-wide text-slate-500">UMLS CUI</div>
              <div className="font-mono text-slate-200">{resolution.umls_cui || '—'}</div>
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-wide text-slate-500">Manufacturers</div>
              <div className="text-slate-200">{(resolution.manufacturer_hints || []).join(', ') || '—'}</div>
            </div>
          </div>
          <div className="mt-3">
            <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1">Has_Ingredient</div>
            <div className="flex flex-wrap gap-2">
              {(resolution.ingredients || []).map((ing) => (
                <Badge
                  key={ing.generic}
                  value={`${ing.generic}${ing.atc ? ` · ${ing.atc}` : ''}`}
                  className="bg-violet-500/15 text-violet-200 border-violet-500/30 text-[10px]"
                />
              ))}
            </div>
          </div>
          {(result?.extracted || []).length > 0 && (
            <div className="mt-3 pt-3 border-t border-slate-800">
              <div className="text-[11px] text-slate-500 mb-1">Extracted spans (PharmaCoNER / CADEC / SMM4H surrogates)</div>
              <div className="flex flex-wrap gap-1.5">
                {result.extracted.map((s, i) => (
                  <Badge
                    key={`${s.text}-${i}`}
                    value={`${s.kind}: ${s.text}`}
                    className="bg-slate-700/40 text-slate-300 border-slate-600/40 text-[10px]"
                  />
                ))}
              </div>
            </div>
          )}
          {(result?.notes || []).map((n) => (
            <p key={n} className="mt-2 text-[11px] text-amber-200/80">{n}</p>
          ))}
        </Card>
      )}

      {resolution?.matched && <ATCClassExplorer resolution={resolution} />}

      {resolution?.matched && (
        <UniverseVersusSubsetFilter
          resolution={resolution}
          report={report}
          selected={selected}
          onChangeSelected={setSelected}
          onRerun={(brands) => run(resolution.query_term, brands)}
        />
      )}

      {result?.audit?.disclaimer && (
        <p className="text-[11px] text-slate-600">{result.audit.disclaimer}</p>
      )}
    </div>
  );
}
