import { useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { Badge, Button, Card, CardHeader } from '../components/ui';
import OmniSearchBox from '../components/OmniSearchBox';
import SignalDataGrid from '../components/SignalDataGrid';
import { usePharmacovigilance } from '../context/PharmacovigilanceContext';
import Signals from '../pages/Signals';

/**
 * Phase 5 — Signals dashboard with a single Omni-Search.
 * Product resolve + optional AE filter drive both the PRR grid and Detect table
 * (no duplicate "Jump to…" bar below).
 */
export default function SignalsView({ embedded = false }) {
  const {
    activeSearchTerm,
    eventFilter,
    resolvedConcept,
    resolvedRxCUI,
    omopSignals,
    isLoading,
    executeSearch,
  } = usePharmacovigilance();

  const bootstrapped = useRef(false);

  useEffect(() => {
    if (bootstrapped.current) return;
    if (activeSearchTerm && !omopSignals && !isLoading) {
      bootstrapped.current = true;
      executeSearch(activeSearchTerm).catch(() => {});
    }
  }, [activeSearchTerm, omopSignals, isLoading, executeSearch]);

  return (
    <div className="space-y-5">
      <Card className="p-4 border-[var(--cds-sys-border-subtle)]">
        <CardHeader
          title="Omni-Search"
          subtitle="One search for Detect: resolve brand / vaccine / device → OMOP PRR/ROR, and filter the corpus table below. Optional AE narrows events."
          right={
            <div className="flex flex-wrap gap-1.5 justify-end">
              {(resolvedConcept?.rxcui || resolvedRxCUI) && (
                <Badge
                  value={resolvedConcept?.rxcui || resolvedRxCUI}
                  className="bg-cyan-500/15 text-cyan-100 border-cyan-500/30 text-[10px] font-mono"
                />
              )}
              {omopSignals?.source && (
                <Badge
                  value={omopSignals.source}
                  className="bg-slate-600/30 text-slate-200 border-slate-500/40 text-[10px]"
                />
              )}
              <Badge
                value="CDM v5.4"
                className="bg-violet-500/15 text-violet-100 border-violet-500/30 text-[10px]"
              />
            </div>
          }
        />
        <div className="mt-4">
          <OmniSearchBox />
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-[var(--cds-sys-text-tertiary)]">
          <Link
            to="/lenses?tab=omni"
            className="text-[var(--cds-sys-accent-primary)] hover:underline"
          >
            Full brand→chemical Omni lens
          </Link>
          <span aria-hidden>·</span>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={isLoading || !activeSearchTerm}
            onClick={() => activeSearchTerm && executeSearch(activeSearchTerm, { eventAe: eventFilter })}
          >
            Refresh scores
          </Button>
        </div>
      </Card>

      <SignalDataGrid />

      <Signals
        embedded={embedded}
        hideProductSearch
        contextDrug={activeSearchTerm || undefined}
        contextRxcui={resolvedConcept?.rxcui || resolvedRxCUI || undefined}
        contextSymptom={eventFilter || undefined}
      />
    </div>
  );
}
