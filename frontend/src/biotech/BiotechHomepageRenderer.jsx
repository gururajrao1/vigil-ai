import {
  Alert,
  AppHeader,
  AppHeaderBrand,
  AppHeaderControls,
  AppHeaderNav,
  AppHeaderTitle,
  Badge,
  BrandIcon,
  Button,
  Card,
  Spinner,
} from '@clairlabs-ai/prp-ui';
import { BIOTECH_TOKENS as T } from './tokens';

const toneBadge = (tone) => {
  if (tone === 'mint') return 'ok';
  if (tone === 'sky') return 'info';
  return 'muted';
};

function TopNav({ navigation, onNavigate }) {
  if (!navigation) return null;
  const items = navigation.items || [];
  const primary = items.find((i) => i.emphasis);
  const links = items.filter((i) => !i.emphasis);

  return (
    <AppHeader>
      <AppHeaderBrand>
        <BrandIcon aria-hidden>VA</BrandIcon>
        <AppHeaderTitle>
          <span className="cds-text-gradient">{navigation.brand}</span>
          {navigation.wordmark_sub ? (
            <div className="text-[10px] text-[var(--cds-sys-text-tertiary)] tracking-wide font-normal mt-0.5">
              {navigation.wordmark_sub}
            </div>
          ) : null}
        </AppHeaderTitle>
      </AppHeaderBrand>
      <AppHeaderNav aria-label="Homepage sections">
        {links.map((item) => (
          <Button
            key={item.id}
            type="button"
            variant="ghost"
            size="sm"
            disabled={!!item.disabled}
            onClick={() => { if (!item.disabled) onNavigate?.(item.href); }}
          >
            {item.label}
          </Button>
        ))}
      </AppHeaderNav>
      <AppHeaderControls>
        {primary && (
          <Button
            type="button"
            variant="gradient"
            size="sm"
            disabled={!!primary.disabled}
            loading={!!primary.disabled}
            onClick={() => { if (!primary.disabled) onNavigate?.(primary.href); }}
          >
            {primary.label}
          </Button>
        )}
      </AppHeaderControls>
    </AppHeader>
  );
}

