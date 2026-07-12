import { HubShell } from '../components/PageTabs';
import Signals from './Signals';
import SignalLifecycle from './SignalLifecycle';
import Alerts from './Alerts';

const TABS = [
  { id: 'detect', label: 'Detect' },
  { id: 'lifecycle', label: 'Workflow' },
  { id: 'alerts', label: 'Alert inbox' },
];

/** Signal detection, workflow board, and alert inbox in one window. */
export default function SignalWorkbench() {
  return (
    <HubShell
      title="Safety Signals"
      subtitle="Find pairs · move them through Workflow · clear urgent pings in Alert inbox."
      tabDefs={TABS}
      defaultTab="detect"
    >
      {(tab) => {
        if (tab === 'lifecycle') return <SignalLifecycle embedded />;
        if (tab === 'alerts') return <Alerts embedded />;
        return <Signals embedded />;
      }}
    </HubShell>
  );
}
