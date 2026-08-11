import { useEffect, useState } from 'react';
import { api } from '../api';
import { Badge, Card, CardHeader, Spinner } from '../components/ui';

/**
 * Ingredient identity: ATC ladder, ChEBI ID, SMILES, and structural neighbours
 * scored by Tanimoto similarity.
 */
export default function ChemicalStructureCard({ term = '', embedded = false }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!term) return undefined;
    let cancelled = false;
    setBusy(true);
    setErr(null);
    api.ontologyEngineDrugChemical(term)
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => {
        if (cancelled) return;
        const msg = e.message || String(e);
        setErr(/404|Not Found/i.test(msg)
          ? 'Ontology engine API not on this backend yet — deploy the latest API, then refresh.'
          : msg);
      })
      .finally(() => { if (!cancelled) setBusy(false); });
    return () => { cancelled = true; };
  }, [term]);

  if (!term) return null;
  if (data && !data.matched && !busy) return null;

  const chem = data?.chemical;
  const levels = data?.atc_levels || [];
  const similar = data?.similar_drugs || [];

  return (
    <Card className={embedded ? 'p-4' : 'p-4 border-violet-700/40'}>
      <CardHeader
        title="Chemical identity — ATC ladder and structure"
        subtitle={`Ingredient normalization and chemistry for "${term}"`}
        right={(
          <div className="flex items-center gap-2">
            {data?.preferred_generic && (
              <Badge value={data.preferred_generic} className="bg-violet-500/15 text-violet-200 border-violet-500/30 text-[10px]" />
            )}
            <Badge value="ChEBI subset" className="bg-slate-700/40 text-slate-300 border-slate-600/40 text-[10px]" />
          </div>
        )}
      />

      {busy && !data && <div className="mt-3"><Spinner label="Resolving chemistry…" /></div>}
      {err && <p className="mt-3 text-sm text-rose-300">{err}</p>}

      {data && (
        <div className="mt-4 space-y-4">
          <div className="flex flex-wrap gap-3 text-[11px] text-slate-500">
            {data.atc_code && <span>ATC: <span className="font-mono text-slate-200">{data.atc_code}</span></span>}
            {data.rxnorm_id && <span>RxNorm: <span className="font-mono text-slate-200">{data.rxnorm_id}</span></span>}
            {data.cui && <span>CUI: <span className="font-mono text-slate-200">{data.cui}</span></span>}
            {chem?.chebi_id && <span>ChEBI: <span className="font-mono text-slate-200">{chem.chebi_id}</span></span>}
            {chem?.formula && <span>formula: <span className="font-mono text-slate-200">{chem.formula}</span></span>}
          </div>

          {levels.length > 0 && (
            <div className="space-y-1.5">
              {levels.map((lvl) => (
                <div key={lvl.code} className="flex items-center gap-2 text-xs">
                  <span className="w-8 text-[10px] uppercase tracking-wide text-slate-500">L{lvl.level}</span>
                  <span className="w-16 font-mono text-slate-300">{lvl.code}</span>
                  <span className="flex-1 text-slate-300">{lvl.label}</span>
                  <span className="hidden md:inline text-[10px] text-slate-600">{lvl.level_name}</span>
                </div>
              ))}
            </div>
          )}

          {chem?.smiles ? (
            <div>
              <div className="text-[11px] uppercase tracking-wide text-slate-500">SMILES</div>
              <div className="mt-1 rounded-md border border-slate-800 bg-slate-950/60 px-3 py-2 font-mono text-[11px] text-slate-200 break-all">
                {chem.smiles}
              </div>
            </div>
          ) : (
            <p className="text-xs text-slate-400">
              {chem?.is_macromolecule
                ? 'Biologic / macromolecule — no small-molecule SMILES, so structural similarity does not apply.'
                : 'No SMILES for this ingredient in the ChEBI demo subset.'}
            </p>
          )}

          {similar.length > 0 && (
            <div className="pt-3 border-t border-slate-800">
              <div className="text-[11px] text-slate-500 mb-1.5">
                Structural neighbours — read-across candidates ({similar[0].method})
              </div>
              <div className="space-y-1.5">
                {similar.map((s) => (
                  <div key={s.generic} className="flex items-center gap-2 text-xs">
                    <span className="w-36 truncate text-slate-300" title={s.generic}>{s.generic}</span>
                    <div className="flex-1 h-2 rounded bg-slate-900 overflow-hidden">
                      <div className="h-full bg-violet-500/60" style={{ width: `${Math.round(s.tanimoto * 100)}%` }} />
                    </div>
                    <span className="w-10 text-right tabular-nums text-slate-400">{s.tanimoto}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <p className="text-[11px] text-slate-500">{data.audit?.disclaimer}</p>
        </div>
      )}
    </Card>
  );
}
