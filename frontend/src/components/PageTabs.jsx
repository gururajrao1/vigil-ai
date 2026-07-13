import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';

/** Horizontal tab strip for hub pages (one window, multiple related views). */
export function PageTabs({ tabs, active, onChange }) {
  return (
    <div
      className="flex flex-wrap gap-0 border border-[var(--app-border)] bg-[var(--app-surface)]"
      role="tablist"
      style={{ borderRadius: 4 }}
    >
      {tabs.map((t, i) => {
        const on = active === t.id;
        return (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={on}
            onClick={() => onChange(t.id)}
            className={`px-3 py-2 text-xs font-semibold border-r border-[var(--app-border)] last:border-r-0 ${
              on
                ? 'text-[var(--app-accent)] bg-[var(--app-accent-muted)]'
                : 'text-[var(--app-text-muted)] hover:text-[var(--app-text)] hover:bg-[var(--app-surface-hover)]'
            }`}
            style={{
              letterSpacing: '-0.02em',
              borderBottom: on ? '2px solid var(--app-accent)' : '2px solid transparent',
            }}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}

/** Sync active tab with `?tab=` so deep links / redirects keep working. */
export function useHubTab(defaultId, validIds) {
  const [params, setParams] = useSearchParams();
  const raw = params.get('tab') || defaultId;
  const active = validIds.includes(raw) ? raw : defaultId;

  const setTab = useCallback(
    (id) => {
      const next = new URLSearchParams(params);
      if (id === defaultId) next.delete('tab');
      else next.set('tab', id);
      setParams(next, { replace: true });
    },
    [params, setParams, defaultId],
  );

  const tabs = useMemo(() => validIds, [validIds]);
  return [active, setTab, tabs];
}

export function HubShell({ title, subtitle, tabDefs, defaultTab, children }) {
  const ids = tabDefs.map((t) => t.id);
  const [active, setTab] = useHubTab(defaultTab || ids[0], ids);
  return (
    <div className="space-y-4 min-w-0 max-w-full">
      <div className="min-w-0 va-mint-rule">
        <h2 className="page-title break-words">{title}</h2>
        {subtitle && <p className="page-subtitle break-words">{subtitle}</p>}
      </div>
      <PageTabs tabs={tabDefs} active={active} onChange={setTab} />
      <div className="hub-embed min-w-0 max-w-full">{typeof children === 'function' ? children(active) : children}</div>
    </div>
  );
}
