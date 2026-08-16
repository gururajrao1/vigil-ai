import { useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { Badge, Button, Card, CardHeader } from '../components/ui';
import OmniSearchBox from '../components/OmniSearchBox';
import SignalDataGrid from '../components/SignalDataGrid';
import { usePharmacovigilance } from '../context/PharmacovigilanceContext';
import Signals from '../pages/Signals';

/**
 * Phase 5 — Signals dashboard.
 * OmniSearchBox + SignalDataGrid bind to PharmacovigilanceContext (no full page reload).
 * Legacy Detect table below stays seeded from the same clinical context.
 */
export default function SignalsView({ embedded = false }) {
  const {
    activeSearchTerm,
    resolvedConcept,
    resolvedRxCUI,
    omopSignals,
    isLoading,
    executeSearch,
  } = usePharmacovigilance();

  const bootstrapped = useRef(false);

  // If context already has a term (e.g. navigated from Omni lens) but no Phase 4 rows yet
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
          title="Omni-Search · OMOP signals"
          subtitle="Brand / slang / clinical term → concept_id → PRR/ROR from omop_signal_summary. Shared context updates Detect without reload."
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
              <Badge
                value="Phase 5"
                className="bg-emerald-500/10 text-emerald-100 border-emerald-500/30 text-[10px]"
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
            onClick={() => activeSearchTerm && executeSearch(activeSearchTerm)}
          >
            Refresh scores
          </Button>
        </div>
      </Card>

      <SignalDataGrid />

      {/* Existing Detect workbench — filters seed from context search / RxCUI */}
      <Signals
        embedded={embedded}
        contextDrug={activeSearchTerm || undefined}
        contextRxcui={resolvedConcept?.rxcui || resolvedRxCUI || undefined}
      />
    </div>
  );
}
