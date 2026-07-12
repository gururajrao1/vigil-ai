import { HubShell } from '../components/PageTabs';
import KnowledgeGraph from './KnowledgeGraph';
import Story from './Story';
import TermGlossary from './TermGlossary';

const TABS = [
  { id: 'graph', label: 'Drug ↔ AE graph' },
  { id: 'story', label: 'Compare story' },
  { id: 'glossary', label: 'Term glossary' },
];

/**
 * Relationship evidence in one window:
 * - Graph: filter by drug → related AEs, or by AE → related drugs
 * - Story: guided A-vs-B comparison for one event
 * - Glossary: layman patient phrases → MedDRA-style Preferred Terms
 */
export default function Evidence() {
  return (
    <HubShell
      title="Evidence Explorer"
      subtitle="Select a drug to list linked adverse events, or select an AE to list linked drugs — plus guided A/B comparison and the patient-phrase glossary."
      tabDefs={TABS}
      defaultTab="graph"
    >
      {(tab) => {
        if (tab === 'story') return <Story embedded />;
        if (tab === 'glossary') return <TermGlossary embedded />;
        return <KnowledgeGraph embedded />;
      }}
    </HubShell>
  );
}
