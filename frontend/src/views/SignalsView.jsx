import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { Badge, Card, CardHeader, Spinner } from '../components/ui';
import OmniSearchGateway from '../modules/search/OmniSearchGateway';
import { usePharmacovigilance } from '../context/PharmacovigilanceContext';
import Signals from '../pages/Signals';

/**
 * Module 3 — OMOP-driven Signals view.
 * Omni-Search at top updates PharmacovigilanceContext; PRR/ROR table binds to context.
 */
export default function SignalsView({ embedded = false }) {
  const {
    activeSearchTerm,
    resolvedRxCUI,
    comparisonBrands,
    omopSignals,
    setFromOmniSearch,
  } = usePharmacovigilance();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const runOmni = async (term) => {
    const q = (term || '').trim();
    if (!q) return;
    setBusy(true);
    setErr(null);
    try {
      const omni = await api.searchOmni(q, { includeAnalytics: true });
      const resolution = omni?.resolution;
      const rxcui =
        resolution?.ingredients?.[0]?.rxcui
        || resolution?.brand_rxcui
        || null;
      const brands = resolution?.subset_brands || [];
      let omop = null;
      const lookup = rxcui || q;
      try {
        omop = await api.omopSignalsByRxcui(lookup);
      } catch (e) {
        // Still update context from Omni even if OMOP endpoint is waking up
        omop = null;
        if (!/404/.test(e.message || '')) {
          setErr(e.message || String(e));
        }
      }
      const meddraPt =
        omop?.adverse_events?.[0]?.meddra_pt
        || omni?.extracted?.find((s) => s.kind === 'event')?.normalized_hint
        || null;
      setFromOmniSearch({
        term: q,
        rxcui: omop?.resolved_rxcui || rxcui,
        meddraPt,
        brands: omop?.comparison_brands?.length ? omop.comparison_brands : brands,
        omop,
      });
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setBusy(false);
    }
  };

  // If context already has a term (e.g. navigated from Omni lens), keep table in sync
  useEffect(() => {
    if (activeSearchTerm && !omopSignals && !busy) {
      runOmni(activeSearchTerm);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const rows = omopSignals?.adverse_events || [];

  return (
    <div className="space-y-5">
      <Card className="p-4 border-cyan-700/30">
        <CardHeader
          title="OMOP-linked Omni-Search"
          subtitle="Brand / RxCUI → CONCEPT → drug_exposure × condition_occurrence → PRR/ROR. Updates all analytics via shared clinical context."
          right={
            <div className="flex flex-wrap gap-1.5">
              {resolvedRxCUI && (
                <Badge value={resolvedRxCUI} className="bg-cyan-500/15 text-cyan-200 border-cyan-500/30 text-[10px]" />
              )}
              {omopSignals?.source && (
                <Badge
                  value={omopSignals.source}
                  className="bg-slate-700/40 text-slate-300 border-slate-600/40 text-[10px]"
                />
              )}
              <Badge value="CDM v5.4" className="bg-violet-500/15 text-violet-200 border-violet-500/30 text-[10px]" />
            </div>
          }
        />
        <div className="mt-3">
          <OmniSearchGateway
            onResolved={runOmni}
            initialQuery={activeSearchTerm || ''}
            busy={busy}
          />
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5 text-[11px] text-slate-500">
          <span>Try:</span>
          {['Janumet', 'Ozempic', 'Coumadin', 'metformin', 'RXNORM:VIG-6809'].map((ex) => (
            <button
              key={ex}
              type="button"
              className="rounded border border-slate-700 px-1.5 py-0.5 text-slate-300 hover:border-slate-500"
              onClick={() => runOmni(ex)}
            >
              {ex}
            </button>
          ))}
          <Link to="/signals" className="ml-auto text-cyan-400 hover:text-cyan-300">
            Open Detect with this search →
          </Link>
        </div>
        {err && <p className="mt-3 text-sm text-rose-300">{err}</p>}
        {(comparisonBrands || []).length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            <span className="text-[11px] text-slate-500 self-center">Comparison brands</span>
            {comparisonBrands.map((b) => (
              <Badge key={b} value={b} className="bg-amber-500/10 text-amber-100 border-amber-500/30 text-[10px]" />
            ))}
          </div>
        )}
      </Card>

      {busy && !omopSignals && <Spinner label="Resolving RxCUI + OMOP AEs…" />}

      {omopSignals && (
        <Card className="p-4">
          <CardHeader
            title={`OMOP adverse events · ${omopSignals.drug_name || activeSearchTerm || 'drug'}`}
            subtitle={`${omopSignals.n_exposures || 0} exposures · ${omopSignals.n_persons || 0} persons · source=${omopSignals.source}`}
          />
          {(omopSignals.notes || []).map((n) => (
            <p key={n} className="mt-2 text-[11px] text-amber-200/80">{n}</p>
          ))}
          {rows.length === 0 ? (
            <p className="mt-3 text-sm text-slate-400">
              No AE rows yet. Load the PV demo pack, then{' '}
              <button
                type="button"
                className="text-cyan-400 hover:text-cyan-300"
                onClick={() => api.omopSync({ limit: 300 }).then(() => runOmni(activeSearchTerm || 'Janumet'))}
              >
                sync OMOP staging
              </button>
              .
            </p>
          ) : (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-slate-500">
                  <tr className="text-left">
                    <th className="py-1.5 pr-3">Condition / MedDRA PT</th>
                    <th className="py-1.5 pr-3 text-right">N</th>
                    <th className="py-1.5 pr-3 text-right">PRR</th>
                    <th className="py-1.5 pr-3 text-right">ROR</th>
                    <th className="py-1.5 pr-3 text-right">χ²</th>
                    <th className="py-1.5 pr-3 text-right">EB05</th>
                    <th className="py-1.5 pr-3 text-right">IC025</th>
                    <th className="py-1.5 pr-3">Tier</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={`${r.condition_name}-${r.n_occurrences}`} className="border-t border-slate-800/70">
                      <td className="py-1.5 pr-3 text-slate-200">{r.meddra_pt || r.condition_name}</td>
                      <td className="py-1.5 pr-3 text-right tabular-nums text-slate-300">{r.n_occurrences}</td>
                      <td className="py-1.5 pr-3 text-right tabular-nums text-slate-300">{r.prr?.toFixed?.(2) ?? r.prr ?? '—'}</td>
                      <td className="py-1.5 pr-3 text-right tabular-nums text-slate-300">{r.ror?.toFixed?.(2) ?? r.ror ?? '—'}</td>
                      <td className="py-1.5 pr-3 text-right tabular-nums text-slate-400">{r.chi_square?.toFixed?.(2) ?? '—'}</td>
                      <td className="py-1.5 pr-3 text-right tabular-nums text-slate-400">{r.eb05?.toFixed?.(2) ?? '—'}</td>
                      <td className="py-1.5 pr-3 text-right tabular-nums text-slate-400">{r.ic025?.toFixed?.(2) ?? '—'}</td>
                      <td className="py-1.5 pr-3">
                        <Badge
                          value={r.strength || '—'}
                          className={
                            r.strength === 'STRONG'
                              ? 'bg-rose-500/15 text-rose-200 border-rose-500/30 text-[10px]'
                              : r.strength === 'MODERATE'
                                ? 'bg-amber-500/15 text-amber-200 border-amber-500/30 text-[10px]'
                                : 'bg-slate-600/25 text-slate-300 border-slate-600/40 text-[10px]'
                          }
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      {/* Existing Detect table — filters seed from context RxCUI / search term */}
      <Signals
        embedded={embedded}
        contextDrug={activeSearchTerm || undefined}
        contextRxcui={resolvedRxCUI || undefined}
      />
    </div>
  );
}
