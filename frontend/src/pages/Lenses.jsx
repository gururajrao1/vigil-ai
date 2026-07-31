import { HubShell } from '../components/PageTabs';
import Smq from './Smq';
import ClassEffects from './ClassEffects';
import Vaccine from './Vaccine';
import Spatial from './Spatial';
import Divergence from './Divergence';
import Ddi from './Ddi';
import Pregnancy from './Pregnancy';
import RemineLab from './RemineLab';

const TABS = [
  { id: 'remine', label: 'Remine lab' },
  { id: 'ddi', label: 'DDI findings' },
  { id: 'pregnancy', label: 'Pregnancy' },
  { id: 'smq', label: 'SMQ syndromes' },
  { id: 'class', label: 'Class effects' },
  { id: 'vaccine', label: 'Vaccine' },
  { id: 'spatial', label: 'Geo clusters' },
  { id: 'divergence', label: 'vs FAERS' },
];

/** Analytic lenses hub. */
export default function Lenses() {
  return (
    <HubShell
      title="Analytic Lenses"
      subtitle="Remine competition bias, DDI findings, pregnancy/teratogen cohort, SMQ, class effects, vaccine AESI, geo scan, and vs FAERS."
      tabDefs={TABS}
      defaultTab="remine"
    >
      {(tab) => {
        if (tab === 'remine') return <RemineLab embedded />;
        if (tab === 'ddi') return <Ddi embedded />;
        if (tab === 'pregnancy') return <Pregnancy embedded />;
        if (tab === 'class') return <ClassEffects embedded />;
        if (tab === 'vaccine') return <Vaccine embedded />;
        if (tab === 'spatial') return <Spatial embedded />;
        if (tab === 'divergence') return <Divergence embedded />;
        return <Smq embedded />;
      }}
    </HubShell>
  );
}
