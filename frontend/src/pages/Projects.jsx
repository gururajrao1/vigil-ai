import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { useProject } from '../projectContext';
import { useRefresh } from '../App';
import { Button, Card, CardHeader } from '../components/ui';

const OWNER_BY_SLUG = {
  'general-pv': 'Gururaja',
  oncology: 'Bharat',
  vaccine: 'Shekhar',
  device: 'Gururaja',
};

/** Curated packs → Pathfinder / literature intent (see docs/VIGILAI_APPLICATION_HANDBOOK.md §11). */
const KEYWORD_PACKS = [
  {
    id: 'general',
    label: 'General PV',
    keywords: 'adverse reaction, side effect, drug safety, pharmacovigilance, patient forum, MedWatch',
  },
  {
    id: 'anticoagulant',
    label: 'Anticoagulants',
    keywords: 'warfarin, rivaroxaban, apixaban, haemorrhage, bleeding, anticoagulant, INR',
  },
  {
    id: 'psych',
    label: 'Psychiatry',
    keywords: 'paroxetine, sertraline, lithium, suicidal ideation, akathisia, SSRI, bipolar forum',
  },
  {
    id: 'glp1',
    label: 'GLP-1 / metabolic',
    keywords: 'semaglutide, Ozempic, Wegovy, pancreatitis, gastroparesis, nausea, weight loss drug',
  },
  {
    id: 'oncology',
    label: 'Oncology / ICI',
    keywords: 'pembrolizumab, nivolumab, checkpoint inhibitor, immune-related AE, colitis, pneumonitis, oncology forum',
  },
  {
    id: 'pregnancy',
    label: 'Pregnancy',
    keywords: 'pregnancy, congenital anomaly, birth defect, teratogen, lithium pregnancy, valproate, neural tube defect',
  },
  {
    id: 'vaccine',
    label: 'Vaccine / AESI',
    keywords: 'myocarditis, vaccine side effects, reactogenicity, MMR, COVID-19 vaccine, VAERS, immunization',
  },
  {
    id: 'device-cardiac',
    label: 'Devices · cardiac',
    keywords: 'pacemaker, coronary stent, defibrillator, lead fracture, device malfunction, MAUDE, implant forum',
  },
  {
    id: 'device-diabetes',
    label: 'Devices · diabetes',
    keywords: 'insulin pump, continuous glucose monitor, CGM, overinfusion, sensor error, infusion set, diabetes device',
  },
  {
    id: 'ddi',
    label: 'DDI / polypharmacy',
    keywords: 'polypharmacy, drug interaction, warfarin amiodarone, serotonin syndrome, concomitant medication',
  },
];

