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
  const [actionMsg, setActionMsg] = useState('');

  const [capabilities, setCapabilities] = useState(null);

  const load = async () => {
    if (!project?.id) return;
    setLoading(true);
    try {
      const [s, r] = await Promise.all([
        api.suggestedSources(project.id),
        api.pathfinderRuns(project.id),
      ]);
      setSources(s);
      setRuns(r);
    } catch {
      setSources([]);
      setRuns([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [project?.id, tick]);

  useEffect(() => {
    api.pipelineCapabilities().then(setCapabilities).catch(() => setCapabilities(null));
  }, []);

  const runPathfinder = async () => {
    if (!project?.id) return;
    setDiscovering(true);
    setActionMsg('');
    try {
      await api.pathfinderRun(project.id, true);
      setActionMsg('Discovery complete — review suggested sources below. Metrics update only after Approve & Onboard (each source usually adds a few posts).');
      bump();
      await load();
    } catch (e) {
      setActionMsg(e.message);
    } finally {
      setDiscovering(false);
    }
  };

  const approve = async (id, needsLogin) => {
    setActionMsg('');
    try {
      const profile = needsLogin ? 'cookies' : null;
      const res = await api.approveSource(project.id, id, profile);
      if (res.ok) {
        setActionMsg(
          `Onboarded (+${res.ingested} posts`
          + (res.signals != null ? ` · ${res.signals} signals` : '')
          + ') — same pipeline as Fetch: Live Feed + Safety Signals updated.'
        );
        recordIngest({
          source: 'pathfinder',
          ingested: res.ingested || 0,
          signals: res.signals,
          alerts: res.alerts,
          url: res.url,
        });
      } else {
        setActionMsg(res.error);
      }
      await load();
    } catch (e) {
      setActionMsg(e.message);
    }
  };

  const reject = async (id) => {
    await api.rejectSource(project.id, id);
    bump();
    await load();
  };

  if (!project) return <Spinner label="Loading project workspace…" />;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        {!embedded ? (
          <div>
            <h2 className="text-lg font-semibold text-[var(--app-text)]">Suggested Source Queue</h2>
            <p className="text-sm text-[var(--app-text-muted)] mt-1">
              Pathfinder discoveries for <strong>{project.name}</strong>. Approve sources before they enter live analytics.
              Login-walled rows reuse your saved browser session cookies — we do not crack CAPTCHAs.
            </p>
          </div>
        ) : (
          <p className="text-sm text-[var(--app-text-muted)]">
            Pathfinder discoveries for <strong>{project.name}</strong>. Approve before live analytics.
          </p>
        )}
        <div className="flex gap-2">
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

      <Card className="p-3 text-[11px] text-[var(--app-text-muted)] leading-relaxed">
        <strong className="text-[var(--app-text-secondary)]">Login-walled onboard:</strong>{' '}
        Install Playwright, then capture a session you already own:{' '}
        <code className="text-teal-400">playwright codegen --save-storage=project_vault/cookies.json &lt;url&gt;</code>
        {' '}— then Approve &amp; Onboard. Public pages scrape without cookies.
      </Card>

      {capabilities && (
        <div className="flex flex-wrap gap-2 text-[11px]">
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
        </div>
      )}

      {actionMsg && (
        <div className="text-sm rounded-lg border border-[var(--app-border)] px-4 py-2 text-[var(--app-text-secondary)]">
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
              <div key={r.id} className="flex gap-3">
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
          {sources.length === 0 && (
            <p className="text-sm text-[var(--app-text-muted)]">Queue empty — run Pathfinder to discover communities.</p>
          )}
          {sources.map((s) => (
            <Card key={s.id} className="p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span>{s.access_emoji} {s.access_label || (s.access_status === 'login_required' ? 'Requires Login' : 'Public')}</span>
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
                    </div>
                  )}
                </div>
                {s.approval_status === 'pending' && (
                  <div className="flex gap-2 shrink-0">
                    <Button onClick={() => approve(s.id, s.access_status === 'login_required')}>
                      Approve & Onboard
                    </Button>
                    <button type="button" onClick={() => reject(s.id)}
                      className="text-xs text-rose-400 px-2">Reject</button>
                  </div>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
