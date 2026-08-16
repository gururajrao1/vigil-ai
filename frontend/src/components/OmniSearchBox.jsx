import { useEffect, useId, useRef, useState } from 'react';
import { Badge, Button, Spinner } from './ui';
import { usePharmacovigilance } from '../context/PharmacovigilanceContext';

/**
 * Resolution badge — shows how Omni-Search / Phase 4 mapped the query.
 */
export function ResolutionBadge({ concept, className = '' }) {
  if (!concept) return null;
  const confidence =
    concept.confidence != null && !Number.isNaN(Number(concept.confidence))
      ? `${Math.round(Number(concept.confidence) * 100)}%`
      : null;
  const ingredients = (concept.activeIngredients || []).slice(0, 4);
  const brands = (concept.brandNames || []).slice(0, 4);

  return (
    <div
      className={`mt-3 rounded-lg border border-[var(--cds-sys-border-subtle)] bg-[var(--cds-sys-bg-elevated)]/60 px-3 py-2.5 ${className}`}
      role="status"
      aria-live="polite"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[10px] uppercase tracking-[0.12em] font-mono text-[var(--cds-sys-text-tertiary)]">
          Resolved
        </span>
        {concept.conceptName && (
          <Badge
            value={concept.conceptName}
            className="bg-emerald-500/15 text-emerald-100 border-emerald-500/30 text-[10px]"
          />
        )}
        {concept.rxcui && (
          <Badge
            value={concept.rxcui}
            className="bg-cyan-500/15 text-cyan-100 border-cyan-500/30 text-[10px] font-mono"
          />
        )}
        {concept.atcCode && (
          <Badge
            value={`ATC ${concept.atcCode}`}
            className="bg-violet-500/15 text-violet-100 border-violet-500/30 text-[10px] font-mono"
          />
        )}
        {confidence && (
          <Badge
            value={`confidence ${confidence}`}
            className="bg-amber-500/10 text-amber-100 border-amber-500/30 text-[10px]"
          />
        )}
        {concept.matchMethod && (
          <Badge
            value={concept.matchMethod}
            className="bg-slate-600/30 text-slate-200 border-slate-500/40 text-[10px]"
          />
        )}
      </div>
      {ingredients.length > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-[var(--cds-sys-text-secondary)]">
          <span className="text-[var(--cds-sys-text-tertiary)]">Generics</span>
          {ingredients.map((g) => (
            <Badge
              key={g}
              value={g}
              className="bg-emerald-500/10 text-emerald-100 border-emerald-500/25 text-[10px]"
            />
          ))}
        </div>
      )}
      {brands.length > 0 && (
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px] text-[var(--cds-sys-text-secondary)]">
          <span className="text-[var(--cds-sys-text-tertiary)]">Brands</span>
          {brands.map((b) => (
            <Badge
              key={b}
              value={b}
              className="bg-sky-500/10 text-sky-100 border-sky-500/25 text-[10px]"
            />
          ))}
        </div>
      )}
    </div>
  );
}

const EXAMPLES = ['Janumet', 'janumett', 'Ozempic', 'metformin', 'MMR', 'pacemaker'];

/**
 * Unified Omni-Search — product resolve + optional AE filter for Detect.
 * Replaces the old separate "Jump to…" / "filter by event" bars on Detect.
 */
export default function OmniSearchBox({
  placeholder = 'Drug, brand, vaccine, device, or misspelling… e.g. Janumet, MMR, catheter',
  examples = EXAMPLES,
  className = '',
  showEventFilter = true,
}) {
  const {
    activeSearchTerm,
    eventFilter,
    resolvedConcept,
    isLoading,
    searchError,
    executeSearch,
    setEventFilter,
  } = usePharmacovigilance();
  const [q, setQ] = useState(activeSearchTerm || '');
  const [ae, setAe] = useState(eventFilter || '');
  const inputId = useId();
  const aeId = useId();
  const inputRef = useRef(null);

  useEffect(() => {
    if (activeSearchTerm !== q) setQ(activeSearchTerm || '');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSearchTerm]);

  useEffect(() => {
    if (eventFilter !== ae) setAe(eventFilter || '');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eventFilter]);

  const submit = async (value = q, eventAe = ae) => {
    const term = String(value || '').trim();
    const eventVal = String(eventAe || '').trim();
    if (isLoading) return;
    setQ(term);
    setAe(eventVal);
    try {
      await executeSearch(term, { eventAe: eventVal });
    } catch {
      // Error surfaced via searchError; Detect still receives activeSearchTerm when set
    }
  };

  return (
    <div className={`w-full ${className}`}>
      <form
        className="flex flex-col gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <div className="flex flex-col gap-3 sm:flex-row sm:items-stretch">
          <div className="relative flex-1 min-w-0">
            <label htmlFor={inputId} className="sr-only">
              Product / Omni-Search query
            </label>
            <input
              ref={inputRef}
              id={inputId}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={placeholder}
              disabled={isLoading}
              autoComplete="off"
              className="w-full rounded-xl border border-[var(--cds-sys-border-subtle)] bg-[var(--cds-sys-bg-base)] px-4 py-3.5 text-base text-[var(--cds-sys-text-primary)] placeholder:text-[var(--cds-sys-text-tertiary)] shadow-sm focus:outline-none focus:ring-2 focus:ring-[var(--cds-sys-accent-primary)]/40 focus:border-[var(--cds-sys-accent-primary)]/50 disabled:opacity-60"
            />
            {isLoading && (
              <div className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2">
                <Spinner label="" size="sm" />
              </div>
            )}
          </div>
          {showEventFilter && (
            <div className="sm:w-56 shrink-0">
              <label htmlFor={aeId} className="sr-only">
                Optional adverse event filter
              </label>
              <input
                id={aeId}
                type="search"
                value={ae}
                onChange={(e) => {
                  setAe(e.target.value);
                  setEventFilter(e.target.value);
                }}
                placeholder="Optional: filter by AE…"
                disabled={isLoading}
                className="w-full h-full min-h-[3.25rem] rounded-xl border border-[var(--cds-sys-border-subtle)] bg-[var(--cds-sys-bg-base)] px-3 py-3 text-sm text-[var(--cds-sys-text-primary)] placeholder:text-[var(--cds-sys-text-tertiary)] focus:outline-none focus:ring-2 focus:ring-[var(--cds-sys-accent-primary)]/40 disabled:opacity-60"
              />
            </div>
          )}
          <Button
            type="submit"
            variant="primary"
            disabled={isLoading || (!String(q || '').trim() && !String(ae || '').trim())}
            className="sm:px-6 sm:min-w-[7.5rem]"
          >
            {isLoading ? 'Searching…' : 'Search'}
          </Button>
        </div>
      </form>

      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-[var(--cds-sys-text-tertiary)]">
        <span>Try</span>
        {examples.map((ex) => (
          <Button
            key={ex}
            type="button"
            size="sm"
            variant="outline"
            disabled={isLoading}
            onClick={() => submit(ex, ae)}
          >
            {ex}
          </Button>
        ))}
        <span className="ml-1 opacity-70">· one search updates OMOP scores and Detect below</span>
      </div>

      {searchError && (
        <p className="mt-3 text-sm text-rose-300" role="alert">
          {searchError}
        </p>
      )}

      <ResolutionBadge concept={resolvedConcept} />
    </div>
  );
}
