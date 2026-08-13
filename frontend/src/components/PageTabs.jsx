import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Tabs, TabsList, TabsTrigger } from '@clairlabs-ai/prp-ui';

/** Horizontal tab strip for hub pages (one window, multiple related views). */
export function PageTabs({ tabs, active, onChange }) {
  return (
    <Tabs value={active} onValueChange={onChange}>
      <TabsList aria-label="Hub sections">
        {tabs.map((t) => (
          <TabsTrigger key={t.id} value={t.id}>
            {t.label}
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
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
