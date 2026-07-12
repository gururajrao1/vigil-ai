import { HubShell } from '../components/PageTabs';
import ContextBanner from '../components/ContextBanner';
import Overview from './Overview';
import Kpis from './Kpis';

const TABS = [
  { id: 'corpus', label: 'Corpus metrics' },
  { id: 'ops', label: 'Ops KPIs & SPC' },
];

/** All dashboard metrics in one window. */
export default function Dashboard() {
  return (
    <div className="space-y-4">
      <ContextBanner />
      <HubShell
        title="Dashboard"
        subtitle="Corpus health and signal-operations quality — one place for every metric."
        tabDefs={TABS}
        defaultTab="corpus"
      >
        {(tab) => (tab === 'ops' ? <Kpis embedded /> : <Overview embedded />)}
      </HubShell>
    </div>
  );
}
