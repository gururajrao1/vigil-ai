import { HubShell } from '../components/PageTabs';
import SurrogateHonestyBanner from '../components/SurrogateHonestyBanner';
import Sources from './Sources';
import LiveFeed from './LiveFeed';
import Surveillance from './Surveillance';
import Command from './Command';

const TABS = [
  { id: 'catalog', label: 'Source catalog' },
  { id: 'live', label: 'Live stream' },
  { id: 'networks', label: 'Network registry' },
  { id: 'agent', label: 'Agent chat' },
];

export default function SourcesHub() {
  return (
    <div className="space-y-4">
      <SurrogateHonestyBanner />
      <HubShell
        title="Data Sources"
        subtitle="Technical ingest index — live unstructured streams vs local surrogate comparative snapshots."
        tabDefs={TABS}
        defaultTab="catalog"
      >
        {(tab) => {
          if (tab === 'live') return <LiveFeed embedded />;
          if (tab === 'networks') return <Surveillance embedded />;
          if (tab === 'agent') return <Command embedded />;
          return <Sources embedded />;
        }}
      </HubShell>
    </div>
  );
}
