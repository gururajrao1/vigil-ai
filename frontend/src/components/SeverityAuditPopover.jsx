import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { Badge, Button, Spinner } from './ui';

function CheckCell({ check }) {
  if (!check) return <span className="text-[var(--app-text-faint)]">—</span>;
  const val = check.value == null ? '—' : Number(check.value).toFixed(3);
  return (
    <span className={check.met ? 'text-rose-300' : 'text-[var(--app-text-muted)]'}>
      {val}{' '}
      <span className="text-[10px] opacity-70">
        {check.op} {check.threshold}
        {check.met ? ' ✓' : ''}
      </span>
    </span>
  );
}

function MetricBlock({ title, formula, children }) {
  return (
    <div className="rounded-lg border border-[var(--app-border)] bg-[var(--app-surface-solid)]/80 p-2.5">
      <div className="text-[11px] font-semibold text-[var(--app-text)]">{title}</div>
      <div className="text-[10px] font-mono text-[var(--app-text-faint)] mt-0.5 leading-snug">{formula}</div>
      <div className="mt-2 space-y-1 text-[11px] text-[var(--app-text-secondary)]">{children}</div>
    </div>
  );
}

/**
 * Interactive severity badge → clinical parameter audit popover.
 * Loads GET /api/analytics/signal-audit/{id} on open (hover or click).
 */
export default function SeverityAuditPopover({ signalId, severity, className = '' }) {
  const [open, setOpen] = useState(false);
  const [audit, setAudit] = useState(null);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(false);
  const rootRef = useRef(null);
  const hoverTimer = useRef(null);

  useEffect(() => {
    if (!open || !signalId) return undefined;
    let cancelled = false;
    setLoading(true);
    setErr(null);
    api.signalAudit(signalId)
      .then((d) => { if (!cancelled) setAudit(d); })
      .catch((e) => { if (!cancelled) setErr(e.message || 'Audit unavailable'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [open, signalId]);

  useEffect(() => {
    if (!open) return undefined;
    const onDoc = (e) => {
      if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false);
    };
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const onEnter = () => {
    clearTimeout(hoverTimer.current);
    hoverTimer.current = setTimeout(() => setOpen(true), 180);
  };
  const onLeave = () => {
    clearTimeout(hoverTimer.current);
    hoverTimer.current = setTimeout(() => setOpen(false), 220);
  };

  const eq = audit?.equations || {};
  const lim = audit?.data_limitations;

  return (
    <span
      ref={rootRef}
      className={`relative inline-flex ${className}`}
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
    >
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="!p-0 h-auto min-h-0"
        aria-label={`Severity ${severity || 'unknown'} — open audit`}
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
      >
        <Badge kind="severity" value={severity} />
      </Button>

      {open && (
        <div
          role="dialog"
          aria-label="Severity parameter audit"
          className="absolute z-50 right-0 top-full mt-2 w-[min(22rem,calc(100vw-2rem))] rounded-xl border border-[var(--app-border)] bg-[var(--app-shell)] shadow-xl p-3 text-left"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="flex items-start justify-between gap-2 mb-2">
            <div>
              <div className="text-xs font-semibold text-[var(--app-text)]">Severity audit</div>
              <div className="text-[10px] text-[var(--app-text-muted)] mt-0.5 capitalize">
                {audit ? `${audit.product} → ${audit.event}` : `Signal #${signalId}`}
              </div>
            </div>
            <Badge kind="severity" value={severity} />
          </div>

          {loading && <Spinner label="Loading parameters…" />}
          {err && <div className="text-xs text-rose-300 py-2">{err}</div>}

          {!loading && audit && (
            <div className="space-y-2 max-h-[70vh] overflow-y-auto pr-0.5">
              <div className="text-[10px] text-[var(--app-text-muted)] leading-relaxed">
                {audit.severity?.method}
              </div>
              <div className="flex flex-wrap gap-1.5 text-[10px]">
                <Badge kind="strength" value={audit.strength} />
                {audit.sdr_flag && (
                  <Badge value="SDR" tone="err" />
                )}
                {audit.severity?.who_umc && (
                  <Badge kind="causality" value={audit.severity.who_umc} />
                )}
              </div>
              {audit.sdr_reasons?.length > 0 && (
                <ul className="text-[10px] text-rose-200/90 list-disc pl-4 space-y-0.5">
                  {audit.sdr_reasons.map((r) => <li key={r}>{r}</li>)}
                </ul>
              )}

              <div className="grid grid-cols-1 gap-2">
                <MetricBlock title="PRR" formula={eq.prr?.formula}>
                  <div>Observed: <span className="font-mono text-[var(--app-text)]">{eq.prr?.observed ?? '—'}</span>
                    {eq.prr?.ci95 && (
                      <span className="text-[var(--app-text-faint)]"> (95% CI {eq.prr.ci95[0]}–{eq.prr.ci95[1]})</span>
                    )}
                  </div>
                  <div>χ² Yates: <span className="font-mono">{eq.prr?.chi_square_yates ?? '—'}</span>
                    {' · '}n={eq.prr?.post_count ?? '—'} · E={eq.prr?.expected ?? '—'}
                  </div>
                  <div>Strong tier: <CheckCell check={eq.prr?.checks?.strong_tier} /></div>
                  <div>SDR CI: <CheckCell check={eq.prr?.checks?.sdr_ci_lower} /></div>
                </MetricBlock>

                <MetricBlock title="ROR" formula={eq.ror?.formula}>
                  <div>Observed: <span className="font-mono text-[var(--app-text)]">{eq.ror?.observed ?? '—'}</span>
                    {eq.ror?.ci95 && (
                      <span className="text-[var(--app-text-faint)]"> (95% CI {eq.ror.ci95[0]}–{eq.ror.ci95[1]})</span>
                    )}
                  </div>
                  <div>Elevated: <CheckCell check={eq.ror?.checks?.elevated} /></div>
                </MetricBlock>

                <MetricBlock title="IC₀₂₅ (BCPNN)" formula={eq.ic025?.formula}>
                  <div>IC: <span className="font-mono">{eq.ic025?.ic ?? '—'}</span>
                    {' · '}IC₀₂₅: <span className="font-mono text-[var(--app-text)]">{eq.ic025?.ic025 ?? '—'}</span>
                  </div>
                  <div>SDR (IC₀₂₅ &gt; 0): <CheckCell check={eq.ic025?.checks?.sdr} /></div>
                </MetricBlock>

                <MetricBlock title="EBGM / EB05 (MGPS)" formula={eq.ebgm?.formula}>
                  <div>EBGM: <span className="font-mono">{eq.ebgm?.ebgm ?? '—'}</span>
                    {' · '}EB05: <span className="font-mono text-[var(--app-text)]">{eq.ebgm?.eb05 ?? '—'}</span>
                  </div>
                  <div>SDR (EB05 ≥ 2): <CheckCell check={eq.ebgm?.checks?.sdr_eb05} /></div>
                </MetricBlock>
              </div>

              {lim && (
                <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-2.5">
                  <div className="text-[11px] font-semibold text-amber-200">{lim.title}</div>
                  <p className="text-[10px] text-amber-100/90 mt-1 leading-relaxed">{lim.summary}</p>
                  <p className="text-[9px] text-amber-200/70 mt-1.5 italic">{lim.disclaimer}</p>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </span>
  );
}
