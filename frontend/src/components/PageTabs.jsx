import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';

/** Horizontal tab strip for hub pages (one window, multiple related views). */
export function PageTabs({ tabs, active, onChange }) {
  return (
    <div
      className="flex flex-wrap gap-1 p-1 rounded-xl border border-[var(--app-border)] bg-[var(--app-surface)]"
      role="tablist"
    >
      {tabs.map((t) => {
        const on = active === t.id;
        return (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={on}
            onClick={() => onChange(t.id)}
            className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
              on
                ? 'bg-teal-500/20 text-teal-200 border border-teal-500/40'
                : 'text-[var(--app-text-muted)] border border-transparent hover:text-[var(--app-text)] hover:bg-[var(--app-surface-hover)]'
            }`}
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
      <div className="min-w-0">
        <h2 className="text-lg font-semibold text-[var(--app-text)] break-words">{title}</h2>
        {subtitle && <p className="text-sm text-[var(--app-text-muted)] mt-1 break-words">{subtitle}</p>}
      </div>
      <PageTabs tabs={tabDefs} active={active} onChange={setTab} />
      <div className="hub-embed min-w-0 max-w-full">{typeof children === 'function' ? children(active) : children}</div>
    </div>
  );
}
