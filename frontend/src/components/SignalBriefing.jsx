import { Link } from 'react-router-dom';
import { Badge, Button, Card, CardHeader } from '../components/ui';

const WORRY_TONE = { red: 'err', amber: 'warn', green: 'ok' };

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
    <Card className="p-4" variant="glass">
      <CardHeader
        title="What’s going on (plain English)"
        subtitle="For reviewers and stakeholders — technical stats are below"
        right={
          <Badge
            value={worry.label || '—'}
            tone={WORRY_TONE[worry.level] || 'warn'}
            dot
          />
        }
      />

      <p className="mt-3 text-base text-[var(--cds-sys-text-primary)] leading-relaxed">
        {briefing.headline || briefing.narrative_plain}
      </p>
      {worry.phrase && (
        <p className="mt-1.5 text-sm text-[var(--cds-sys-text-secondary)]">{worry.phrase}</p>
      )}
      {briefing.prr_plain && (
        <p className="mt-2 text-sm text-[var(--cds-sys-text-secondary)]">
          <span className="text-[var(--cds-sys-text-tertiary)]">In numbers: </span>
          {briefing.prr_plain}
        </p>
      )}

      {why.length > 0 && (
        <div className="mt-4">
          <div className="text-[10px] uppercase tracking-wide text-[var(--cds-sys-text-tertiary)] mb-1.5">
            Why we think that
          </div>
          <ul className="space-y-1.5 text-sm text-[var(--cds-sys-text-secondary)] list-disc list-inside">
            {why.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        </div>
      )}

      {glossary.length > 0 && (
        <div className="mt-4">
          <div className="text-[10px] uppercase tracking-wide text-[var(--cds-sys-text-tertiary)] mb-1.5">
            What the jargon means
          </div>
          <div className="flex flex-wrap gap-2">
            {glossary.map((g) => (
              <Badge
                key={g.term}
                tone="muted"
                title={g.plain}
                className="max-w-xs whitespace-normal text-left"
              >
                <span className="font-medium">{g.term}</span>
                <span className="opacity-60"> — </span>
                {g.plain}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {steps.length > 0 && (
        <div className="mt-4">
          <div className="text-[10px] uppercase tracking-wide text-[var(--cds-sys-text-tertiary)] mb-2">
            What you can do next
          </div>
          <div className="flex flex-wrap gap-2">
            {steps.map((s) => {
              if (s.href || s.action === 'open_risk_populations') {
                const href = s.href || '/lenses?tab=risk';
                return (
                  <Link key={s.id} to={href}>
                    <Button variant="outline" size="sm">{s.label}</Button>
                  </Link>
                );
              }
              return (
                <Button
                  key={s.id}
                  variant="outline"
                  size="sm"
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
        <p className="mt-4 text-[10px] text-[var(--cds-sys-text-tertiary)] leading-relaxed">{briefing.disclaimer}</p>
      )}
    </Card>
  );
}
