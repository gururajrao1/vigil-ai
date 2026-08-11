import { useEffect, useState } from 'react';
import { api } from '../api';
import { Badge, Card, CardHeader, Spinner } from '../components/ui';

const LEVEL_TONE = {
  SOC: 'bg-indigo-500/15 text-indigo-200 border-indigo-500/30',
  HLGT: 'bg-sky-500/15 text-sky-200 border-sky-500/30',
  HLT: 'bg-cyan-500/15 text-cyan-200 border-cyan-500/30',
  PT: 'bg-emerald-500/15 text-emerald-200 border-emerald-500/30',
  LLT: 'bg-slate-600/25 text-slate-300 border-slate-600/40',
};

function TierRow({ tier, index, total }) {
  if (!tier.name) return null;
  return (
    <div className="flex items-start gap-3" style={{ paddingLeft: `${index * 18}px` }}>
      <span className="pt-1 text-slate-700 select-none">{index === 0 ? '' : '└'}</span>
      <div className="flex-1 rounded-md border border-slate-800 bg-slate-950/50 px-3 py-2">
        <div className="flex flex-wrap items-center gap-2">
          <Badge value={tier.level} className={`${LEVEL_TONE[tier.level]} text-[10px]`} />
          <span className="text-sm text-slate-100">{tier.name}</span>
          {index === total - 1 && (
            <span className="text-[10px] uppercase tracking-wide text-slate-500">as reported</span>
          )}
        </div>
        {tier.code && (
          <div className="mt-1 font-mono text-[11px] text-slate-500">{tier.code}</div>
        )}
      </div>
    </div>
  );
}

/**
 * Interactive SOC → HLGT → HLT → PT → LLT chain for one event verbatim.
 * Pass `term` (verbatim or PT) — the component resolves the chain itself.
 */
export default function OntologyHierarchyTree({ term = '', embedded = false }) {
  const [chain, setChain] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!term) return undefined;
    let cancelled = false;
    setBusy(true);
    setErr(null);
    api.ontologyEngineMeddraChain(term)
      .then((c) => { if (!cancelled) setChain(c); })
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

  const tiers = (chain?.tiers || []).filter((t) => t.name);

  return (
    <Card className={embedded ? 'p-4' : 'p-4 border-indigo-700/40'}>
      <CardHeader
        title="MedDRA hierarchy — LLT to SOC"
        subtitle={`Where "${term}" sits in the 5-tier event terminology`}
        right={(
          <div className="flex items-center gap-2">
            {chain?.matched
              ? <Badge value={`match: ${chain.match_method}`} className="bg-emerald-500/15 text-emerald-200 border-emerald-500/30 text-[10px]" />
              : <Badge value="unmatched" className="bg-amber-500/15 text-amber-200 border-amber-500/30 text-[10px]" />}
            <Badge value="open surrogate" className="bg-slate-700/40 text-slate-300 border-slate-600/40 text-[10px]" />
          </div>
        )}
      />

      {busy && !chain && <div className="mt-3"><Spinner label="Resolving chain…" /></div>}
      {err && <p className="mt-3 text-sm text-rose-300">{err}</p>}

      {chain && (
        <div className="mt-4 space-y-2">
          {tiers.length > 0 ? (
            tiers.map((tier, i) => (
              <TierRow key={tier.level} tier={tier} index={i} total={tiers.length} />
            ))
          ) : (
            <p className="text-sm text-slate-400">
              No hierarchy row for this term. The verbatim is kept as-is rather than
              coded to a Preferred Term it does not belong to.
            </p>
          )}

          <div className="flex flex-wrap gap-3 pt-3 text-[11px] text-slate-500 border-t border-slate-800">
            {chain.cui && <span>CUI: <span className="font-mono text-slate-300">{chain.cui}</span></span>}
            {chain.snomed_ct && <span>SNOMED: <span className="font-mono text-slate-300">{chain.snomed_ct}</span></span>}
            {chain.oae && <span>OAE: <span className="font-mono text-slate-300">{chain.oae}</span></span>}
            {chain.icd11 && <span>ICD-11: <span className="font-mono text-slate-300">{chain.icd11}</span></span>}
            <span>confidence: <span className="text-slate-300">{chain.confidence}</span></span>
          </div>

          <p className="text-[11px] text-slate-500">{chain.audit?.disclaimer}</p>
        </div>
      )}
    </Card>
  );
}
