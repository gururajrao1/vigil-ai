import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { useProject } from '../projectContext';
import { useRefresh } from '../App';
import { Button, Card, CardHeader } from '../components/ui';

export default function Projects() {
  const { project, projects, setActiveProject, reload } = useProject();
  const { bump } = useRefresh();
  const [form, setForm] = useState({ name: '', slug: '', therapeutic_area: 'general', keywords: '' });
  const [busy, setBusy] = useState(false);
  const [fillingId, setFillingId] = useState(null);
  const [msg, setMsg] = useState('');

  const create = async () => {
    if (!form.name || !form.slug) return;
    setBusy(true);
    setMsg('');
    try {
      const keywords = form.keywords.split(',').map((k) => k.trim()).filter(Boolean);
      await api.createProject({ ...form, keywords });
      setForm({ name: '', slug: '', therapeutic_area: 'general', keywords: '' });
      await reload();
      setMsg('Workspace created.');
    } catch (e) {
      setMsg(e.message);
    } finally {
      setBusy(false);
    }
  };

  const fill = async (p) => {
    setFillingId(p.id);
    setMsg('');
    try {
      const res = await api.seedProject(p.id);
      await reload();
      bump();
      setMsg(`Filled ${p.name}: +${res.ingested} posts · ${res.signal_count ?? res.signals ?? 0} signals.`);
      setActiveProject({ ...p, post_count: res.post_count, signal_count: res.signal_count });
    } catch (e) {
      setMsg(e.message);
    } finally {
      setFillingId(null);
    }
  };

  return (
    <div className="space-y-6 max-w-4xl">
      <div>
        <h2 className="text-lg font-semibold text-[var(--app-text)]">Project Workspaces</h2>
        <p className="text-sm text-[var(--app-text-muted)] mt-1">
          Each project is a separate surveillance campaign. The header dropdown switches which
          workspace Fetch, Demo corpus, Pathfinder, Source Queue, Divergence, and Knowledge Graph use.
        </p>
      </div>

      <Card className="p-4 border-teal-500/25 bg-teal-500/5">
        <CardHeader title="How to use projects" subtitle="End-to-end campaign workflow" />
        <ol className="mt-3 space-y-2 text-sm text-[var(--app-text-secondary)] list-decimal list-inside">
          <li>Select a workspace in the header (or click one below).</li>
          <li>If it shows 0 posts, click <strong>Fill workspace</strong> (or Demo corpus / Fetch while it is active).</li>
          <li>Optional: <Link to="/source-queue" className="text-teal-400">Source Queue</Link> → Run Pathfinder → Approve sources for live discovery.</li>
          <li>Open <Link to="/graph" className="text-teal-400">Knowledge Graph</Link>, Signals, and Divergence — they reflect this project’s data.</li>
        </ol>
      </Card>

      {project && (
        <Card className="p-4 border-teal-500/30">
          <div className="text-xs text-[var(--app-text-muted)]">Active workspace</div>
          <div className="text-xl font-semibold text-[var(--app-text)]">{project.name}</div>
          <div className="text-sm text-[var(--app-text-secondary)] mt-1">{project.description}</div>
          <div className="flex flex-wrap gap-3 mt-3 text-xs text-[var(--app-text-muted)]">
            <span>{project.post_count ?? 0} posts</span>
            <span>{project.signal_count ?? 0} signals</span>
            <span className="capitalize">{project.therapeutic_area}</span>
          </div>
          <div className="flex flex-wrap gap-2 mt-3">
            {project.keywords?.map((k) => (
              <span key={k} className="text-xs px-2 py-0.5 rounded bg-teal-500/10 text-teal-300">{k}</span>
            ))}
          </div>
        </Card>
      )}

      <Card className="p-4">
        <CardHeader title="All workspaces" subtitle="Click to switch · Fill empty specialty campaigns" />
        <div className="space-y-2 mt-3">
          {projects.map((p) => {
            const empty = !(p.post_count > 0);
            return (
              <div
                key={p.id}
                className={`rounded-lg border px-4 py-3 transition ${
                  project?.id === p.id
                    ? 'border-teal-500/50 bg-teal-500/10'
                    : 'border-[var(--app-border)]'
                }`}
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <button type="button" onClick={() => setActiveProject(p)} className="text-left min-w-0">
                    <div className="font-medium text-[var(--app-text)]">{p.name}</div>
                    <div className="text-xs text-[var(--app-text-muted)]">
                      {p.therapeutic_area} · {p.slug} · {p.post_count ?? 0} posts · {p.signal_count ?? 0} signals
                      {empty && <span className="text-amber-400"> · empty</span>}
                    </div>
                  </button>
                  <Button
                    onClick={() => fill(p)}
                    disabled={fillingId === p.id}
                    variant={empty ? undefined : 'ghost'}
                  >
                    {fillingId === p.id ? 'Filling…' : empty ? 'Fill workspace' : 'Re-fill corpus'}
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
        {msg && <p className="text-xs text-[var(--app-text-muted)] mt-3">{msg}</p>}
      </Card>

      <Card className="p-4">
        <CardHeader title="Create workspace" />
        <div className="grid gap-3 mt-3 sm:grid-cols-2">
          <input className="app-input" placeholder="Name" value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <input className="app-input" placeholder="slug-kebab-case" value={form.slug}
            onChange={(e) => setForm({ ...form, slug: e.target.value })} />
          <select className="app-input" value={form.therapeutic_area}
            onChange={(e) => setForm({ ...form, therapeutic_area: e.target.value })}>
            <option value="general">general</option>
            <option value="oncology">oncology</option>
            <option value="vaccine">vaccine</option>
            <option value="device">device</option>
          </select>
          <input className="app-input sm:col-span-2" placeholder="keywords, comma-separated"
            value={form.keywords} onChange={(e) => setForm({ ...form, keywords: e.target.value })} />
        </div>
        <div className="mt-4 flex items-center gap-3">
          <Button onClick={create} disabled={busy}>{busy ? 'Creating…' : 'Create project'}</Button>
        </div>
      </Card>
    </div>
  );
}
