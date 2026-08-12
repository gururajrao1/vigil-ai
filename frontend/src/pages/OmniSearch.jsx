import { useState } from 'react';
import { api } from '../api';
import { Badge, Card, CardHeader } from '../components/ui';
import OmniSearchGateway from '../modules/search/OmniSearchGateway';
import UniverseVersusSubsetFilter from '../modules/search/UniverseVersusSubsetFilter';
import ATCClassExplorer from '../modules/search/ATCClassExplorer';

/** Module 1 — Unified Search & Global Brand-to-Chemical Mapping. */
export default function OmniSearch({ embedded = false }) {
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

  return (
    <div className="space-y-5">
      {!embedded && (
        <div>
          <h2 className="text-xl font-bold text-slate-100">Omni-Search</h2>
          <p className="text-sm text-slate-400 mt-1">
            Brand → chemical mapping with Universe vs Subset disproportionality.
          </p>
        </div>
      )}

      <Card className="p-4">
        <CardHeader
          title="Unified search gateway"
          subtitle="Noisy patient text and international brands resolve to generic ingredients, RxCUIs, and ATC — then compare manufacturer subsets against the chemical universe."
        />
        <div className="mt-3">
          <OmniSearchGateway onResolved={(term) => run(term)} busy={busy} />
        </div>
        {err && <p className="mt-3 text-sm text-rose-300">{err}</p>}
      </Card>

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
