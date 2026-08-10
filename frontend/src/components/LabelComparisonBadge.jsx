/** In-label vs novel signal badge (GVP Module 1). */
export default function LabelComparisonBadge({ labelFilter, novelty }) {
  const tag = labelFilter?.tag;
  const tier = (tag || novelty || 'UNKNOWN').toString().toUpperCase();

  let text = '[OFF-LABEL: NOVEL SIGNAL]';
  let cls = 'bg-amber-500/15 text-amber-200 border-amber-500/35';
  if (tier === 'ESTABLISHED_REACTION' || tier === 'IN_LABEL') {
    text = '[IN-LABEL: ESTABLISHED]';
    cls = 'bg-slate-600/25 text-slate-300 border-slate-600/40';
  } else if (tier === 'BOXED_COVERED' || tier === 'BOXED') {
    text = '[IN-LABEL: BOXED WARNING]';
    cls = 'bg-rose-500/15 text-rose-300 border-rose-500/35';
  } else if (tier === 'UNKNOWN') {
    text = '[LABEL: UNKNOWN]';
    cls = 'bg-slate-800 text-slate-400 border-slate-700';
  }

  const weber = labelFilter?.weber?.weber_adjusted;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span
        className={`inline-flex items-center border px-2 py-0.5 text-[10px] font-mono tracking-wide ${cls}`}
        style={{ borderRadius: 4 }}
        title={labelFilter?.label_gap?.note || labelFilter?.disclaimer || ''}
      >
        {text}
      </span>
      {weber && (
        <span
          className="inline-flex items-center border border-violet-500/30 bg-violet-500/10 px-2 py-0.5 text-[10px] font-mono text-violet-200"
          style={{ borderRadius: 4 }}
          title={(labelFilter?.weber?.reasons || []).join(', ')}
        >
          WEBER GATE↑
        </span>
      )}
    </div>
  );
}
