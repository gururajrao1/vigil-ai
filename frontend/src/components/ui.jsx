// Small reusable UI primitives — VigilAI Life Sciences stage (4px, no motion).

export function Card({ children, className = '' }) {
  return (
    <div
      className={`border border-[var(--app-border)] bg-[var(--app-surface)] ${className}`}
      style={{ borderRadius: 'var(--va-radius, 4px)' }}
    >
      {children}
    </div>
  );
}

export function CardHeader({ title, subtitle, right }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-2 px-4 pt-4">
      <div className="min-w-0 flex-1">
        <h3
          className="text-sm font-bold text-[var(--app-text)] break-words"
          style={{ letterSpacing: '-0.03em' }}
        >
          {title}
        </h3>
        {subtitle && <p className="text-xs text-[var(--app-text-muted)] mt-0.5 break-words">{subtitle}</p>}
      </div>
      {right != null && <div className="shrink-0 max-w-full">{right}</div>}
    </div>
  );
}

const STRENGTH_COLORS = {
  STRONG: 'bg-[rgba(45,212,191,0.12)] text-[var(--app-accent)] border-[var(--app-border)]',
  MODERATE: 'bg-[rgba(56,189,248,0.12)] text-[var(--app-accent-sky)] border-[var(--app-border)]',
  WEAK: 'bg-transparent text-[var(--app-text-muted)] border-[var(--app-border)]',
};
const SEVERITY_COLORS = {
  Critical: 'bg-[rgba(244,63,94,0.12)] text-rose-300 border-[var(--app-border)]',
  High: 'bg-[rgba(56,189,248,0.12)] text-[var(--app-accent-sky)] border-[var(--app-border)]',
  Medium: 'bg-transparent text-[var(--app-text-muted)] border-[var(--app-border)]',
  Low: 'bg-[rgba(45,212,191,0.12)] text-[var(--app-accent)] border-[var(--app-border)]',
};
const CAUSALITY_COLORS = {
  Certain: 'bg-[rgba(45,212,191,0.12)] text-[var(--app-accent)] border-[var(--app-border)]',
  Probable: 'bg-[rgba(56,189,248,0.12)] text-[var(--app-accent-sky)] border-[var(--app-border)]',
  Possible: 'bg-transparent text-[var(--app-text-muted)] border-[var(--app-border)]',
  Unlikely: 'bg-transparent text-[var(--app-text-faint)] border-[var(--app-border)]',
  Unassessable: 'bg-transparent text-[var(--app-text-faint)] border-[var(--app-border)]',
};

export function Badge({ children, kind, value, className = '' }) {
  let colors = 'bg-transparent text-[var(--app-text-muted)] border-[var(--app-border)]';
  if (kind === 'strength') colors = STRENGTH_COLORS[value] || colors;
  if (kind === 'severity') colors = SEVERITY_COLORS[value] || colors;
  if (kind === 'causality') colors = CAUSALITY_COLORS[value] || colors;
  return (
    <span
      className={`inline-flex items-center border px-2 py-0.5 text-[10px] font-medium font-mono tracking-wide ${colors} ${className}`}
      style={{ borderRadius: 'var(--va-radius, 4px)' }}
    >
      {children ?? value}
    </span>
  );
}

export function StatCard({ label, value, sub, accent = 'text-[var(--app-accent-sky)]', icon }) {
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-[0.08em] text-[var(--app-text-muted)] font-mono">{label}</span>
        {icon && <span className="text-[var(--app-text-faint)]">{icon}</span>}
      </div>
      <div className={`mt-2 font-mono font-bold tracking-tight text-2xl sm:text-3xl ${accent}`}>{value}</div>
      {sub && <div className="mt-1 text-xs text-[var(--app-text-muted)]">{sub}</div>}
    </Card>
  );
}

export function Spinner({ label = 'Loading…' }) {
  return (
    <div className="flex items-center gap-2 text-[var(--app-text-muted)] text-sm py-8 justify-center font-mono text-xs tracking-wide">
      <span
        className="inline-block h-2 w-2 bg-[var(--app-accent)]"
        style={{ borderRadius: 0 }}
        aria-hidden
      />
      {label}
    </div>
  );
}

export function Button({ children, onClick, variant = 'primary', disabled, className = '', type = 'button' }) {
  const styles = {
    primary: 'bg-[var(--app-accent)] hover:opacity-90 text-[#030712]',
    ghost: 'bg-[var(--app-surface)] hover:bg-[var(--app-surface-hover)] text-[var(--app-text-secondary)] border border-[var(--app-border)]',
    danger: 'bg-rose-700 hover:opacity-90 text-white',
  };
  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      className={`px-3 py-1.5 text-sm font-semibold disabled:opacity-50 ${styles[variant] || styles.primary} ${className}`}
      style={{ borderRadius: 'var(--va-radius, 4px)', letterSpacing: '-0.02em' }}
    >
      {children}
    </button>
  );
}
