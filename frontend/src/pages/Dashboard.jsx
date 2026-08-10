import { HubShell } from '../components/PageTabs';
import ContextBanner from '../components/ContextBanner';
import Overview from './Overview';
import Kpis from './Kpis';
import InspectionReadinessPanel from '../hubs/InspectionReadinessPanel';
import COUGovernanceScorecard from '../hubs/COUGovernanceScorecard';
import BenefitRiskBalanceVisualizer from '../hubs/BenefitRiskBalanceVisualizer';

const TABS = [
  { id: 'corpus', label: 'Corpus metrics' },
  { id: 'ops', label: 'Ops KPIs & SPC' },
  { id: 'governance', label: 'Inspection & COU' },
];

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
                <InspectionReadinessPanel embedded />
                <COUGovernanceScorecard embedded />
                <BenefitRiskBalanceVisualizer
                  embedded
                  drug="semaglutide"
                  event="nausea"
                  strength="MODERATE"
                  postCount={12}
                />
              </div>
            );
          }
          return <Overview embedded />;
        }}
      </HubShell>
    </div>
  );
}
