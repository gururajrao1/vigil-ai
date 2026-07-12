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
    <aside className="w-full lg:w-[30%] shrink-0 rounded-xl border border-slate-700/60 bg-slate-950/80 p-4 space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-slate-100">Signal Story Mode</h3>
        <p className="text-[11px] text-slate-500 mt-1 leading-relaxed">
          Step through a clinical narrative. The canvas opacity tracks this stepper so the hairball never owns the room.
        </p>
      </div>

      <label className="block space-y-1">
        <span className="text-[10px] uppercase tracking-wide text-slate-500">Target drug</span>
        <select
          value={targetDrug || ''}
          onChange={(e) => onPickTarget(e.target.value)}
          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-2 text-xs text-slate-200"
        >
          <option value="">Pick a product…</option>
          {drugOptions.map((d) => (
            <option key={d} value={d}>{d}</option>
          ))}
        </select>
      </label>

      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled={!targetDrug}
          onClick={() => setActiveStoryStep(on ? 0 : 1)}
          className={`flex-1 rounded-lg px-3 py-2 text-xs font-medium border transition disabled:opacity-40 ${
            on
              ? 'bg-teal-500/20 text-teal-200 border-teal-500/40'
              : 'bg-slate-800 text-slate-300 border-slate-700 hover:bg-slate-700'
          }`}
        >
          {on ? 'Exit story' : 'Start story'}
        </button>
      </div>

      <ol className="space-y-2">
        {STEPS.map((s) => {
          const active = activeStoryStep === s.id;
          const done = activeStoryStep > s.id;
          return (
            <li key={s.id}>
              <button
                type="button"
                disabled={!targetDrug}
                onClick={() => setActiveStoryStep(s.id)}
                className={`w-full text-left rounded-lg border px-3 py-2.5 transition disabled:opacity-40 ${
                  active
                    ? 'border-teal-500/50 bg-teal-500/10'
                    : done
                      ? 'border-slate-700/80 bg-slate-900/40'
                      : 'border-slate-800 bg-slate-900/20 hover:border-slate-600'
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className={`flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold ${
                    active ? 'bg-teal-500 text-slate-950' : 'bg-slate-800 text-slate-400'
                  }`}
                  >
                    {s.id}
                  </span>
                  <span className={`text-xs font-medium ${active ? 'text-teal-100' : 'text-slate-300'}`}>
                    {s.title}
                  </span>
                </div>
                {active && (
                  <p className="text-[11px] text-slate-400 mt-2 leading-relaxed pl-7">{s.body}</p>
                )}
              </button>
            </li>
          );
        })}
      </ol>

      {activeStoryStep === 1 && targetDrug && (
        <div className="rounded-lg border border-sky-500/25 bg-sky-500/5 px-3 py-2 text-[11px] text-slate-400 space-y-1">
          <div className="text-sky-300 font-medium">Focus · {targetDrug}</div>
          <div>{targetAes.length} linked AE{targetAes.length === 1 ? '' : 's'} in neighborhood</div>
        </div>
      )}

      {activeStoryStep === 2 && (
        <div className="rounded-lg border border-amber-500/25 bg-amber-500/5 px-3 py-2 text-[11px] text-slate-400 space-y-1">
          <div className="text-amber-300 font-medium">Contrast set</div>
          {contrastDrugs.length === 0 ? (
            <div>No comparator products share these AEs in the current graph.</div>
          ) : (
            <ul className="list-disc pl-4 space-y-0.5">
              {contrastDrugs.slice(0, 8).map((d) => (
                <li key={d} className="text-slate-300">{d}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="flex gap-2 pt-1">
        <button
          type="button"
          disabled={activeStoryStep <= 1 || !targetDrug}
          onClick={() => setActiveStoryStep((s) => Math.max(1, s - 1))}
          className="flex-1 rounded-lg border border-slate-700 px-2 py-1.5 text-xs text-slate-400 disabled:opacity-30 hover:bg-slate-800"
        >
          ← Prev
        </button>
        <button
          type="button"
          disabled={!targetDrug || activeStoryStep >= 2}
          onClick={() => setActiveStoryStep((s) => Math.min(2, (s || 0) + 1 || 1))}
          className="flex-1 rounded-lg border border-teal-700/50 bg-teal-500/10 px-2 py-1.5 text-xs text-teal-200 disabled:opacity-30 hover:bg-teal-500/20"
        >
          Next →
        </button>
      </div>
    </aside>
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