function ownerFor(p) {
  return OWNER_BY_SLUG[p.slug] || OWNER_BY_SLUG[p.therapeutic_area] || 'VigilAI Ops';
}

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
      <div className="va-mint-rule">
        <h2 className="page-title">Projects</h2>
        <p className="page-subtitle">
          Case portfolio of surveillance campaigns — owners beside structural target tags.
        </p>
      </div>

      <Card className="p-4">
        <CardHeader title="How to use projects" subtitle="End-to-end campaign workflow" />
        <ol className="mt-3 space-y-2 text-sm text-[var(--app-text-secondary)] list-decimal list-inside">
          <li>Select a workspace in the header (or click one below).</li>
          <li>If it shows 0 posts, click <strong>Fill workspace</strong> (or Demo corpus / Fetch while it is active).</li>
          <li>Optional: <Link to="/source-queue" className="text-[var(--app-accent-sky)]">Source Discovery</Link> → Run Pathfinder → Approve sources.</li>
          <li>Open <Link to="/graph" className="text-[var(--app-accent-sky)]">Evidence Explorer</Link>, Signals, and Lenses for this project&apos;s corpus.</li>
        </ol>
      </Card>

      {project && (
        <Card className="p-4">
          <div className="mono-tag">ACTIVE CASE</div>
          <div className="text-xl font-extrabold text-[var(--app-text)] mt-2" style={{ letterSpacing: '-0.04em' }}>
            {project.name}
          </div>
          <div className="text-sm text-[var(--app-text-secondary)] mt-1">{project.description}</div>
          <div className="flex flex-wrap gap-3 mt-3 text-xs font-mono text-[var(--app-text-muted)]">
            <span>owner · {ownerFor(project)}</span>
            <span>{project.post_count ?? 0} posts</span>
            <span>{project.signal_count ?? 0} signals</span>
            <span className="capitalize">{project.therapeutic_area}</span>
          </div>
          <div className="flex flex-wrap gap-2 mt-3">
            {project.keywords?.map((k) => (
              <span
                key={k}
                className="text-[10px] px-2 py-0.5 font-mono border border-[var(--app-border)] text-[var(--app-accent)]"
                style={{ borderRadius: 4 }}
              >
                {k}
              </span>
            ))}
          </div>
        </Card>
      )}

      <Card className="p-4">
        <CardHeader title="Case portfolio" subtitle="Click to switch · Fill empty specialty campaigns" />
        <div className="space-y-2 mt-3">
          {projects.map((p) => {
            const empty = !(p.post_count > 0);
            return (
              <div
                key={p.id}
                className={`border px-4 py-3 ${
                  project?.id === p.id
                    ? 'border-[var(--app-accent)] bg-[var(--app-accent-muted)]'
                    : 'border-[var(--app-border)]'
                }`}
                style={{ borderRadius: 4 }}
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <Button type="button" variant="ghost" onClick={() => setActiveProject(p)} className="justify-start text-left h-auto min-w-0">
                    <div className="min-w-0">
                      <div className="font-bold text-[var(--app-text)]" style={{ letterSpacing: '-0.03em' }}>
                        {p.name}
                      </div>
                      <div className="text-[10px] font-mono text-[var(--app-text-muted)] mt-1 tracking-wide">
                        OWNER · {ownerFor(p).toUpperCase()}
                      </div>
                      <div className="text-xs text-[var(--app-text-muted)] mt-1">
                        {p.therapeutic_area} · {p.slug} · {p.post_count ?? 0} posts · {p.signal_count ?? 0} signals
                        {empty && <span className="text-[var(--app-accent-sky)]"> · empty</span>}
                      </div>
                    </div>
                  </Button>
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
        {msg && <p className="text-xs text-[var(--app-text-muted)] mt-3 font-mono">{msg}</p>}
      </Card>

      <Card className="p-4">
        <CardHeader title="Create workspace" />
        <div className="grid gap-3 mt-3 sm:grid-cols-2">
          <input placeholder="Name" value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            aria-label="Project name" />
          <input placeholder="slug-kebab-case" value={form.slug}
            onChange={(e) => setForm({ ...form, slug: e.target.value })}
            aria-label="Project slug" />
          <select value={form.therapeutic_area}
            onChange={(e) => setForm({ ...form, therapeutic_area: e.target.value })}
            aria-label="Therapeutic area">
            <option value="general">general</option>
            <option value="oncology">oncology</option>
            <option value="vaccine">vaccine</option>
            <option value="device">device</option>
          </select>
          <div className="sm:col-span-2 space-y-2">
            <input
              className="w-full"
              placeholder="keywords, comma-separated — drive Pathfinder + literature retrieval"
              value={form.keywords}
              onChange={(e) => setForm({ ...form, keywords: e.target.value })}
              aria-label="Project keywords"
            />
            <p className="text-[11px] text-[var(--app-text-muted)] leading-relaxed">
              Keywords are the workspace intent vocabulary (3–8 terms). Pathfinder searches
              patient forums with them; literature crawls narrow the same way. Pick a pack
              below or type your own — then Run Pathfinder from Source Discovery.
            </p>
            <div className="flex flex-wrap gap-1.5">
              {KEYWORD_PACKS.map((pack) => (
                <Button
                  key={pack.id}
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => setForm((f) => ({
                    ...f,
                    keywords: pack.keywords,
                    therapeutic_area:
                      pack.id.startsWith('device') ? 'device'
                        : pack.id === 'oncology' ? 'oncology'
                          : pack.id === 'vaccine' ? 'vaccine'
                            : f.therapeutic_area,
                  }))}
                  title={pack.keywords}
                >
                  {pack.label}
                </Button>
              ))}
            </div>
          </div>
        </div>
        <div className="mt-4 flex items-center gap-3">
          <Button onClick={create} disabled={busy}>{busy ? 'Creating…' : 'Create project'}</Button>
        </div>
      </Card>
    </div>
  );
}
