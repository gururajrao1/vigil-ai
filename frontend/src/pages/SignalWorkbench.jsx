import { HubShell } from '../components/PageTabs';
import SignalsView from '../views/SignalsView';
import SignalLifecycle from './SignalLifecycle';
import Alerts from './Alerts';
import SignalTrackingRegister from './SignalTrackingRegister';

const TABS = [
  { id: 'detect', label: 'Detect' },
  { id: 'register', label: 'Register' },
  { id: 'lifecycle', label: 'Workflow' },
  { id: 'alerts', label: 'Alert inbox' },
];

/** Signal detection, GVP register, workflow board, and alert inbox. */
export default function SignalWorkbench() {
  return (
    <HubShell
      title="Safety Signals"
      subtitle="OMOP Omni-Search · Find pairs · GVP register · Workflow · Alert inbox."
      tabDefs={TABS}
      defaultTab="detect"
    >
      {(tab) => {
        if (tab === 'register') return <SignalTrackingRegister embedded />;
        if (tab === 'lifecycle') return <SignalLifecycle embedded />;
        if (tab === 'alerts') return <Alerts embedded />;
        return <SignalsView embedded />;
      }}
    </HubShell>
  );
}
