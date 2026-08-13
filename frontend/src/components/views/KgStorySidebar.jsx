import { Badge, Button, Card } from '../ui';

/**
 * Signal Story Mode — left-rail controller for KG narrative focus steps.
 */
const STEPS = [
  {
    id: 1,
    title: 'Isolate target drug',
    body: 'Highlight the focus product and its direct neighborhood. Background network fades to 15% so the presentation stays on one fingerprint.',
  },
  {
    id: 2,
    title: 'Baseline contrast',
    body: 'Bring comparator products that share the same adverse events into sharp focus — triangulate whether the pattern is molecule-specific or class-wide.',
  },
];

export default function KgStorySidebar({
  activeStoryStep,
  setActiveStoryStep,
  targetDrug,
  contrastDrugs = [],
  targetAes = [],
  onPickTarget,
  drugOptions = [],
}) {
  const on = activeStoryStep > 0;

  return (
    <Card className="w-full lg:w-[30%] shrink-0 p-4 space-y-4" variant="glass">
      <div>
        <h3 className="text-sm font-semibold text-[var(--cds-sys-text-primary)]">Signal Story Mode</h3>
        <p className="text-[11px] text-[var(--cds-sys-text-tertiary)] mt-1 leading-relaxed">
          Step through a clinical narrative. The canvas opacity tracks this stepper so the hairball never owns the room.
        </p>
      </div>

      <label className="block space-y-1">
        <span className="text-[10px] uppercase tracking-wide text-[var(--cds-sys-text-tertiary)]">Target drug</span>
        <select
          value={targetDrug || ''}
          onChange={(e) => onPickTarget(e.target.value)}
          className="w-full px-2.5 py-2 text-xs"
        >
          <option value="">Pick a product…</option>
          {drugOptions.map((d) => (
            <option key={d} value={d}>{d}</option>
          ))}
        </select>
      </label>

      <div className="flex items-center gap-2">
        <Button
          type="button"
          disabled={!targetDrug}
          onClick={() => setActiveStoryStep(on ? 0 : 1)}
          variant={on ? 'outline' : 'gradient'}
          size="sm"
          className="flex-1"
        >
          {on ? 'Exit story' : 'Start story'}
        </Button>
      </div>

      <ol className="space-y-2">
        {STEPS.map((s) => {
          const active = activeStoryStep === s.id;
          const done = activeStoryStep > s.id;
          return (
            <li key={s.id}>
              <Button
                type="button"
                disabled={!targetDrug}
                onClick={() => setActiveStoryStep(s.id)}
                variant={active ? 'glass' : 'ghost'}
                className="w-full justify-start text-left h-auto py-2.5"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <Badge tone={active ? 'brand' : done ? 'ok' : 'muted'} value={String(s.id)} />
                    <span className="text-xs font-medium">{s.title}</span>
                  </div>
                  {active && (
                    <p className="text-[11px] text-[var(--cds-sys-text-secondary)] mt-2 leading-relaxed pl-1">{s.body}</p>
                  )}
                </div>
              </Button>
            </li>
          );
        })}
      </ol>

      {activeStoryStep === 1 && targetDrug && (
        <div className="px-3 py-2 text-[11px] text-[var(--cds-sys-text-secondary)] space-y-1">
          <div className="font-medium text-[var(--cds-sys-accent-primary)]">Focus · {targetDrug}</div>
          <div>{targetAes.length} linked AE{targetAes.length === 1 ? '' : 's'} in neighborhood</div>
        </div>
      )}

      {activeStoryStep === 2 && (
        <div className="px-3 py-2 text-[11px] text-[var(--cds-sys-text-secondary)] space-y-1">
          <Badge tone="warn" value="Contrast set" />
          {contrastDrugs.length === 0 ? (
            <div>No comparator products share these AEs in the current graph.</div>
          ) : (
            <ul className="list-disc pl-4 space-y-0.5">
              {contrastDrugs.slice(0, 8).map((d) => (
                <li key={d}>{d}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="flex gap-2 pt-1">
        <Button
          type="button"
          disabled={activeStoryStep <= 1 || !targetDrug}
          onClick={() => setActiveStoryStep((s) => Math.max(1, s - 1))}
          variant="outline"
          size="sm"
          className="flex-1"
        >
          ← Prev
        </Button>
        <Button
          type="button"
          disabled={!targetDrug || activeStoryStep >= 2}
          onClick={() => setActiveStoryStep((s) => Math.min(2, (s || 0) + 1 || 1))}
          variant="gradient"
          size="sm"
          className="flex-1"
        >
          Next →
        </Button>
      </div>
    </Card>
  );
}

/** Build highlight id sets for canvas alpha from story step + graph. */
export function computeStoryFocus(kg, { activeStoryStep, targetDrug }) {
  const empty = { hotIds: new Set(), contrastDrugLabels: [], targetAeLabels: [] };
  if (!kg?.nodes?.length || !targetDrug || !activeStoryStep) return empty;

  const fold = (s) => (s || '').toLowerCase().trim();
  const want = fold(targetDrug);
  const drugNode = kg.nodes.find((n) => n.type === 'drug' && fold(n.label) === want);
  if (!drugNode) return empty;

  const links = kg.edges || [];
  const idOf = (x) => (typeof x === 'object' ? x.id : x);
  const neighborIds = new Set();
  const targetAeLabels = [];

  links.forEach((e) => {
    const s = idOf(e.source);
    const t = idOf(e.target);
    if (s === drugNode.id) neighborIds.add(t);
    if (t === drugNode.id) neighborIds.add(s);
  });

  kg.nodes.forEach((n) => {
    if (neighborIds.has(n.id) && n.type === 'symptom') {
      targetAeLabels.push(n.label);
    }
  });

  if (activeStoryStep === 1) {
    const hotIds = new Set([drugNode.id, ...neighborIds]);
    return { hotIds, contrastDrugLabels: [], targetAeLabels };
  }

  // Step 2: drugs that share any of the target's AE nodes
  const aeIds = new Set(
    kg.nodes.filter((n) => n.type === 'symptom' && targetAeLabels.some((a) => fold(a) === fold(n.label))).map((n) => n.id),
  );
  const contrastIds = new Set([drugNode.id, ...aeIds]);
  const contrastDrugLabels = [];

  links.forEach((e) => {
    const s = idOf(e.source);
    const t = idOf(e.target);
    const touchAe = aeIds.has(s) || aeIds.has(t);
    if (!touchAe) return;
    contrastIds.add(s);
    contrastIds.add(t);
  });

  kg.nodes.forEach((n) => {
    if (n.type === 'drug' && contrastIds.has(n.id) && n.id !== drugNode.id) {
      contrastDrugLabels.push(n.label);
    }
  });

  return { hotIds: contrastIds, contrastDrugLabels, targetAeLabels };
}
