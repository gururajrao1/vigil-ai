// Small reusable UI primitives (Tailwind).

export function Card({ children, className = '' }) {
  return (
    <div className={`rounded-xl border border-[var(--app-border)] bg-[var(--app-surface)] backdrop-blur ${className}`}>
      {children}
    </div>
  );
}

export function CardHeader({ title, subtitle, right }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-2 px-4 pt-4">
      <div className="min-w-0 flex-1">
        <h3 className="text-sm font-semibold text-[var(--app-text)] break-words">{title}</h3>
        {subtitle && <p className="text-xs text-[var(--app-text-muted)] mt-0.5 break-words">{subtitle}</p>}
      </div>
      {right != null && <div className="shrink-0 max-w-full">{right}</div>}
    </div>
  );
}

const STRENGTH_COLORS = {
  STRONG: 'bg-rose-500/15 text-rose-300 border-rose-500/30',
  MODERATE: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  WEAK: 'bg-slate-500/15 text-slate-300 border-slate-500/30',
};
const SEVERITY_COLORS = {
  Critical: 'bg-rose-600/20 text-rose-300 border-rose-600/40',
  High: 'bg-orange-500/15 text-orange-300 border-orange-500/30',
  Medium: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  Low: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
};
const CAUSALITY_COLORS = {
  Certain: 'bg-violet-500/15 text-violet-300 border-violet-500/30',
  Probable: 'bg-sky-500/15 text-sky-300 border-sky-500/30',
  Possible: 'bg-slate-500/15 text-slate-300 border-slate-500/30',
  Unlikely: 'bg-slate-700/40 text-slate-400 border-slate-600/40',
  Unassessable: 'bg-slate-700/40 text-slate-400 border-slate-600/40',
};

export function Badge({ children, kind, value, className = '' }) {
  let colors = 'bg-slate-500/15 text-slate-300 border-slate-500/30';
  if (kind === 'strength') colors = STRENGTH_COLORS[value] || colors;
  if (kind === 'severity') colors = SEVERITY_COLORS[value] || colors;
  if (kind === 'causality') colors = CAUSALITY_COLORS[value] || colors;
  return (
    <span className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium ${colors} ${className}`}>
      {children ?? value}
    </span>
  );
}

export function StatCard({ label, value, sub, accent = 'text-[var(--app-text)]', icon }) {
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between">
        <span className="text-xs uppercase tracking-wide text-[var(--app-text-muted)]">{label}</span>
        {icon && <span className="text-[var(--app-text-faint)]">{icon}</span>}
      </div>
      <div className={`mt-2 text-2xl sm:text-3xl font-bold ${accent}`}>{value}</div>
      {sub && <div className="mt-1 text-xs text-[var(--app-text-muted)]">{sub}</div>}
    </Card>
  );
}

export function Spinner({ label = 'Loading…' }) {
  return (
    <div className="flex items-center gap-2 text-[var(--app-text-muted)] text-sm py-8 justify-center">
      <div className="h-4 w-4 animate-spin rounded-full border-2 border-[var(--app-border)] border-t-sky-500" />
      {label}
    </div>
  );
}

export function Button({ children, onClick, variant = 'primary', disabled, className = '' }) {
  const styles = {
    primary: 'bg-sky-600 hover:bg-sky-500 text-white',
    ghost: 'bg-[var(--app-surface-hover)] hover:bg-[var(--app-border)] text-[var(--app-text-secondary)] border border-[var(--app-border)]',
    danger: 'bg-rose-600 hover:bg-rose-500 text-white',
  };
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`rounded-lg px-3 py-1.5 text-sm font-medium transition disabled:opacity-40 disabled:cursor-not-allowed ${styles[variant]} ${className}`}
    >
      {children}
    </button>
  );
}
