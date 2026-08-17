import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Badge, Button, Card, CardHeader, Spinner } from './ui';
import { usePharmacovigilance } from '../context/PharmacovigilanceContext';

const num = (v, d = 2) => {
  if (v == null || Number.isNaN(Number(v))) return '—';
  return Number(v).toFixed(d);
};

/** SDR-style highlight: PRR > 2 and 95% CI lower bound > 1. */
export function isDisproportionateHighlight(row) {
  const prr = Number(row?.prr);
  const lo =
    row?.prr_ci_low != null
      ? Number(row.prr_ci_low)
      : Array.isArray(row?.prr_ci)
        ? Number(row.prr_ci[0])
        : NaN;
  return Number.isFinite(prr) && prr > 2.0 && Number.isFinite(lo) && lo > 1.0;
}

function foldKey(s) {
  return (s || '').toLowerCase().replace(/[^a-z0-9]+/g, '');
}

function matchDetectRow(row, matches) {
  const pt = foldKey(row?.meddra_pt || row?.condition_name);
  if (!pt) return null;
  return (matches || []).find((s) => {
    const a = foldKey(s?.meddra?.pt);
    const b = foldKey(s?.symptom);
    return a === pt || b === pt || (a && pt.includes(a)) || (b && pt.includes(b));
  }) || null;
}

function rowBrandKey(row) {
  return (
    row?.product
    || row?.brand
    || row?.subset_product
    || row?.drug
    || ''
  ).toString().toLowerCase();
}

/**
 * Disproportionality data grid — PRR / ROR / EB05 with Universe vs Subset brand filters.
 */
