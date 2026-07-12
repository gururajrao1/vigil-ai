import { HubShell } from '../components/PageTabs';
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

/** All ingest / source surfaces in one window — Sources stay first-class. */
export default function SourcesHub() {
  return (
    <HubShell
      title="Data Sources"
      subtitle="Crawl catalog, continuous live feed, worldwide network registry, and agent-assisted ingest."
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
  );
}