function HeroManifesto({ hero, onNavigate }) {
  if (!hero) return null;
  return (
    <section
      id="manifesto"
      className="biotech-hero relative overflow-hidden border-b border-[var(--cds-sys-border-glass)]"
      style={{
        padding: 'clamp(48px, 8vw, 96px) clamp(20px, 4vw, 56px)',
        background: 'var(--cds-sys-gradient-deep)',
      }}
    >
      {/* Clair orb atmosphere — decorative only */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background: `
            ${'var(--cds-sys-orb-1)'} 0% 0% / 55% 55% no-repeat,
            ${'var(--cds-sys-orb-2)'} 100% 10% / 50% 50% no-repeat,
            ${'var(--cds-sys-orb-3)'} 60% 100% / 45% 45% no-repeat
          `,
          opacity: 0.85,
        }}
      />
      <div
        className="biotech-hero-grid relative z-[1] grid gap-[clamp(28px,5vw,64px)] items-start"
        style={{ gridTemplateColumns: 'minmax(0, 1.4fr) minmax(240px, 0.7fr)' }}
      >
        <div className="border-l-[3px] border-[var(--cds-sys-accent-primary)] pl-7">
          <p className="m-0 font-mono text-[11px] uppercase tracking-[0.08em] text-[var(--cds-sys-accent-secondary)]">
            {hero.eyebrow}
          </p>
          <h1
            className="cds-text-gradient mt-[18px] mb-0 font-extrabold leading-[1.02] tracking-tight max-w-[720px]"
            style={{
              fontFamily: T.fontDisplay,
              fontSize: 'clamp(2.4rem, 5.5vw, 4.25rem)',
            }}
          >
            {hero.title}
          </h1>
          <p
            className="mt-[22px] mb-0 max-w-[560px] text-[18px] font-medium leading-[1.55] tracking-tight text-[var(--cds-sys-text-primary)]"
          >
            {hero.lede}
          </p>
          <p className="mt-4 mb-0 max-w-[580px] text-[15px] leading-[1.65] text-[var(--cds-sys-text-secondary)]">
            {hero.body}
          </p>
          <div className="mt-[22px] flex flex-wrap gap-2">
            {(hero.env_tags || []).map((tag) => (
              <Badge key={tag} tone="brand">
                {tag}
              </Badge>
            ))}
          </div>
          <div className="mt-7 flex flex-wrap gap-3">
            {hero.primary_cta?.href && (
              <Button
                type="button"
                variant="gradient"
                size="lg"
                disabled={!!hero.primary_cta.disabled}
                loading={!!hero.primary_cta.disabled}
                onClick={() => { if (!hero.primary_cta.disabled) onNavigate?.(hero.primary_cta.href); }}
              >
                {hero.primary_cta.label}
              </Button>
            )}
            {hero.secondary_cta?.href && hero.secondary_cta?.label ? (
              <Button
                type="button"
                variant="outline"
                size="lg"
                disabled={!!hero.secondary_cta.disabled}
                onClick={() => { if (!hero.secondary_cta.disabled) onNavigate?.(hero.secondary_cta.href); }}
              >
                {hero.secondary_cta.label}
              </Button>
            ) : null}
          </div>
        </div>
        <aside className="flex flex-col gap-3">
          {(hero.throughput || []).map((s) => (
            <Card key={s.label} variant="glass" className="px-5 py-[18px]">
              <div className="text-[11px] uppercase tracking-[0.06em] text-[var(--cds-sys-text-secondary)]">
                {s.label}
              </div>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="font-mono text-[32px] font-semibold text-[var(--cds-sys-accent-primary)]">
                  {s.value}
                </span>
                {s.unit && (
                  <span className="font-mono text-[11px] text-[var(--cds-sys-text-tertiary)]">{s.unit}</span>
                )}
              </div>
              <div className="mt-2 font-mono text-[9px] tracking-wide text-[var(--cds-sys-text-tertiary)]">
                {s.provenance}
              </div>
            </Card>
          ))}
        </aside>
      </div>
      <style>{`
        @media (max-width: 900px) {
          .biotech-hero-grid { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </section>
  );
}

function TechnologyPillars({ pillars }) {
  if (!pillars?.length) return null;
  return (
    <section
      id="pillars"
      className="border-b border-[var(--cds-sys-border-glass)]"
      style={{ padding: 'clamp(48px, 7vw, 88px) clamp(20px, 4vw, 56px)' }}
    >
      <p className="m-0 font-mono text-[11px] tracking-[0.1em] text-[var(--cds-sys-accent-primary)]">
        CORE TECHNOLOGY PILLARS
      </p>
      <h2
        className="mt-3 mb-0 max-w-[520px] font-extrabold tracking-tight text-[var(--cds-sys-text-primary)]"
        style={{ fontFamily: T.fontDisplay, fontSize: 'clamp(1.75rem, 3vw, 2.5rem)' }}
      >
        Four gates. Offline-first. No silent API key debt.
      </h2>
      <div
        className="mt-9 grid gap-4"
        style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))' }}
      >
        {pillars.map((p) => (
          <Card key={p.id} variant="interactive" className="p-[22px_22px_24px]">
            <Badge tone={p.accent === 'sky' ? 'info' : 'brand'} dot>
              {p.gate}
            </Badge>
            <h3
              className="mt-3 mb-0 font-bold tracking-tight text-[var(--cds-sys-text-primary)]"
              style={{ fontFamily: T.fontDisplay, fontSize: 20 }}
            >
              {p.title}
            </h3>
            <p className="mt-3 mb-0 text-sm leading-relaxed text-[var(--cds-sys-text-secondary)]">
              {p.narrative}
            </p>
          </Card>
        ))}
      </div>
    </section>
  );
}

function PipelineSwimlane({ stages }) {
  if (!stages?.length) return null;
  return (
    <section
      className="border-b border-[var(--cds-sys-border-glass)]"
      style={{
        padding: '40px clamp(20px, 4vw, 56px)',
        background: 'var(--cds-sys-surface-chrome)',
      }}
    >
      <p className="m-0 font-mono text-[11px] tracking-[0.1em] text-[var(--cds-sys-accent-secondary)]">
        PIPELINE SWIMLANE
      </p>
      <div className="mt-5 flex gap-3 overflow-x-auto pb-1">
        {stages.map((st) => (
          <Card
            key={st.id}
            variant={st.state === 'active' ? 'deep' : 'glass'}
            className="min-w-[140px] flex-1 px-4 py-[18px]"
          >
            <Badge
              tone={st.state === 'active' ? 'ok' : st.state === 'ready' ? 'info' : 'muted'}
              dot
              pulse={st.state === 'active'}
            >
              {st.state}
            </Badge>
            <div
              className="mt-3 font-bold text-sm tracking-tight text-[var(--cds-sys-text-primary)]"
              style={{ fontFamily: T.fontDisplay }}
            >
              {st.label}
            </div>
            <div className="mt-1.5 text-xs leading-snug text-[var(--cds-sys-text-secondary)]">
              {st.detail}
            </div>
          </Card>
        ))}
      </div>
    </section>
  );
}

function SignalSpotlight({ spot, onNavigate }) {
  if (!spot) return null;
  return (
    <section
      id="spotlight"
      className="border-b border-[var(--cds-sys-border-glass)]"
      style={{ padding: 'clamp(48px, 7vw, 88px) clamp(20px, 4vw, 56px)' }}
    >
      <p className="m-0 font-mono text-[11px] tracking-[0.1em] text-[var(--cds-sys-accent-primary)]">
        {spot.eyebrow}
      </p>
      <Card
        variant="deep"
        className="biotech-spot-grid mt-5 grid gap-8 p-[clamp(24px,4vw,40px)]"
        style={{ gridTemplateColumns: 'minmax(0, 1.5fr) minmax(200px, 0.7fr)' }}
      >
        <div>
          <h2
            className="cds-text-gradient m-0 font-extrabold tracking-tight"
            style={{ fontFamily: T.fontDisplay, fontSize: 'clamp(1.6rem, 3vw, 2.35rem)' }}
          >
            {spot.headline}
          </h2>
          <p className="mt-4 mb-0 max-w-[640px] text-[15px] leading-[1.7] text-[var(--cds-sys-text-secondary)]">
            {spot.narrative}
          </p>
          {spot.patient_voice && (
            <blockquote className="mt-[22px] mb-0 border-l-2 border-[var(--cds-sys-accent-secondary)] py-4 pl-[18px] text-[15px] leading-relaxed text-[var(--cds-sys-text-primary)] not-italic">
              {spot.patient_voice}
            </blockquote>
          )}
          <p className="mt-[18px] mb-0 font-mono text-[11px] leading-snug text-[var(--cds-sys-text-tertiary)]">
            {spot.provenance_note}
          </p>
          {spot.href && (
            <Button
              type="button"
              variant="outline"
              className="mt-[22px]"
              onClick={() => onNavigate?.(spot.href)}
            >
              Open this pair →
            </Button>
          )}
        </div>
        <div className="flex flex-col gap-2.5">
          {(spot.flags || []).map((f) => (
            <Card key={f.key} variant="glass" className="flex items-baseline justify-between gap-3 px-4 py-3.5">
              <span className="font-mono text-[11px] tracking-wide text-[var(--cds-sys-text-secondary)]">
                {f.key}
              </span>
              <Badge tone={toneBadge(f.tone)}>{f.value}</Badge>
            </Card>
          ))}
        </div>
      </Card>
      <style>{`
        @media (max-width: 800px) {
          .biotech-spot-grid { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </section>
  );
}

function Honesty({ honesty }) {
  if (!honesty) return null;
  return (
    <section
      className="border-b border-[var(--cds-sys-border-glass)]"
      style={{
        padding: '40px clamp(20px, 4vw, 56px)',
        background: 'var(--cds-sys-surface-chrome)',
      }}
    >
      <h2
        className="m-0 font-bold tracking-tight text-[var(--cds-sys-text-primary)]"
        style={{ fontFamily: T.fontDisplay, fontSize: 20 }}
      >
        {honesty.title}
      </h2>
      <div
        className="mt-5 grid gap-5"
        style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))' }}
      >
        <Alert tone="info" title="Live unstructured pipeline">
          {honesty.live_pipeline}
        </Alert>
        <Alert tone="success" title="Local reference surrogates">
          {honesty.surrogate_benchmarks}
        </Alert>
      </div>
      {(honesty.never_claim || []).length > 0 && (
        <ul className="mt-[18px] mb-0 list-disc pl-[18px] text-[13px] leading-relaxed text-[var(--cds-sys-text-secondary)]">
          {honesty.never_claim.map((n) => (
            <li key={n}>Never claimed: {n}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

function CtaStrip({ strip, onNavigate }) {
  if (!strip) return null;
  return (
    <section
      className="border-b border-[var(--cds-sys-border-glass)]"
      style={{ padding: '48px clamp(20px, 4vw, 56px)' }}
    >
      <Card variant="glass" className="p-8" style={{ background: 'var(--cds-sys-gradient-soft)' }}>
        <h2
          className="cds-text-gradient m-0 font-extrabold tracking-tight"
          style={{ fontFamily: T.fontDisplay, fontSize: 'clamp(1.5rem, 2.5vw, 2rem)' }}
        >
          {strip.title}
        </h2>
        <p className="mt-3 mb-0 max-w-[560px] text-[15px] leading-relaxed text-[var(--cds-sys-text-secondary)]">
          {strip.body}
        </p>
        <div className="mt-[22px] flex flex-wrap gap-2.5">
          {(strip.buttons || []).map((b) => (
            <Button
              key={`${b.label}-${b.href}`}
              type="button"
              variant="gradient"
              disabled={!!b.disabled}
              onClick={() => { if (!b.disabled) onNavigate?.(b.href); }}
            >
              {b.label}
            </Button>
          ))}
        </div>
      </Card>
    </section>
  );
}

function ActionBar({ actions, onAction }) {
  if (!actions?.length) return null;
  return (
    <div className="flex flex-wrap gap-2" style={{ padding: '20px clamp(20px, 4vw, 56px)' }}>
      {actions.map((a) => (
        <Button
          key={a.id}
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => onAction?.(a)}
        >
          {a.label}
        </Button>
      ))}
    </div>
  );
}

/** Clair-styled public homepage — paints vigilai.biotech_homepage.v1 only. */
export default function BiotechHomepageRenderer({ layout, onNavigate, onAction }) {
  if (!layout) return null;
  return (
    <div
      className="min-h-[100vh] text-[var(--cds-sys-text-primary)]"
      style={{
        background: T.canvas,
        fontFamily: T.fontDisplay,
      }}
    >
      <TopNav navigation={layout.navigation} onNavigate={onNavigate} />
      <HeroManifesto hero={layout.hero_manifesto} onNavigate={onNavigate} />
      <TechnologyPillars pillars={layout.technology_pillars} />
      <PipelineSwimlane stages={layout.pipeline_swimlane} />
      <SignalSpotlight spot={layout.signal_spotlight} onNavigate={onNavigate} />
      <Honesty honesty={layout.honesty} />
      <CtaStrip strip={layout.cta_strip} onNavigate={onNavigate} />
      <ActionBar actions={layout.actions} onAction={onAction} />
      {layout.disclaimer && (
        <footer
          className="border-t border-[var(--cds-sys-border-glass)] text-[11px] leading-snug text-[var(--cds-sys-text-tertiary)]"
          style={{ padding: '18px clamp(20px, 4vw, 56px) 40px' }}
        >
          {layout.disclaimer}
        </footer>
      )}
    </div>
  );
}
