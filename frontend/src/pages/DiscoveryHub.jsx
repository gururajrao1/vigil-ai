import { HubShell } from '../components/PageTabs';
import SurrogateHonestyBanner from '../components/SurrogateHonestyBanner';
import SourceQueue from './SourceQueue';
import Onboarding from './Onboarding';

const TABS = [
  { id: 'queue', label: 'Pathfinder queue' },
  { id: 'manual', label: 'Manual forum URL' },
];

export default function DiscoveryHub() {
  return (
    <div className="space-y-4">
      <SurrogateHonestyBanner />
      <HubShell
        title="Source Discovery"
        subtitle="Structured discovery index for communities and forum URLs — comparative logic remains local-surrogate only."
        tabDefs={TABS}
        defaultTab="queue"
      >
        {(tab) => (tab === 'manual' ? <Onboarding embedded /> : <SourceQueue embedded />)}
      </HubShell>
    </div>
  );
}
