import { HubShell } from '../components/PageTabs';
import Smq from './Smq';
import ClassEffects from './ClassEffects';
import Vaccine from './Vaccine';
import Spatial from './Spatial';
import Divergence from './Divergence';
import Ddi from './Ddi';
import Pregnancy from './Pregnancy';

const TABS = [
  { id: 'smq', label: 'SMQ syndromes' },
  { id: 'class', label: 'Class effects' },
  { id: 'ddi', label: 'DDI pairs' },
  { id: 'pregnancy', label: 'Pregnancy' },
  { id: 'vaccine', label: 'Vaccine' },
  { id: 'spatial', label: 'Geo clusters' },
  { id: 'divergence', label: 'vs FAERS' },
];

/** Analytic lenses that used to be five separate nav items. */
export default function Lenses() {
  return (
    <HubShell
      title="Analytic Lenses"
      subtitle="Syndrome pooling, ATC class effects, DDI co-mentions, pregnancy cohort, vaccine AESI, geographic scan, and social↔FAERS divergence."
      tabDefs={TABS}
      defaultTab="smq"
    >
      {(tab) => {
        if (tab === 'class') return <ClassEffects embedded />;
        if (tab === 'ddi') return <Ddi embedded />;
        if (tab === 'pregnancy') return <Pregnancy embedded />;
        if (tab === 'vaccine') return <Vaccine embedded />;
        if (tab === 'spatial') return <Spatial embedded />;
        if (tab === 'divergence') return <Divergence embedded />;
        return <Smq embedded />;
      }}
    </HubShell>
  );
}