export default function SignalDataGrid({
  className = '',
  onSelectBrand,
}) {
  const {
    activeSearchTerm,
    resolvedConcept,
    signalData,
    comparisonBrands,
    omopSignals,
    detectMatches,
    isLoading,
    executeSearch,
  } = usePharmacovigilance();
  const nav = useNavigate();

  const [viewMode, setViewMode] = useState('universe'); // universe | subset
  const [enabledBrands, setEnabledBrands] = useState(() => new Set());

  const brandOptions = useMemo(() => {
    const fromConcept = resolvedConcept?.brandNames || [];
    const fromCtx = comparisonBrands || [];
    const fromPayload = omopSignals?.comparison_brands || [];
    return [...new Set([...fromConcept, ...fromCtx, ...fromPayload].filter(Boolean))];
  }, [resolvedConcept, comparisonBrands, omopSignals]);

  const filteredRows = useMemo(() => {
    const rows = Array.isArray(signalData) ? signalData : [];
    if (viewMode !== 'subset' || enabledBrands.size === 0) return rows;
    const selected = [...enabledBrands].map((b) => b.toLowerCase());
    const hasBrandColumn = rows.some((r) => rowBrandKey(r));
    if (!hasBrandColumn) {
      // Ingredient-level universe table — subset toggles do not hide rows
      return rows;
    }
    return rows.filter((r) => {
      const key = rowBrandKey(r);
      return selected.some((b) => key === b || key.includes(b) || b.includes(key));
    });
  }, [signalData, viewMode, enabledBrands]);

  const subsetLacksBrandColumn = useMemo(() => {
    const rows = Array.isArray(signalData) ? signalData : [];
    return (
      viewMode === 'subset'
      && enabledBrands.size > 0
      && rows.length > 0
      && !rows.some((r) => rowBrandKey(r))
    );
  }, [signalData, viewMode, enabledBrands]);

  const toggleBrand = (brand) => {
    setEnabledBrands((prev) => {
      const next = new Set(prev);
      if (next.has(brand)) next.delete(brand);
      else next.add(brand);
      return next;
    });
    setViewMode('subset');
  };

  const runBrandSearch = async (brand) => {
    onSelectBrand?.(brand);
    try {
      await executeSearch(brand);
    } catch {
      /* searchError in context */
    }
  };

  if (isLoading && (!signalData || signalData.length === 0) && !omopSignals) {
    return <Spinner label="Loading disproportionality scores…" />;
  }

  if (!omopSignals && (!signalData || signalData.length === 0)) {
    return (
      <Card className={`p-4 ${className}`}>
        <CardHeader
          title="Disproportionality grid"
          subtitle="Run Omni-Search above to load PRR / ROR / EB05 for the resolved drug."
        />
        <p className="mt-3 text-sm text-[var(--cds-sys-text-secondary)] px-4 pb-4">
          No signal rows yet. Try <span className="font-mono text-[var(--cds-sys-text-primary)]">Janumet</span> after
          FAERS / OMOP staging is populated.
        </p>
      </Card>
    );
  }

  const drugLabel =
    resolvedConcept?.conceptName
    || omopSignals?.drug_name
    || activeSearchTerm
    || 'drug';

  return (
    <Card className={`p-0 overflow-hidden ${className}`}>
      <div className="px-4 pt-4">
        <CardHeader
          title={`Safety signals · ${drugLabel}`}
          subtitle={`${omopSignals?.n_exposures ?? filteredRows.length} exposures · source=${omopSignals?.source || 'omop'} · CDM v5.4`}
          right={
            <div className="flex flex-wrap gap-1.5">
              <Button
                type="button"
                size="sm"
                variant={viewMode === 'universe' ? 'primary' : 'outline'}
                onClick={() => setViewMode('universe')}
              >
                Universe
              </Button>
              <Button
                type="button"
                size="sm"
                variant={viewMode === 'subset' ? 'primary' : 'outline'}
                onClick={() => setViewMode('subset')}
                disabled={brandOptions.length === 0}
              >
                Subset
              </Button>
            </div>
          }
        />
      </div>

      <div className="px-4 mt-2 text-[11px] text-[var(--cds-sys-text-secondary)] space-y-1">
        <p>
          Evans 2001 / EMA GVP IX: an SDR row (red) is a <em>signal of disproportionate reporting</em> —
          PRR &gt; 2 and 95% CI lower bound &gt; 1, not a confirmed ADR. Use it to open a case series in Detect.
        </p>
        <p>
          <strong className="text-[var(--cds-sys-text-primary)]">Universe</strong> = ingredient 2×2 vs the rest of the
          corpus. <strong className="text-[var(--cds-sys-text-primary)]">Subset</strong> = brand vs peer brands of the
          same chemical (Hauben: is it the molecule or this product?). Click a PT to jump to the Detect pair.
        </p>
      </div>

      {(omopSignals?.notes || []).length > 0 && (
        <div className="px-4 mt-2 space-y-1">
          {omopSignals.notes.map((n) => (
            <p key={n} className="text-[11px] text-amber-200/85">{n}</p>
          ))}
        </div>
      )}

      {/* Universe vs Subset brand toggles */}
      <div className="px-4 mt-3 mb-2">
        <div className="text-[10px] uppercase tracking-[0.1em] font-mono text-[var(--cds-sys-text-tertiary)] mb-1.5">
          {viewMode === 'universe'
            ? 'Universe — chemical / ingredient baseline'
            : 'Subset — competing brands sharing the active ingredient'}
        </div>
        {brandOptions.length === 0 ? (
          <p className="text-xs text-[var(--cds-sys-text-secondary)]">
            No peer brands in context yet. Resolve a combo brand (e.g. Janumet) to enable subset filters.
          </p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {brandOptions.map((brand) => {
              const on = enabledBrands.has(brand);
              return (
                <label
                  key={brand}
                  className={`inline-flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs cursor-pointer transition-colors ${
                    on
                      ? 'border-sky-500/40 bg-sky-500/10 text-sky-100'
                      : 'border-[var(--cds-sys-border-subtle)] bg-[var(--cds-sys-bg-base)] text-[var(--cds-sys-text-secondary)]'
                  }`}
                >
                  <input
                    type="checkbox"
                    className="rounded border-slate-600"
                    checked={on}
                    onChange={() => toggleBrand(brand)}
                  />
                  <span>{brand}</span>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    className="!px-1 !py-0 text-[10px] opacity-70"
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      runBrandSearch(brand);
                    }}
                  >
                    Search
                  </Button>
                </label>
              );
            })}
          </div>
        )}
        {subsetLacksBrandColumn && (
          <p className="mt-2 text-[11px] text-[var(--cds-sys-text-tertiary)]">
            PRR rows are ingredient-level (universe). Use brand <span className="font-mono">Search</span> to
            re-resolve a competing product, or keep toggles as a comparison checklist.
          </p>
        )}
      </div>

      {filteredRows.length === 0 ? (
        <p className="px-4 pb-4 text-sm text-[var(--cds-sys-text-secondary)]">
          No adverse-event rows for the current filter. Clear subset toggles or sync OMOP staging.
        </p>
      ) : (
        <div className="mt-1 overflow-x-auto border-t border-[var(--cds-sys-border-subtle)]">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-[var(--cds-sys-text-tertiary)] bg-[var(--cds-sys-bg-elevated)]/40">
                <th className="py-2.5 px-4 font-medium">Condition / MedDRA PT</th>
                <th className="py-2.5 px-3 text-right font-medium">N</th>
                <th className="py-2.5 px-3 text-right font-medium">PRR</th>
                <th className="py-2.5 px-3 text-right font-medium">PRR 95% CI</th>
                <th className="py-2.5 px-3 text-right font-medium">ROR</th>
                <th className="py-2.5 px-3 text-right font-medium">EB05</th>
                <th className="py-2.5 px-3 text-right font-medium">χ²</th>
                <th className="py-2.5 px-4 font-medium">Tier</th>
                <th className="py-2.5 px-4 font-medium">Review</th>
              </tr>
            </thead>
            <tbody>
              {filteredRows.map((r, idx) => {
                const hot = isDisproportionateHighlight(r);
                const key = `${r.condition_concept_id || r.condition_name}-${r.n_occurrences}-${idx}`;
                const ciLo = r.prr_ci_low ?? r.prr_ci?.[0];
                const ciHi = r.prr_ci_high ?? r.prr_ci?.[1];
                const hit = matchDetectRow(r, detectMatches);
                const pt = r.meddra_pt || r.condition_name || '';
                const openPair = () => {
                  if (hit?.id) {
                    nav(`/signals/${hit.id}`);
                    return;
                  }
                  const qs = new URLSearchParams();
                  if (drugLabel && drugLabel !== 'drug') qs.set('drug', drugLabel);
                  if (pt) qs.set('symptom', pt);
                  nav(`/signals?${qs.toString()}`);
                };
                return (
                  <tr
                    key={key}
                    onClick={openPair}
                    onKeyDown={(e) => { if (e.key === 'Enter') openPair(); }}
                    tabIndex={0}
                    role="link"
                    className={`border-t border-[var(--cds-sys-border-subtle)] transition-colors cursor-pointer ${
                      hot
                        ? 'bg-rose-500/15 text-rose-50 ring-1 ring-inset ring-rose-500/25'
                        : 'hover:bg-[var(--cds-sys-bg-elevated)]/30'
                    }`}
                  >
                    <td className="py-2 px-4 text-[var(--cds-sys-text-primary)]">
                      {pt || '—'}
                      {hot && (
                        <span className="ml-2 text-[10px] font-mono uppercase tracking-wide text-rose-200">
                          SDR
                        </span>
                      )}
                    </td>
                    <td className="py-2 px-3 text-right tabular-nums text-[var(--cds-sys-text-secondary)]">
                      {r.n_persons ?? r.n_occurrences ?? r.exposure_count ?? '—'}
                    </td>
                    <td className={`py-2 px-3 text-right tabular-nums font-medium ${hot ? 'text-rose-100' : 'text-[var(--cds-sys-text-primary)]'}`}>
                      {num(r.prr)}
                    </td>
                    <td className="py-2 px-3 text-right tabular-nums text-[var(--cds-sys-text-secondary)] font-mono text-[10px]">
                      {ciLo != null || ciHi != null
                        ? `${num(ciLo)}–${num(ciHi)}`
                        : '—'}
                    </td>
                    <td className="py-2 px-3 text-right tabular-nums text-[var(--cds-sys-text-secondary)]">
                      {num(r.ror)}
                    </td>
                    <td className="py-2 px-3 text-right tabular-nums text-[var(--cds-sys-text-secondary)]">
                      {num(r.eb05)}
                    </td>
                    <td className="py-2 px-3 text-right tabular-nums text-[var(--cds-sys-text-tertiary)]">
                      {num(r.chi_square)}
                    </td>
                    <td className="py-2 px-4">
                      <Badge
                        kind="strength"
                        value={r.strength || '—'}
                        className="text-[10px]"
                      />
                    </td>
                    <td className="py-2 px-4">
                      {hit ? (
                        <span className="flex flex-wrap gap-1">
                          <Badge
                            value={hit.label_novelty === 'novel' ? 'novel vs label' : (hit.label_novelty || 'in Detect')}
                            className={
                              hit.label_novelty === 'novel'
                                ? 'bg-amber-500/15 text-amber-100 border-amber-500/30 text-[10px]'
                                : 'bg-slate-600/25 text-slate-200 border-slate-500/40 text-[10px]'
                            }
                          />
                        </span>
                      ) : (
                        <span className="text-[10px] text-[var(--cds-sys-text-tertiary)]">Open Detect</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="px-4 py-3 text-[10px] text-[var(--cds-sys-text-tertiary)] border-t border-[var(--cds-sys-border-subtle)]">
        Red rows: PRR &gt; 2.0 and PRR 95% CI lower bound &gt; 1.0 (Evans-style SDR cue). Click a PT to open the
        matching Detect pair (label novelty when SIDER/label overlay exists). Next:{' '}
        <Link to="/terminology?tab=ontology" className="text-[var(--cds-sys-accent-primary)] hover:underline">
          Ontology SOC roll-up
        </Link>
        {' '}if no single PT is strong but the organ class is (Hauben/Trontell signal strengthening).
      </p>
    </Card>
  );
}
