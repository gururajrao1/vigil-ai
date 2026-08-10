import { Card, CardHeader } from './ui';

const TIER_STYLE = {
  CRITICAL_URGENT: 'bg-rose-500/20 text-rose-200 border-rose-500/40',
  HIGH_EARLY_WARNING: 'bg-amber-500/15 text-amber-200 border-amber-500/35',
  EMERGENT_CHATTER: 'bg-sky-500/15 text-sky-200 border-sky-500/35',
  REGULATORY_ONLY: 'bg-violet-500/15 text-violet-200 border-violet-500/35',
  INSUFFICIENT: 'bg-slate-700/40 text-slate-400 border-slate-600/40',
};

/** Three-pillar triangulation meters (GVP Module 3). */
export default function TriangulationMatrixCard({ triangulation }) {
  if (!triangulation) {
    return (
      <Card className="p-4">
        <CardHeader title="Signal triangulation" subtitle="Social · Regulatory · RWD" />
        <p className="mt-2 text-sm text-slate-500">No triangulation payload yet.</p>
      </Card>
    );
  }

  const tier = triangulation.urgency_tier || 'INSUFFICIENT';
  const pillars = triangulation.pillars || [];
  const score = Number(triangulation.triangulated_risk_score || 0);

  return (
    <Card className="p-4">
      <CardHeader
        title="Multi-source triangulation"
        subtitle="Social / News · FAERS/MAUDE · OMOP/MIMIC surrogate"
        right={
          <span
            className={`inline-flex items-center border px-2 py-1 text-[10px] font-mono font-semibold tracking-wide ${TIER_STYLE[tier] || TIER_STYLE.INSUFFICIENT}`}
            style={{ borderRadius: 4 }}
          >
            [{triangulation.badge || tier}]
          </span>
        }
      />

      <div className="mt-3 text-xs text-slate-400">
        Triangulated risk:{' '}
        <span className="text-slate-100 font-mono">{score.toFixed(2)}</span>
        <span className="text-slate-500"> · pillars passed {triangulation.n_pillars_passed ?? '—'}/3</span>
      </div>

      <div className="mt-4 space-y-3">
        {pillars.map((p) => {
          const pct = Math.round(Math.min(1, Number(p.score || 0)) * 100);
          return (
            <div key={p.pillar}>
              <div className="flex justify-between text-[11px] mb-1">
                <span className="text-slate-300">{p.label || p.pillar}</span>
                <span className={p.passed ? 'text-emerald-300' : 'text-slate-500'}>
                  {p.passed ? 'PASS' : 'gap'} · {pct}%
                </span>
              </div>
              <div className="h-2 rounded bg-slate-900 overflow-hidden border border-slate-800">
                <div
                  className={`h-full ${p.passed ? 'bg-emerald-400/80' : 'bg-slate-600'}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>

      <p className="mt-3 text-[10px] text-slate-500">{triangulation.disclaimer}</p>
    </Card>
  );
}
