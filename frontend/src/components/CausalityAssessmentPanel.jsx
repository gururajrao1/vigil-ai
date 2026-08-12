import { Badge, Card, CardHeader } from './ui';

/** WHO-UMC + Naranjo checklist panel (GVP Module 2). */
export default function CausalityAssessmentPanel({ causality, whoUmc, whoFactors, severity }) {
  const who = causality?.who_umc || {
    category: whoUmc,
    factors: whoFactors || [],
    score: causality?.who_umc?.score,
  };
  const naranjo = causality?.naranjo;
  const tags = causality?.dechallenge_rechallenge;

  return (
    <Card className="p-4">
      <CardHeader
        title="Causality assessment"
        subtitle="WHO-UMC scale + Naranjo algorithm (AI-assisted draft)"
      />
      <div className="mt-3 flex flex-wrap gap-2 items-center">
        <Badge kind="causality" value={who?.category || whoUmc || 'Unassessable'} />
        {severity && <Badge kind="severity" value={severity} />}
        {naranjo && (
          <Badge
            value={`Naranjo ${naranjo.category} (${naranjo.score})`}
            className="bg-sky-500/15 text-sky-200 border-sky-500/30"
          />
        )}
      </div>

      {(who?.factors || whoFactors || []).length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {(who?.factors || whoFactors || []).map((f) => (
            <span
              key={f}
              className="text-[10px] font-mono text-slate-400 border border-slate-700 px-1.5 py-0.5"
              style={{ borderRadius: 4 }}
            >
              {f}
            </span>
          ))}
        </div>
      )}

      {tags && (
        <div className="mt-3 flex flex-wrap gap-1.5 text-[11px]">
          {tags.positive_dechallenge && (
            <span className="text-emerald-300 border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5" style={{ borderRadius: 4 }}>
              + Dechallenge
            </span>
          )}
          {tags.negative_dechallenge && (
            <span className="text-rose-300 border border-rose-500/30 bg-rose-500/10 px-2 py-0.5" style={{ borderRadius: 4 }}>
              − Dechallenge
            </span>
          )}
          {tags.positive_rechallenge && (
            <span className="text-amber-200 border border-amber-500/30 bg-amber-500/10 px-2 py-0.5" style={{ borderRadius: 4 }}>
              + Rechallenge
            </span>
          )}
          {tags.temporal_relationship && (
            <span className="text-sky-200 border border-sky-500/30 bg-sky-500/10 px-2 py-0.5" style={{ borderRadius: 4 }}>
              Temporal
            </span>
          )}
        </div>
      )}

      {naranjo?.items?.length > 0 && (
        <div className="mt-4 overflow-x-auto rounded border border-slate-800">
          <table className="min-w-full text-[11px]">
            <thead className="bg-slate-950 text-slate-500">
              <tr>
                <th className="text-left p-2">#</th>
                <th className="text-left p-2">Naranjo item</th>
                <th className="text-left p-2">Answer</th>
                <th className="text-right p-2">Pts</th>
              </tr>
            </thead>
            <tbody>
              {naranjo.items.map((it) => (
                <tr key={it.id} className="border-t border-slate-800/80 text-slate-300">
                  <td className="p-2 font-mono text-slate-500">{it.id}</td>
                  <td className="p-2">{it.question}</td>
                  <td className="p-2 capitalize">{(it.answer || '').replaceAll('_', ' ')}</td>
                  <td className="p-2 text-right tabular-nums">{it.points}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="mt-3 text-[10px] text-slate-500 leading-relaxed">
        {causality?.disclaimer
          || 'AI-assisted draft — QPPV/Medical Reviewer validation required.'}
      </p>
    </Card>
  );
}
