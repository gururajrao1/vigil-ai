import { Link } from 'react-router-dom';
import { Badge, Button, Card, CardHeader } from '../components/ui';

const WORRY_STYLE = {
  red: 'bg-rose-500/15 text-rose-300 border-rose-500/30',
  amber: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  green: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
};

/**
 * Plain-English briefing for non-technical stakeholders.
 * Analyst DMA / remine / evidence stay below on the page.
 */
export default function SignalBriefing({ briefing, onAction }) {
  if (!briefing) return null;
  const worry = briefing.worry || {};
  const why = briefing.why || [];
  const glossary = briefing.glossary || [];
  const steps = briefing.next_steps || [];

  return (
    <Card className="p-4 border-sky-600/30 bg-slate-900/40">
      <CardHeader
        title="What’s going on (plain English)"
        subtitle="For reviewers and stakeholders — technical stats are below"
        right={
          <Badge
            value={worry.label || '—'}
            className={WORRY_STYLE[worry.level] || WORRY_STYLE.amber}
          />
        }
      />

      <p className="mt-3 text-base text-slate-100 leading-relaxed">
        {briefing.headline || briefing.narrative_plain}
      </p>
      {worry.phrase && (
        <p className="mt-1.5 text-sm text-slate-300">{worry.phrase}</p>
      )}
      {briefing.prr_plain && (
        <p className="mt-2 text-sm text-sky-200/90">
          <span className="text-slate-500">In numbers: </span>
          {briefing.prr_plain}
        </p>
      )}

      {why.length > 0 && (
        <div className="mt-4">
          <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1.5">
            Why we think that
          </div>
          <ul className="space-y-1.5 text-sm text-slate-300 list-disc list-inside">
            {why.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        </div>
      )}

      {glossary.length > 0 && (
        <div className="mt-4">
          <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1.5">
            What the jargon means
          </div>
          <div className="flex flex-wrap gap-2">
            {glossary.map((g) => (
              <span
                key={g.term}
                title={g.plain}
                className="rounded-md border border-slate-700 bg-slate-950/50 px-2 py-1 text-[11px] text-slate-300 max-w-xs"
              >
                <span className="font-medium text-slate-100">{g.term}</span>
                <span className="text-slate-500"> — </span>
                {g.plain}
              </span>
            ))}
          </div>
        </div>
      )}

      {steps.length > 0 && (
        <div className="mt-4">
          <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-2">
            What you can do next
          </div>
          <div className="flex flex-wrap gap-2">
            {steps.map((s) => {
              if (s.href || s.action === 'open_risk_populations') {
                const href = s.href || '/lenses?tab=risk';
                return (
                  <Link key={s.id} to={href}>
                    <Button variant="secondary" className="text-xs">{s.label}</Button>
                  </Link>
                );
              }
              return (
                <Button
                  key={s.id}
                  variant="secondary"
                  className="text-xs"
                  onClick={() => onAction?.(s.action)}
                >
                  {s.label}
                </Button>
              );
            })}
          </div>
        </div>
      )}

      {briefing.disclaimer && (
        <p className="mt-4 text-[10px] text-slate-500 leading-relaxed">{briefing.disclaimer}</p>
      )}
    </Card>
  );
}
