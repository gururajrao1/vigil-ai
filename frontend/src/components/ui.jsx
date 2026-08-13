// VigilAI shared primitives — thin wrappers over @clairlabs-ai/prp-ui.
// Preserve existing call sites (kind/value Badge, labeled Spinner, PaginationBar).

import {
  Badge as CdsBadge,
  Button as CdsButton,
  Card as CdsCard,
  Spinner as CdsSpinner,
} from '@clairlabs-ai/prp-ui';

export function Card({ children, className = '', variant = 'glass', ...rest }) {
  return (
    <CdsCard variant={variant} className={className} {...rest}>
      {children}
    </CdsCard>
  );
}

export function CardHeader({ title, subtitle, right }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-2 px-4 pt-4">
      <div className="min-w-0 flex-1">
        <h3 className="text-sm font-bold text-[var(--cds-sys-text-primary)] break-words tracking-tight">
          {title}
        </h3>
        {subtitle && (
          <p className="text-xs text-[var(--cds-sys-text-secondary)] mt-0.5 break-words">{subtitle}</p>
        )}
      </div>
      {right != null && <div className="shrink-0 max-w-full">{right}</div>}
    </div>
  );
}

const STRENGTH_TONE = { STRONG: 'ok', MODERATE: 'info', WEAK: 'muted' };
const SEVERITY_TONE = { Critical: 'err', High: 'warn', Medium: 'muted', Low: 'ok' };
const CAUSALITY_TONE = {
  Certain: 'ok',
  Probable: 'info',
  Possible: 'muted',
  Unlikely: 'muted',
  Unassessable: 'muted',
};

export function Badge({ children, kind, value, className = '', tone, dot, pulse, ...rest }) {
  let resolved = tone || 'muted';
  if (!tone) {
    if (kind === 'strength') resolved = STRENGTH_TONE[value] || 'muted';
    if (kind === 'severity') resolved = SEVERITY_TONE[value] || 'muted';
    if (kind === 'causality') resolved = CAUSALITY_TONE[value] || 'muted';
  }
  return (
    <CdsBadge tone={resolved} dot={dot} pulse={pulse} className={className} {...rest}>
      {children ?? value}
    </CdsBadge>
  );
}

export function StatCard({ label, value, sub, accent = 'text-[var(--cds-sys-accent-primary)]', icon }) {
  return (
    <Card className="p-4" variant="glass">
      <div className="flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-[0.08em] text-[var(--cds-sys-text-secondary)] font-mono">
          {label}
        </span>
        {icon && <span className="text-[var(--cds-sys-text-tertiary)]">{icon}</span>}
      </div>
      <div className={`mt-2 font-mono font-bold tracking-tight text-2xl sm:text-3xl ${accent}`}>{value}</div>
      {sub && <div className="mt-1 text-xs text-[var(--cds-sys-text-secondary)]">{sub}</div>}
    </Card>
  );
}

export function Spinner({ label = 'Loading…', size = 'sm' }) {
  return (
    <div className="flex items-center gap-2 text-[var(--cds-sys-text-secondary)] py-8 justify-center font-mono text-xs tracking-wide">
      <CdsSpinner size={size} label={label} />
      <span>{label}</span>
    </div>
  );
}

const BUTTON_VARIANT = {
  primary: 'gradient',
  secondary: 'outline',
  gradient: 'gradient',
  ghost: 'ghost',
  danger: 'danger',
  outline: 'outline',
  glass: 'glass',
};

export function Button({
  children,
  onClick,
  variant = 'primary',
  disabled,
  className = '',
  type = 'button',
  loading,
  size,
  ...rest
}) {
  return (
    <CdsButton
      type={type}
      disabled={disabled}
      onClick={onClick}
      variant={BUTTON_VARIANT[variant] || 'primary'}
      loading={loading}
      size={size}
      className={className}
      {...rest}
    >
      {children}
    </CdsButton>
  );
}

/** Compact prev/next pager for long tables. page is 1-based. */
export function PaginationBar({
  page,
  pageSize,
  total,
  onPageChange,
  className = '',
  label = 'rows',
}) {
  const totalPages = Math.max(1, Math.ceil((total || 0) / Math.max(1, pageSize || 1)));
  const safePage = Math.min(Math.max(1, page || 1), totalPages);
  const from = total === 0 ? 0 : (safePage - 1) * pageSize + 1;
  const to = Math.min(total, safePage * pageSize);
  if (total <= pageSize) {
    return (
      <div className={`flex items-center justify-between gap-2 text-[11px] text-[var(--cds-sys-text-tertiary)] ${className}`}>
        <span>
          {total} {label}
        </span>
      </div>
    );
  }
  return (
    <div className={`flex flex-wrap items-center justify-between gap-2 text-[11px] text-[var(--cds-sys-text-secondary)] ${className}`}>
      <span>
        Showing <span className="text-[var(--cds-sys-text-primary)] tabular-nums">{from}–{to}</span> of{' '}
        <span className="text-[var(--cds-sys-text-primary)] tabular-nums">{total}</span> {label}
      </span>
      <div className="flex items-center gap-1.5">
        <Button
          variant="outline"
          size="sm"
          disabled={safePage <= 1}
          onClick={() => onPageChange?.(safePage - 1)}
        >
          Prev
        </Button>
        <span className="font-mono text-[var(--cds-sys-text-primary)] px-1">
          {safePage} / {totalPages}
        </span>
        <Button
          variant="outline"
          size="sm"
          disabled={safePage >= totalPages}
          onClick={() => onPageChange?.(safePage + 1)}
        >
          Next
        </Button>
      </div>
    </div>
  );
}
