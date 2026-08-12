import { HubShell } from '../components/PageTabs';
import MCN from './MCN';
import Ontology from './Ontology';

const TABS = [
  { id: 'mcn', label: 'MCN' },
  { id: 'ontology', label: 'Ontology' },
];

/**
 * Terminology hub — MCN + ontology playgrounds moved out of Analytic Lenses
 * so Lenses stays focused on analytic overlays. Omni-Search lives on Safety Signals → Detect.
 */
export default function Terminology() {
  return (
    <HubShell
      title="Terminology"
      subtitle="Medical concept normalization and ontology playgrounds. Brand / RxCUI search is on Safety Signals → Detect."
      tabDefs={TABS}
      defaultTab="mcn"
    >
      {(tab) => {
        if (tab === 'ontology') return <Ontology embedded />;
        return <MCN embedded />;
      }}
    </HubShell>
  );
}
