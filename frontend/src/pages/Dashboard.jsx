import { useEffect, useState } from 'react';
import { HubShell } from '../components/PageTabs';
import ContextBanner from '../components/ContextBanner';
import Overview from './Overview';
import Kpis from './Kpis';
import InspectionReadinessPanel from '../hubs/InspectionReadinessPanel';
import COUGovernanceScorecard from '../hubs/COUGovernanceScorecard';
import BenefitRiskBalanceVisualizer from '../hubs/BenefitRiskBalanceVisualizer';
import FrontierModuleStrip from '../hubs/FrontierModuleStrip';
import { api } from '../api';

const TABS = [
  { id: 'corpus', label: 'Corpus metrics' },
  { id: 'ops', label: 'Ops KPIs & SPC' },
  { id: 'governance', label: 'Inspection & COU' },
];

function GovernanceBenefitRisk() {
  const [pair, setPair] = useState(null);

  useEffect(() => {
    api.signals()
      .then((rows) => {
        const list = Array.isArray(rows) ? rows : (rows?.signals || []);
        const ranked = [...list].sort((a, b) => {
          const sevRank = { Critical: 0, High: 1, Medium: 2, Low: 3 };
          const sa = sevRank[a.severity] ?? 9;
          const sb = sevRank[b.severity] ?? 9;
          if (sa !== sb) return sa - sb;
          return (b.prr || 0) - (a.prr || 0);
        });
        const top = ranked[0];
        if (!top) return;
        setPair({
          signalId: top.id,
          drug: top.drug,
          event: top.meddra?.pt || top.symptom,
          strength: top.strength,
          postCount: top.post_count || 0,
        });
      })
      .catch(() => setPair(null));
  }, []);

  if (!pair) {
    return (
      <BenefitRiskBalanceVisualizer
        embedded
        sampleNote="Waiting on a live signal pair from this workspace…"
      />
    );
  }

  return (
    <BenefitRiskBalanceVisualizer
      embedded
      signalId={pair.signalId}
      drug={pair.drug}
      event={pair.event}
      strength={pair.strength}
      postCount={pair.postCount}
      sampleNote={`Live pair from workspace: ${pair.drug} → ${pair.event} (n=${pair.postCount}).`}
    />
  );
}

/** All dashboard metrics in one window — including next-gen governance frontiers. */
export default function Dashboard() {
  return (
    <div className="space-y-4">
      <ContextBanner />
      <HubShell
        title="Dashboard"
        subtitle="Corpus health, signal-ops quality, inspection readiness, and FDA AI/ML COU credibility."
        tabDefs={TABS}
        defaultTab="corpus"
      >
        {(tab) => {
          if (tab === 'ops') return <Kpis embedded />;
          if (tab === 'governance') {
            return (
              <div className="space-y-4">
                <FrontierModuleStrip />
                <InspectionReadinessPanel embedded />
                <COUGovernanceScorecard embedded />
                <GovernanceBenefitRisk />
              </div>
            );
          }
          return <Overview embedded />;
        }}
      </HubShell>
    </div>
  );
}
