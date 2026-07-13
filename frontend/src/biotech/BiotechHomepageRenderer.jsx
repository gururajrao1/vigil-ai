import { BIOTECH_TOKENS as T } from './tokens';

const toneColor = (tone) => {
  if (tone === 'mint') return T.mint;
  if (tone === 'sky') return T.sky;
  return T.muted;
};

function TopNav({ navigation, onNavigate }) {
  if (!navigation) return null;
  return (
    <header
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 40,
        background: 'rgba(11,18,32,0.92)',
        borderBottom: `1px solid ${T.border}`,
        backdropFilter: 'blur(10px)',
        display: 'flex',
        alignItems: 'center',
        gap: 28,
        padding: '0 clamp(20px, 4vw, 56px)',
        height: 64,
      }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
        <span
          style={{
            fontFamily: T.fontDisplay,
            fontWeight: 800,
            fontSize: 17,
            letterSpacing: '-0.04em',
            color: T.text,
          }}
        >
          {navigation.brand}
        </span>
        <span style={{ fontSize: 10, color: T.muted, letterSpacing: '0.04em' }}>
          {navigation.wordmark_sub}
        </span>
      </div>
      <nav style={{ display: 'flex', gap: 6, marginLeft: 'auto', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
        {(navigation.items || []).map((item) => (
          <button
            key={item.id}
            type="button"
            disabled={!!item.disabled}
            onClick={() => { if (!item.disabled) onNavigate?.(item.href); }}
            style={{
              fontFamily: T.fontDisplay,
              fontSize: 13,
              fontWeight: item.emphasis ? 700 : 500,
              color: item.emphasis ? T.canvas : T.muted,
              background: item.emphasis ? T.mint : 'transparent',
              border: item.emphasis ? 'none' : `1px solid ${T.border}`,
              padding: '8px 14px',
              cursor: item.disabled ? 'wait' : 'pointer',
              letterSpacing: '-0.02em',
              opacity: item.disabled ? 0.55 : 1,
            }}
          >
            {item.label}
          </button>
        ))}
      </nav>
    </header>
  );
}

function HeroManifesto({ hero, onNavigate }) {
  if (!hero) return null;
  return (
    <section
      id="manifesto"
      style={{
        background: T.navy,
        borderBottom: `1px solid ${T.border}`,
        padding: 'clamp(48px, 8vw, 96px) clamp(20px, 4vw, 56px)',
        display: 'grid',
        gridTemplateColumns: 'minmax(0, 1.4fr) minmax(240px, 0.7fr)',
        gap: 'clamp(28px, 5vw, 64px)',
        alignItems: 'start',
      }}
      className="biotech-hero-grid"
    >
      <div style={{ borderLeft: `3px solid ${T.mint}`, paddingLeft: 28 }}>
        <p
          style={{
            margin: 0,
            fontFamily: T.fontMono,
            fontSize: 11,
            color: T.sky,
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
          }}
        >
          {hero.eyebrow}
        </p>
        <h1
          style={{
            margin: '18px 0 0',
            fontFamily: T.fontDisplay,
            fontWeight: 800,
            fontSize: 'clamp(2.4rem, 5.5vw, 4.25rem)',
            letterSpacing: '-0.04em',
            lineHeight: 1.02,
            color: T.text,
            maxWidth: 720,
          }}
        >
          {hero.title}
        </h1>
        <p
          style={{
            margin: '22px 0 0',
            fontSize: 18,
            lineHeight: 1.55,
            color: T.text,
            maxWidth: 560,
            fontWeight: 500,
            letterSpacing: '-0.02em',
          }}
        >
          {hero.lede}
        </p>
        <p style={{ margin: '16px 0 0', fontSize: 15, lineHeight: 1.65, color: T.muted, maxWidth: 580 }}>
          {hero.body}
        </p>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 22 }}>
          {(hero.env_tags || []).map((t) => (
            <span
              key={t}
              style={{
                fontFamily: T.fontMono,
                fontSize: 10,
                color: T.mint,
                border: `1px solid ${T.border}`,
                padding: '5px 9px',
                letterSpacing: '0.06em',
              }}
            >
              {t}
            </span>
          ))}
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginTop: 28 }}>
          {hero.primary_cta?.href && (
            <button
              type="button"
              disabled={!!hero.primary_cta.disabled}
              onClick={() => { if (!hero.primary_cta.disabled) onNavigate?.(hero.primary_cta.href); }}
              style={{
                fontFamily: T.fontDisplay,
                fontWeight: 700,
                fontSize: 14,
                letterSpacing: '-0.03em',
                background: T.mint,
                color: T.canvas,
                border: 'none',
                padding: '12px 20px',
                cursor: hero.primary_cta.disabled ? 'wait' : 'pointer',
                opacity: hero.primary_cta.disabled ? 0.55 : 1,
              }}
            >
              {hero.primary_cta.label}
            </button>
          )}
          {hero.secondary_cta?.href && hero.secondary_cta?.label ? (
            <button
              type="button"
              disabled={!!hero.secondary_cta.disabled}
              onClick={() => { if (!hero.secondary_cta.disabled) onNavigate?.(hero.secondary_cta.href); }}
              style={{
                fontFamily: T.fontDisplay,
                fontWeight: 600,
                fontSize: 14,
                letterSpacing: '-0.03em',
                background: 'transparent',
                color: T.text,
                border: `1px solid ${T.border}`,
                padding: '12px 20px',
                cursor: hero.secondary_cta.disabled ? 'wait' : 'pointer',
                opacity: hero.secondary_cta.disabled ? 0.55 : 1,
              }}
            >
              {hero.secondary_cta.label}
            </button>
          ) : null}
        </div>
      </div>
      <aside style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {(hero.throughput || []).map((s) => (
          <div
            key={s.label}
            style={{
              background: T.glass,
              border: `1px solid ${T.border}`,
              padding: '18px 20px',
            }}
          >
            <div style={{ fontSize: 11, color: T.muted, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
              {s.label}
            </div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 8 }}>
              <span style={{ fontFamily: T.fontMono, fontSize: 32, fontWeight: 600, color: T.sky }}>
                {s.value}
              </span>
              {s.unit && (
                <span style={{ fontFamily: T.fontMono, fontSize: 11, color: T.muted }}>{s.unit}</span>
              )}
            </div>
            <div style={{ marginTop: 8, fontFamily: T.fontMono, fontSize: 9, color: T.muted, letterSpacing: '0.04em' }}>
              {s.provenance}
            </div>
          </div>
        ))}
      </aside>
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
      style={{
        padding: 'clamp(48px, 7vw, 88px) clamp(20px, 4vw, 56px)',
        borderBottom: `1px solid ${T.border}`,
      }}
    >
      <p style={{ margin: 0, fontFamily: T.fontMono, fontSize: 11, color: T.mint, letterSpacing: '0.1em' }}>
        CORE TECHNOLOGY PILLARS
      </p>
      <h2
        style={{
          margin: '12px 0 0',
          fontFamily: T.fontDisplay,
          fontWeight: 800,
          fontSize: 'clamp(1.75rem, 3vw, 2.5rem)',
          letterSpacing: '-0.04em',
          color: T.text,
          maxWidth: 520,
        }}
      >
        Four gates. Offline-first. No silent API key debt.
      </h2>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
          gap: 16,
          marginTop: 36,
        }}
      >
        {pillars.map((p) => (
          <article
            key={p.id}
            style={{
              background: T.navy,
              border: `1px solid ${T.border}`,
              padding: '24px 22px',
              borderTop: `2px solid ${p.accent === 'sky' ? T.sky : T.mint}`,
            }}
          >
            <div style={{ fontFamily: T.fontMono, fontSize: 11, color: p.accent === 'sky' ? T.sky : T.mint }}>
              {p.gate}
            </div>
            <h3
              style={{
                margin: '12px 0 0',
                fontFamily: T.fontDisplay,
                fontWeight: 700,
                fontSize: 20,
                letterSpacing: '-0.03em',
                color: T.text,
              }}
            >
              {p.title}
            </h3>
            <p style={{ margin: '12px 0 0', fontSize: 14, lineHeight: 1.6, color: T.muted }}>{p.narrative}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

function PipelineSwimlane({ stages }) {
  if (!stages?.length) return null;
  return (
    <section
      style={{
        padding: '40px clamp(20px, 4vw, 56px)',
        borderBottom: `1px solid ${T.border}`,
        background: T.navy,
      }}
    >
      <p style={{ margin: 0, fontFamily: T.fontMono, fontSize: 11, color: T.sky, letterSpacing: '0.1em' }}>
        PIPELINE SWIMLANE
      </p>
      <div
        style={{
          display: 'flex',
          gap: 0,
          marginTop: 20,
          overflowX: 'auto',
          border: `1px solid ${T.border}`,
        }}
      >
        {stages.map((st, i) => (
          <div
            key={st.id}
            style={{
              flex: '1 0 140px',
              padding: '18px 16px',
              borderRight: i < stages.length - 1 ? `1px solid ${T.border}` : 'none',
              background: T.glass,
            }}
          >
            <div
              style={{
                width: 8,
                height: 8,
                background: st.state === 'active' ? T.mint : st.state === 'ready' ? T.sky : T.border,
                marginBottom: 12,
              }}
            />
            <div style={{ fontFamily: T.fontDisplay, fontWeight: 700, fontSize: 14, color: T.text, letterSpacing: '-0.02em' }}>
              {st.label}
            </div>
            <div style={{ marginTop: 6, fontSize: 12, color: T.muted, lineHeight: 1.4 }}>{st.detail}</div>
          </div>
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
      style={{
        padding: 'clamp(48px, 7vw, 88px) clamp(20px, 4vw, 56px)',
        borderBottom: `1px solid ${T.border}`,
      }}
    >
      <p style={{ margin: 0, fontFamily: T.fontMono, fontSize: 11, color: T.mint, letterSpacing: '0.1em' }}>
        {spot.eyebrow}
      </p>
      <div
        style={{
          marginTop: 20,
          background: T.navy,
          border: `1px solid ${T.border}`,
          padding: 'clamp(24px, 4vw, 40px)',
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1.5fr) minmax(200px, 0.7fr)',
          gap: 32,
        }}
        className="biotech-spot-grid"
      >
        <div>
          <h2
            style={{
              margin: 0,
              fontFamily: T.fontDisplay,
              fontWeight: 800,
              fontSize: 'clamp(1.6rem, 3vw, 2.35rem)',
              letterSpacing: '-0.04em',
              color: T.text,
            }}
          >
            {spot.headline}
          </h2>
          <p style={{ margin: '16px 0 0', fontSize: 15, lineHeight: 1.7, color: T.muted, maxWidth: 640 }}>
            {spot.narrative}
          </p>
          {spot.patient_voice && (
            <blockquote
              style={{
                margin: '22px 0 0',
                padding: '16px 0 16px 18px',
                borderLeft: `2px solid ${T.sky}`,
                color: T.text,
                fontSize: 15,
                lineHeight: 1.6,
                fontStyle: 'normal',
              }}
            >
              {spot.patient_voice}
            </blockquote>
          )}
          <p style={{ margin: '18px 0 0', fontFamily: T.fontMono, fontSize: 11, color: T.muted, lineHeight: 1.5 }}>
            {spot.provenance_note}
          </p>
          {spot.href && (
            <button
              type="button"
              onClick={() => onNavigate?.(spot.href)}
              style={{
                marginTop: 22,
                fontFamily: T.fontDisplay,
                fontWeight: 600,
                fontSize: 13,
                background: 'transparent',
                color: T.sky,
                border: `1px solid ${T.border}`,
                padding: '10px 16px',
                cursor: 'pointer',
              }}
            >
              Open this pair →
            </button>
          )}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {(spot.flags || []).map((f) => (
            <div
              key={f.key}
              style={{
                background: T.glass,
                border: `1px solid ${T.border}`,
                padding: '14px 16px',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'baseline',
                gap: 12,
              }}
            >
              <span style={{ fontFamily: T.fontMono, fontSize: 11, color: T.muted, letterSpacing: '0.06em' }}>
                {f.key}
              </span>
              <span
                style={{
                  fontFamily: T.fontMono,
                  fontSize: 22,
                  fontWeight: 700,
                  color: toneColor(f.tone),
                  letterSpacing: '-0.02em',
                }}
              >
                {f.value}
              </span>
            </div>
          ))}
        </div>
      </div>
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
      style={{
        padding: '40px clamp(20px, 4vw, 56px)',
        borderBottom: `1px solid ${T.border}`,
        background: T.navy,
      }}
    >
      <h2
        style={{
          margin: 0,
          fontFamily: T.fontDisplay,
          fontWeight: 700,
          fontSize: 20,
          letterSpacing: '-0.03em',
          color: T.text,
        }}
      >
        {honesty.title}
      </h2>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 20, marginTop: 20 }}>
        <p style={{ margin: 0, fontSize: 14, lineHeight: 1.65, color: T.muted }}>
          <strong style={{ color: T.mint }}>Live unstructured pipeline.</strong> {honesty.live_pipeline}
        </p>
        <p style={{ margin: 0, fontSize: 14, lineHeight: 1.65, color: T.muted }}>
          <strong style={{ color: T.sky }}>Local reference surrogates.</strong> {honesty.surrogate_benchmarks}
        </p>
      </div>
      {(honesty.never_claim || []).length > 0 && (
        <ul style={{ margin: '18px 0 0', paddingLeft: 18, color: T.muted, fontSize: 13, lineHeight: 1.7 }}>
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
    <section style={{ padding: '48px clamp(20px, 4vw, 56px)', borderBottom: `1px solid ${T.border}` }}>
      <h2
        style={{
          margin: 0,
          fontFamily: T.fontDisplay,
          fontWeight: 800,
          fontSize: 'clamp(1.5rem, 2.5vw, 2rem)',
          letterSpacing: '-0.04em',
          color: T.text,
        }}
      >
        {strip.title}
      </h2>
      <p style={{ margin: '12px 0 0', color: T.muted, fontSize: 15, maxWidth: 560, lineHeight: 1.6 }}>
        {strip.body}
      </p>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 22 }}>
        {(strip.buttons || []).map((b) => (
          <button
            key={`${b.label}-${b.href}`}
            type="button"
            disabled={!!b.disabled}
            onClick={() => { if (!b.disabled) onNavigate?.(b.href); }}
            style={{
              fontFamily: T.fontDisplay,
              fontWeight: 600,
              fontSize: 13,
              background: T.glass,
              color: T.text,
              border: `1px solid ${T.border}`,
              padding: '10px 16px',
              cursor: b.disabled ? 'wait' : 'pointer',
              opacity: b.disabled ? 0.55 : 1,
            }}
          >
            {b.label}
          </button>
        ))}
      </div>
    </section>
  );
}

function ActionBar({ actions, onAction }) {
  if (!actions?.length) return null;
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, padding: '20px clamp(20px, 4vw, 56px)' }}>
      {actions.map((a) => (
        <button
          key={a.id}
          type="button"
          onClick={() => onAction?.(a)}
          style={{
            fontFamily: T.fontMono,
            fontSize: 11,
            color: T.muted,
            background: 'transparent',
            border: `1px solid ${T.border}`,
            padding: '8px 12px',
            cursor: 'pointer',
          }}
        >
          {a.label}
        </button>
      ))}
    </div>
  );
}

/** High-contrast digital stage — paints vigilai.biotech_homepage.v1 only. */
export default function BiotechHomepageRenderer({ layout, onNavigate, onAction }) {
  if (!layout) return null;
  return (
    <div
      style={{
        minHeight: '100vh',
        background: T.canvas,
        color: T.text,
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
          style={{
            borderTop: `1px solid ${T.border}`,
            padding: '18px clamp(20px, 4vw, 56px) 40px',
            fontSize: 11,
            color: T.muted,
            lineHeight: 1.5,
          }}
        >
          {layout.disclaimer}
        </footer>
      )}
    </div>
  );
}
