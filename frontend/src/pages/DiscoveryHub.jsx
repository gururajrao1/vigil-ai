import { HubShell } from '../components/PageTabs';
import SourceQueue from './SourceQueue';
import Onboarding from './Onboarding';

const TABS = [
  { id: 'queue', label: 'Pathfinder queue' },
  { id: 'manual', label: 'Manual forum URL' },
];

/** Community discovery + manual URL onboarding in one window. */
export default function DiscoveryHub() {
  return (
    <HubShell
      title="Source Discovery"
      subtitle="Pathfinder-suggested communities and manual forum URL onboarding for the active project."
      tabDefs={TABS}
      defaultTab="queue"
    >
      {(tab) => (tab === 'manual' ? <Onboarding embedded /> : <SourceQueue embedded />)}
    </HubShell>
  );
}
