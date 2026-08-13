import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { useProject } from '../projectContext';
import { useRefresh } from '../App';
import { Button, Card, CardHeader, Spinner } from '../components/ui';

export default function SourceQueue({ embedded = false }) {
  const { project } = useProject();
  const { tick, bump, recordIngest } = useRefresh();
  const [sources, setSources] = useState([]);
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [discovering, setDiscovering] = useState(false);
  const [busyId, setBusyId] = useState(null);
  const [actionMsg, setActionMsg] = useState('');
  const [hidePaywalled, setHidePaywalled] = useState(true);
  const [capabilities, setCapabilities] = useState(null);

  /** Soft refresh keeps the list mounted — no full-tab spinner flash. */
  const load = async ({ soft = false } = {}) => {
    if (!project?.id) return;
    if (!soft) setLoading(true);
    try {
      const [s, r] = await Promise.all([
        api.suggestedSources(project.id),
        api.pathfinderRuns(project.id),
      ]);
      setSources(s);
      setRuns(r);
    } catch {
      if (!soft) {
        setSources([]);
        setRuns([]);
      }
    } finally {
      if (!soft) setLoading(false);
    }
  };

  useEffect(() => { load(); }, [project?.id]);

  // Global ingest tick from other hubs — soft sync only
  useEffect(() => {
    if (!project?.id || tick === 0) return;
    load({ soft: true });
  }, [tick]);

  useEffect(() => {
    api.pipelineCapabilities().then(setCapabilities).catch(() => setCapabilities(null));
  }, []);

  const runPathfinder = async () => {
    if (!project?.id) return;
    setDiscovering(true);
    setActionMsg('');
    try {
      await api.pathfinderRun(project.id, true);
      setActionMsg(
        'Discovery complete — open/public sources are ready to Approve. '
        + 'Known paywalls (Medscape, etc.) are auto-skipped; use Data Sources → PubMed / FAERS for literature.'
      );
      await load({ soft: true });
      // Soft bump so Dashboard counts update without remounting this queue as a spinner
      bump();
    } catch (e) {
      setActionMsg(e.message);
    } finally {
      setDiscovering(false);
    }
  };

  const approve = async (id, needsLogin) => {
    setActionMsg('');
    setBusyId(id);
    try {
      const profile = needsLogin ? 'cookies' : null;
      const res = await api.approveSource(project.id, id, profile);
      if (res.ok) {
        setActionMsg(
          `Onboarded (+${res.ingested} posts`
          + (res.signals != null ? ` · ${res.signals} signals` : '')
          + ') — Live Feed + Safety Signals updated.'
        );
        // Patch row in place so the list does not flash
        setSources((prev) => prev.map((s) => (
          s.id === id ? { ...s, approval_status: 'approved' } : s
        )));
        recordIngest({
          source: 'pathfinder',
          ingested: res.ingested || 0,
          signals: res.signals,
          alerts: res.alerts,
          url: res.url,
        });
      } else {
        setActionMsg(res.error);
        // Revert ingesting → pending without full remount
        setSources((prev) => prev.map((s) => (
          s.id === id && s.approval_status === 'ingesting'
            ? { ...s, approval_status: 'pending' }
            : s
        )));
      }
      await load({ soft: true });
    } catch (e) {
      setActionMsg(e.message);
    } finally {
      setBusyId(null);
    }
  };

  const reject = async (id) => {
    setBusyId(id);
    setActionMsg('');
    try {
      await api.rejectSource(project.id, id);
      setSources((prev) => prev.map((s) => (
        s.id === id ? { ...s, approval_status: 'rejected' } : s
      )));
      setActionMsg('Source skipped.');
    } catch (e) {
      setActionMsg(e.message);
    } finally {
      setBusyId(null);
    }
  };

  const visible = sources.filter((s) => {
    if (!hidePaywalled) return true;
    if (s.access_status === 'login_required') return s.approval_status === 'pending';
    return true;
  });
  // Pending public first, then pending login, then history
  const sorted = [...visible].sort((a, b) => {
    const rank = (s) => {
      if (s.approval_status === 'pending' && s.access_status !== 'login_required') return 0;
      if (s.approval_status === 'pending') return 1;
      if (s.approval_status === 'approved') return 2;
      return 3;
    };
    return rank(a) - rank(b);
  });

  if (!project) return <Spinner label="Loading project workspace…" />;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        {!embedded ? (
          <div>
            <h2 className="text-lg font-semibold text-[var(--app-text)]">Suggested Source Queue</h2>
            <p className="text-sm text-[var(--app-text-muted)] mt-1">
              Pathfinder discoveries for <strong>{project.name}</strong>. Approve <em>open</em> sources
              before they enter live analytics. We do not crack CAPTCHAs or HCP paywalls.
            </p>
          </div>
        ) : (
          <p className="text-sm text-[var(--app-text-muted)]">
            Pathfinder discoveries for <strong>{project.name}</strong>. Prefer open sources.
          </p>
        )}
        <div className="flex gap-2 flex-wrap">
          <Button onClick={runPathfinder} disabled={discovering}>
            {discovering ? 'Discovering…' : 'Run Pathfinder'}
          </Button>
          {!embedded && (
            <Link
              to="/source-queue?tab=manual"
              className="text-xs self-center rounded-lg px-3 py-2 border border-[var(--app-border)] text-teal-400 hover:bg-teal-500/10"
            >
              Manual forum URL
            </Link>
          )}
          <Link to="/projects" className="text-xs text-teal-400 self-center">Switch project</Link>
        </div>
      </div>

      <Card className="p-3 text-[11px] text-[var(--app-text-muted)] leading-relaxed space-y-1">
        <div>
          <strong className="text-[var(--app-text-secondary)]">Paywalls (Medscape, UpToDate, …):</strong>{' '}
          auto-skipped — use <Link to="/sources" className="text-teal-400">Data Sources</Link>
          {' '}→ PubMed / Europe PMC / FAERS / VAERS / news RSS instead. Those are open and already wired.
        </div>
        <div>
          <strong className="text-[var(--app-text-secondary)]">Login-walled forums you own access to:</strong>{' '}
          capture your session with{' '}
          <code className="text-teal-400">playwright codegen --save-storage=project_vault/cookies.json &lt;url&gt;</code>
          {' '}then Onboard with cookies. We never store your password.
        </div>
      </Card>

      {capabilities && (
        <div className="flex flex-wrap gap-2 text-[11px] items-center">
          <span className="rounded px-2 py-0.5 border border-[var(--app-border)] text-[var(--app-text-muted)]">
            Pathfinder: {capabilities.pathfinder?.fallback}
          </span>
          <span className="rounded px-2 py-0.5 border border-[var(--app-border)] text-[var(--app-text-muted)]">
            Crawl: {capabilities.source_crawl?.fallback}
          </span>
          {!capabilities.pathfinder?.exa && !capabilities.pathfinder?.tavily && (
            <span className="rounded px-2 py-0.5 bg-teal-500/10 text-teal-300 border border-teal-500/30">
              No Exa/Tavily keys — offline seeds active
            </span>
          )}
          <label className="ml-auto flex items-center gap-1.5 text-[var(--app-text-muted)] cursor-pointer">
            <input
              type="checkbox"
              checked={hidePaywalled}
              onChange={(e) => setHidePaywalled(e.target.checked)}
              className="rounded border-slate-600"
            />
            Hide skipped paywalls
          </label>
        </div>
      )}

      {actionMsg && (
        <div className="text-sm rounded-lg border border-[var(--app-border)] px-4 py-2 text-[var(--app-text-secondary)] whitespace-pre-wrap">
          {actionMsg}
        </div>
      )}

      <Card className="p-4">
        <CardHeader title="Recent discovery runs" />
        {runs.length === 0 ? (
          <p className="text-sm text-[var(--app-text-muted)] mt-2">No pathfinder runs yet.</p>
        ) : (
          <div className="mt-2 space-y-1 text-xs text-[var(--app-text-secondary)]">
            {runs.slice(0, 5).map((r) => (
              <div key={r.id} className="flex gap-3 flex-wrap">
                <span className="text-[var(--app-text-faint)]">{r.started_at?.slice(0, 16)}</span>
                <span className={r.provider === 'offline' ? 'text-teal-400' : ''}>{r.provider}</span>
                <span>{r.status}</span>
                <span>{r.urls_discovered} URLs</span>
              </div>
            ))}
          </div>
        )}
      </Card>

      {loading ? <Spinner label="Loading queue…" /> : (
        <div className="space-y-3">
          {sorted.length === 0 && (
            <p className="text-sm text-[var(--app-text-muted)]">
              Queue empty — run Pathfinder to discover communities, or uncheck “Hide skipped paywalls”.
            </p>
          )}
          {sorted.map((s) => {
            const paywalled = s.access_status === 'login_required';
            const pending = s.approval_status === 'pending';
            const busy = busyId === s.id;
            return (
              <Card key={s.id} className={`p-4 ${paywalled ? 'opacity-90 border-amber-700/30' : ''}`}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span>
                        {s.access_emoji}{' '}
                        {s.access_label || (paywalled ? 'Requires Login' : 'Public')}
                      </span>
                      <span className="font-medium text-[var(--app-text)] truncate">{s.title || s.domain}</span>
                      <span className="text-xs text-[var(--app-text-faint)]">{s.approval_status}</span>
                    </div>
                    <a href={s.url} target="_blank" rel="noreferrer"
                      className="text-xs text-teal-400 break-all">{s.url}</a>
                    {s.access_reason && (
                      <div className="text-[10px] text-[var(--app-text-muted)] mt-1">{s.access_reason}</div>
                    )}
                    {s.access_flags?.length > 0 && (
                      <div className="text-[10px] text-amber-400/80 mt-1">
                        Auth friction: {s.access_flags.join(', ')}
                        {s.access_flags.includes('known_paywall') && (
                          <span> — skipped; use PubMed / FAERS instead</span>
                        )}
                      </div>
                    )}
                  </div>
                  {pending && (
                    <div className="flex gap-2 shrink-0 flex-wrap justify-end">
                      {!paywalled ? (
                        <>
                          <Button disabled={busy} onClick={() => approve(s.id, false)}>
                            {busy ? 'Onboarding…' : 'Approve & Onboard'}
                          </Button>
                          <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => reject(s.id)}>
                            Skip
                          </Button>
                        </>
                      ) : (
                        <>
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            disabled={busy}
                            onClick={() => reject(s.id)}
                          >
                            {busy ? '…' : 'Skip paywall'}
                          </Button>
                          <Button
                            variant="ghost"
                            disabled={busy}
                            onClick={() => approve(s.id, true)}
                            title="Only works if project_vault/cookies.json has your logged-in session"
                          >
                            {busy ? 'Trying…' : 'Onboard with cookies'}
                          </Button>
                        </>
                      )}
                    </div>
                  )}
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
