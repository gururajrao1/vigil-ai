import { useEffect, useState, useRef, createContext, useContext, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { api, setToken, getToken, wakeApi } from './api';
import { Button } from './components/ui';
import { ThemeProvider, ThemeToggle } from './theme';
import Dashboard from './pages/Dashboard';
import SignalWorkbench from './pages/SignalWorkbench';
import SignalDetail from './pages/SignalDetail';
import Evidence from './pages/Evidence';
import Lenses from './pages/Lenses';
import SourcesHub from './pages/SourcesHub';
import DiscoveryHub from './pages/DiscoveryHub';
import Forge from './pages/Forge';
import Projects from './pages/Projects';
import UsersAdmin from './pages/UsersAdmin';
import Login from './pages/Login';
import BiotechHomepagePage from './biotech/BiotechHomepagePage';
import { ProjectProvider, ProjectSelector } from './projectContext';
import { hasMinRole, isAdmin, isAnalyst } from './roles';

export const RefreshContext = createContext({
  tick: 0,
  bump: () => {},
  lastIngest: null,
  recordIngest: () => {},
});
export const useRefresh = () => useContext(RefreshContext);

// ⌘K — hubs + legacy deep-links (old paths redirect into hub tabs)
const CMD_ITEMS = [
  { label: 'Biotech homepage', icon: '◈', path: '/' },
  { label: 'Dashboard · corpus metrics', icon: '📊', path: '/dashboard' },
  { label: 'Dashboard · ops KPIs', icon: '📈', path: '/dashboard?tab=ops' },
  { label: 'Safety Signals · detect', icon: '🚨', path: '/signals' },
  { label: 'Safety Signals · workflow', icon: '📋', path: '/signals?tab=lifecycle' },
  { label: 'Safety Signals · alert inbox', icon: '🔔', path: '/signals?tab=alerts' },
  { label: 'Analytic Lenses', icon: '◈', path: '/lenses' },
  { label: 'Lenses · SMQ', icon: '◈', path: '/lenses?tab=smq' },
  { label: 'Lenses · class effects', icon: '⚗', path: '/lenses?tab=class' },
  { label: 'Lenses · DDI pairs', icon: '⚗', path: '/lenses?tab=ddi' },
  { label: 'Lenses · pregnancy', icon: '🤰', path: '/lenses?tab=pregnancy' },
  { label: 'Lenses · vaccine', icon: '💉', path: '/lenses?tab=vaccine' },
  { label: 'Lenses · geo clusters', icon: '📍', path: '/lenses?tab=spatial' },
  { label: 'Lenses · vs FAERS', icon: '📉', path: '/lenses?tab=divergence' },
  { label: 'Evidence · drug ↔ AE graph', icon: '🕸', path: '/graph' },
  { label: 'Evidence · compare story', icon: '📖', path: '/graph?tab=story' },
  { label: 'Projects', icon: '📁', path: '/projects' },
  { label: 'Source Discovery', icon: '🔗', path: '/source-queue' },
  { label: 'Source Discovery · manual URL', icon: '🔍', path: '/source-queue?tab=manual' },
  { label: 'Data Sources · catalog', icon: '🌐', path: '/sources' },
  { label: 'Data Sources · live stream', icon: '📡', path: '/sources?tab=live' },
  { label: 'Data Sources · networks', icon: '🛰', path: '/sources?tab=networks' },
  { label: 'Data Sources · agent chat', icon: '🎛', path: '/sources?tab=agent' },
  { label: 'Data Forge (Synthetic)', icon: '⚗', path: '/forge', minRole: 'analyst' },
  { label: 'Admin · Users', icon: '👤', path: '/users', minRole: 'admin' },
];

function CommandPalette({ onClose }) {
  const { user } = useAuth();
  const [q, setQ] = useState('');
  const nav = useNavigate();
  const inputRef = useRef(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  const allowed = CMD_ITEMS.filter((i) => !i.minRole || hasMinRole(user, i.minRole));
  const filtered = q.trim()
    ? allowed.filter((i) => i.label.toLowerCase().includes(q.toLowerCase()))
    : allowed;

  const go = (path) => { nav(path); onClose(); };

  return createPortal(
    <div className="fixed inset-0 z-[99999] flex items-start justify-center pt-24 px-4"
         style={{ background: 'var(--app-overlay)', backdropFilter: 'blur(4px)' }}
         onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="w-full max-w-lg border border-[var(--app-border)] bg-[var(--app-surface-solid)] overflow-hidden" style={{ borderRadius: 4 }}>
        <div className="flex items-center gap-2 px-4 py-3 border-b border-[var(--app-border)]">
          <span className="text-[var(--app-text-muted)] text-sm">⌘</span>
          <input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') onClose();
              if (e.key === 'Enter' && filtered.length > 0) go(filtered[0].path);
            }}
            placeholder="Go to page… (type to filter)"
            className="flex-1 bg-transparent text-[var(--app-text)] text-sm outline-none placeholder:text-[var(--app-text-faint)]" />
          <kbd className="text-[10px] text-[var(--app-text-faint)] border border-[var(--app-border)] rounded px-1">ESC</kbd>
        </div>
        <div className="max-h-80 overflow-y-auto py-1">
          {filtered.length === 0 && (
            <div className="px-4 py-3 text-xs text-[var(--app-text-muted)]">No pages match "{q}"</div>
          )}
          {filtered.map((item) => (
            <button key={item.path} type="button" onClick={() => go(item.path)}
              className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-[var(--app-text-secondary)] hover:bg-[var(--app-surface-hover)] transition-colors text-left">
              <span className="text-base">{item.icon}</span>
              {item.label}
              <span className="ml-auto text-[10px] font-mono text-[var(--app-text-faint)]">{item.path}</span>
            </button>
          ))}
        </div>
        <div className="px-4 py-2 border-t border-[var(--app-border)] flex items-center gap-4 text-[10px] text-[var(--app-text-faint)]">
          <span>↵ open</span><span>↑↓ navigate</span><span>ESC close</span>
          <span className="ml-auto">Press <kbd className="border border-slate-700 rounded px-1">⌘K</kbd> / <kbd className="border border-slate-700 rounded px-1">Ctrl+K</kbd> to toggle</span>
        </div>
      </div>
    </div>,
    document.body
  );
}

export const AuthContext = createContext({ user: null, login: () => {}, logout: () => {} });
export const useAuth = () => useContext(AuthContext);

/** One sidebar item per feature family — related views live as tabs inside. */
const NAV_SECTIONS = [
  {
    title: 'Core',
    items: [
      { to: '/', label: 'Homepage', icon: '◈', end: true },
      { to: '/dashboard', label: 'Dashboard', icon: '◧' },
      { to: '/signals', label: 'Safety Signals', icon: '⚠' },
      { to: '/lenses', label: 'Analytic Lenses', icon: '◈' },
      { to: '/graph', label: 'Evidence Explorer', icon: '⬡' },
    ],
  },
  {
    title: 'Workspace',
    items: [
      { to: '/projects', label: 'Projects', icon: '📁', minRole: 'analyst' },
      { to: '/source-queue', label: 'Source Discovery', icon: '🔗', minRole: 'analyst' },
      { to: '/sources', label: 'Data Sources', icon: '⛓' },
      { to: '/forge', label: 'Data Forge', icon: '⚗', minRole: 'analyst' },
      { to: '/users', label: 'Users', icon: '👤', minRole: 'admin' },
    ],
  },
];

function Sidebar({ health, open, onNavigate, user }) {
  return (
    <aside className={`app-sidebar shrink-0 border-r flex flex-col ${open ? 'is-open' : ''}`}>
      <div className="px-5 py-5 border-b border-[var(--app-border)]">
        <div className="flex items-center gap-3">
          <div
            className="h-9 w-9 shrink-0 flex items-center justify-center border border-[var(--app-border)] bg-[var(--app-surface)] font-mono text-[10px] font-bold text-[var(--app-accent)] tracking-widest"
            style={{ borderRadius: 4 }}
            aria-hidden
          >
            VA
          </div>
          <div className="min-w-0">
            <div
              className="font-extrabold text-[var(--app-text)] leading-tight truncate"
              style={{ letterSpacing: '-0.04em' }}
            >
              VigilAI
            </div>
            <div className="text-[10px] text-[var(--app-text-muted)] leading-tight uppercase tracking-[0.12em] truncate font-mono">
              Pharmacovigilance
            </div>
          </div>
        </div>
      </div>
      <nav className="flex-1 px-3 py-4 space-y-4 overflow-y-auto">
        {NAV_SECTIONS.map((section) => {
          const items = section.items.filter((n) => !n.minRole || hasMinRole(user, n.minRole));
          if (!items.length) return null;
          return (
          <div key={section.title}>
            <div className="px-3 mb-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-[var(--app-text-faint)] font-mono">
              {section.title}
            </div>
            <div className="space-y-0.5">
              {items.map((n) => (
                <NavLink
                  key={n.to}
                  to={n.to}
                  end={n.end}
                  onClick={() => onNavigate?.()}
                  className={({ isActive }) =>
                    `flex items-center gap-3 px-3 py-2 text-sm border ${
                      isActive
                        ? 'app-nav-link-active font-semibold'
                        : 'app-nav-link border-transparent'
                    }`
                  }
                  style={{ borderRadius: 4, letterSpacing: '-0.02em' }}
                >
                  <span className="w-4 text-center shrink-0 text-[var(--app-accent)] opacity-80">{n.icon}</span>
                  <span className="truncate">{n.label}</span>
                </NavLink>
              ))}
            </div>
          </div>
          );
        })}
      </nav>
      <div className="px-4 py-3 border-t border-[var(--app-border)] text-[11px] text-[var(--app-text-muted)]">
        <div className="flex items-center gap-2 font-mono text-[10px] tracking-wide">
          <span className={`h-1.5 w-1.5 shrink-0 ${health ? 'bg-[var(--app-accent)]' : 'bg-rose-400'}`} />
          {health ? 'BACKEND ONLINE' : 'BACKEND OFFLINE'}
        </div>
        <div className="mt-1.5 break-words font-mono text-[10px]">
          LLM: <span className={health?.llm?.backend && health.llm.backend !== 'deterministic' ? 'text-[var(--app-accent)]' : 'text-[var(--app-text-faint)]'}>
            {health?.llm?.backend || (health?.llm?.ollama ? 'ollama' : 'offline')}
          </span>
          {' · '}NER: {health?.transformer_ner ? 'transformer' : 'lexicon'}
        </div>
        <div className="mt-1.5 text-[10px] text-[var(--app-text-faint)] leading-snug">
          Nine hubs · ⌘K deep links · no motion stage
        </div>
      </div>
    </aside>
  );
}

// `fast: true` = included in "Select all". Slow sources (Reddit/YouTube) are opt-in only —
// selecting every source used to recompute the full corpus after EACH crawl (15+ min).
const INGEST_SOURCES = [
  { id: 'google_news',  label: 'Google News',             icon: '📰', fast: true,  fn: (opts) => api.crawlGoogleNews(undefined, opts),                         note: '5 PV queries · works on work networks' },
  { id: 'life_science', label: 'Life-science news',       icon: '🧬', fast: true,  fn: (opts) => api.crawlLifeScience(undefined, 50, opts),                    note: 'ScienceDaily · STAT · Nature Med · WHO · FiercePharma' },
  { id: 'hackernews',   label: 'HackerNews',              icon: '🔶', fast: true,  fn: (opts) => api.crawlHackerNews(undefined, 30, opts),                     note: 'Drug safety discussions — Algolia, no key' },
  { id: 'fda_rss',      label: 'FDA alerts + recalls',    icon: '🚨', fast: true,  fn: (opts) => api.crawlFdaRss(undefined, opts),                             note: 'MedWatch · recalls · press releases' },
  { id: 'faers_live',   label: 'FDA FAERS reports',       icon: '🏥', fast: true,  fn: (opts) => api.crawlFaersLive(30, 90, opts),                             note: 'Live serious AE reports from openFDA' },
  { id: 'faers_bulk',   label: 'FAERS bulk subset',       icon: '📦', fast: true,  fn: (opts) => api.crawlFaersBulk(50, opts),                                 note: 'Quarterly ASCII slice + fixtures · DDI polypharmacy' },
  { id: 'vaers',        label: 'VAERS vaccine AEs',       icon: '💉', fast: true,  fn: (opts) => api.crawlVaers(40, opts),                                     note: 'CDC VAERS-style · offline fixtures fallback' },
  { id: 'pubmed',       label: 'PubMed abstracts',        icon: '🔬', fast: true,  fn: (opts) => api.crawlPubmedLive(undefined, 20, opts),                     note: 'Full abstracts · MeSH PV queries · NCBI' },
  { id: 'europe_pmc',   label: 'Europe PMC abstracts',    icon: '📗', fast: true,  fn: (opts) => api.crawlEuropePmc(undefined, 20, opts),                      note: 'EMBL-EBI literature · title + abstract' },
  { id: 'semantic_scholar', label: 'Semantic Scholar',    icon: '🎓', fast: true,  fn: (opts) => api.crawlSemanticScholar(undefined, 20, opts),               note: 'Academic Graph papers · abstracts' },
  { id: 'cochrane',     label: 'Cochrane CENTRAL',        icon: '📘', fast: true,  fn: (opts) => api.crawlCochraneCentral(undefined, 15, opts),               note: 'Trial-register abstracts · SRC:cctr' },
  { id: 'dailymed',     label: 'DailyMed labels',         icon: '💊', fast: true,  fn: (opts) => api.crawlDailymedRss(40, opts),                               note: 'New & revised drug labels from NLM' },
  { id: 'mhra',         label: 'MHRA device alerts (UK)', icon: '🇬🇧', fast: true,  fn: (opts) => api.crawlMhraDevices(40, opts),                                note: 'Field Safety Notices + device alerts — gov.uk' },
  { id: 'maude',        label: 'MAUDE live (device MDRs)', icon: '🩺', fast: true,  fn: (opts) => api.crawlMaudeLive(30, opts),                                  note: 'Real FDA device adverse event reports' },
  { id: 'device_news',  label: 'Device safety news',     icon: '📡', fast: true,  fn: (opts) => api.crawlDeviceNews(40, opts),                                 note: 'CGM · pump · implant · CPAP safety news' },
  { id: 'device_recalls', label: 'FDA device recalls',   icon: '⚠️', fast: true,  fn: (opts) => api.crawlDeviceRecalls(30, opts),                              note: 'openFDA device/enforcement Class I/II recalls' },
  { id: 'stream',       label: 'Synthetic batch',         icon: '▶',  fast: true,  fn: () => api.streamTick(4, false),                                        note: 'Demo only' },
  { id: 'youtube',      label: 'YouTube videos + comments', icon: '📺', fast: false, fn: (opts) => api.crawlYoutube(undefined, 20, opts),                       note: 'SLOWER · titles/descriptions + comments · needs API key' },
  { id: 'twitter',      label: 'X / Twitter',             icon: '🐦', fast: false, fn: (opts) => api.crawlTwitter(undefined, opts),                           note: 'SLOWER · live — key configured' },
  { id: 'reddit_pp',    label: 'Reddit (Pullpush)',       icon: '🔴', fast: false, fn: (opts) => api.crawlRedditPullpush(undefined, opts),                    note: '~1–2 min · 29 subs via mirror — demo carefully' },
  { id: 'reddit',       label: 'Reddit (direct)',         icon: '🔴', fast: false, fn: (opts) => api.crawlRedditHealth('drug adverse reaction', opts),         note: 'SLOWER · may be blocked on corporate networks' },
];
const FAST_SOURCE_IDS = INGEST_SOURCES.filter((s) => s.fast).map((s) => s.id);

function DemoBar({ onAction }) {
  const { user } = useAuth();
  const canOps = isAnalyst(user);
  const canReset = isAdmin(user);
  const { lastIngest } = useRefresh();
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState(['google_news', 'life_science', 'faers_live']);
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState({});
  const [seeding, setSeeding] = useState(false);
  const [resetting, setResetting] = useState(false);
  const btnRef = useRef(null);
  const panelRef = useRef(null);
  const [dropPos, setDropPos] = useState({ top: 0, right: 0 });

  const openDrop = () => {
    if (btnRef.current) {
      const r = btnRef.current.getBoundingClientRect();
      setDropPos({ top: r.bottom + 6, right: window.innerWidth - r.right });
    }
    setOpen((o) => !o);
  };

  useEffect(() => {
    if (!open) return;
    const close = (e) => {
      const inBtn = btnRef.current && btnRef.current.contains(e.target);
      const inPanel = panelRef.current && panelRef.current.contains(e.target);
      if (!inBtn && !inPanel) setOpen(false);
    };
    // Use mousedown so we can intercept before click fires on the label
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  if (!canOps) {
    return (
      <span className="text-[10px] font-mono text-[var(--app-text-faint)] hidden sm:inline" title="Viewer role is read-only">
        Read-only · viewer
      </span>
    );
  }

  const toggle = (id) => setSelected((prev) =>
    prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
  );

  const runSelected = async () => {
    if (!selected.length) return;
    setRunning(true);
    setOpen(false);
    setResults({});
    // Wake free-tier Render before the first crawl — otherwise every source shows ✗.
    const awake = await wakeApi();
    if (!awake) {
      setResults({
        _wake: {
          ok: false,
          error: 'API still cold/unreachable. Wait 30–60s and Fetch again with only 2–3 sources (free Render sleeps when idle).',
        },
      });
      setRunning(false);
      setOpen(true);
      return;
    }
    const srcs = INGEST_SOURCES.filter((s) => selected.includes(s.id));
    // Skip corpus recompute on every source — one pass at the end (was causing 15+ min hangs).
    let anyOk = false;
    for (const s of srcs) {
      try {
        const r = await s.fn({ recompute: false });
        anyOk = true;
        setResults((prev) => ({ ...prev, [s.id]: { ok: true, ingested: r?.ingested ?? 0, fetched: r?.fetched ?? r?.unique_fetched ?? 0 } }));
      } catch (err) {
        const msg = err?.message || err?.detail || String(err);
        setResults((prev) => ({ ...prev, [s.id]: { ok: false, error: msg } }));
      }
    }
    if (anyOk) {
      try {
        await api.recompute();
      } catch { /* dashboard still refreshes with newly ingested posts */ }
    }
    onAction();
    setRunning(false);
  };

  const totalIngested = Object.values(results).reduce((s, r) => s + (r.ingested || 0), 0)
    + (lastIngest?.ingested && lastIngest.source === 'pathfinder' ? lastIngest.ingested : 0);
  const anyResult = Object.keys(results).length > 0 || (lastIngest?.ingested > 0);

  return (
    <div className="flex items-center gap-2 flex-wrap justify-end">
      {/* Multi-source picker — portal so dropdown doesn't overlap page content */}
      <button
        ref={btnRef}
        type="button"
        onClick={openDrop}
        disabled={running}
        className="flex items-center gap-1.5 text-xs rounded-lg px-3 py-1.5 border border-sky-700 bg-sky-900/20 text-sky-300 hover:bg-sky-800/30 disabled:opacity-50 transition-colors"
      >
        <span>📡 Sources</span>
        <span className="bg-sky-700 text-white rounded-full px-1.5 text-[10px]">{selected.length}</span>
        <span className="text-[10px]">{open ? '▲' : '▼'}</span>
      </button>

      {open && typeof document !== 'undefined' && createPortal(
        <div
          ref={panelRef}
          style={{ position: 'fixed', top: dropPos.top, right: dropPos.right, zIndex: 9999 }}
          className="w-[min(16rem,calc(100vw-1.5rem))] max-h-[min(70vh,28rem)] overflow-y-auto rounded-xl border border-slate-700 bg-slate-900 shadow-2xl p-2 space-y-0.5"
        >
          <div className="flex items-center justify-between px-2 py-1">
            <span className="text-[10px] uppercase tracking-wide text-slate-500">Select sources</span>
            <button type="button"
              className="text-[10px] text-sky-400 hover:text-sky-300"
              onClick={() => setSelected(
                FAST_SOURCE_IDS.every((id) => selected.includes(id))
                  ? []
                  : [...FAST_SOURCE_IDS]
              )}>
              {FAST_SOURCE_IDS.every((id) => selected.includes(id)) ? 'Clear all' : 'Select fast'}
            </button>
          </div>
          <p className="px-2 pb-1 text-[10px] text-amber-400/90 leading-snug">
            Deploy tip: wake API first, then Fetch 2–3 sources (not all). Free Render times out if you stack every feed.
          </p>
          {results._wake && !results._wake.ok && (
            <p className="px-2 py-1.5 mb-1 text-[10px] text-rose-300 bg-rose-950/40 rounded-lg border border-rose-800/50 leading-snug">
              {results._wake.error}
            </p>
          )}
          {INGEST_SOURCES.map((s) => {
            const checked = selected.includes(s.id);
            const res = results[s.id];
            return (
              <label key={s.id}
                className={`flex items-start gap-2 px-2 py-1.5 rounded-lg cursor-pointer transition-colors ${checked ? 'bg-sky-900/30' : 'hover:bg-slate-800'}`}>
                <input type="checkbox" checked={checked} onChange={() => toggle(s.id)}
                       className="mt-0.5 accent-sky-400 shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-xs text-slate-200">{s.icon} {s.label}</div>
                  <div className="text-[10px] text-slate-500 truncate">{s.note}</div>
                  {res && !res.ok && (
                    <div className="text-[10px] text-rose-400 mt-0.5 break-words whitespace-normal">
                      {res.error || 'Ingest failed'}
                    </div>
                  )}
                </div>
                {res && (
                  <span
                    title={res.ok ? undefined : (res.error || 'Ingest failed')}
                    className={`text-[10px] shrink-0 ${res.ok ? 'text-emerald-400' : 'text-rose-400'}`}
                  >
                    {res.ok ? `+${res.ingested}` : '✗'}
                  </span>
                )}
              </label>
            );
          })}
          {lastIngest?.source === 'pathfinder' && lastIngest.ingested > 0 && (
            <div className="flex items-start gap-2 px-2 py-1.5 rounded-lg bg-teal-900/20 border border-teal-800/40 mt-1">
              <span className="text-xs text-teal-200">🔗 Pathfinder</span>
              <span className="ml-auto text-[10px] text-emerald-400 shrink-0">
                +{lastIngest.ingested}
                {lastIngest.signals != null && (
                  <span className="text-slate-500 ml-1">· {lastIngest.signals} signals</span>
                )}
              </span>
            </div>
          )}
        </div>,
        document.body
      )}

      {/* Run button */}
      <button
        type="button"
        onClick={runSelected}
        disabled={running || !selected.length}
        className="text-xs rounded-lg px-3 py-1.5 border border-emerald-700 bg-emerald-900/20 text-emerald-300 hover:bg-emerald-800/30 disabled:opacity-40 font-medium transition-colors"
      >
        {running ? <span className="animate-pulse">Ingesting…</span> : '▶ Fetch'}
      </button>

      {anyResult && !running && (
        <span className="text-[11px] text-emerald-400" title={lastIngest?.url || ''}>
          +{totalIngested} new
          {lastIngest?.source === 'pathfinder' && lastIngest.signals != null && (
            <span className="text-slate-500"> · {lastIngest.signals} signals</span>
          )}
        </span>
      )}

      {/* Demo corpus */}
      <Button variant="ghost" disabled={running || seeding || resetting}
              onClick={async () => { setSeeding(true); await api.seed(21); onAction(); setSeeding(false); }}>
        {seeding ? 'Seeding…' : 'Demo corpus'}
      </Button>

      {/* Reset — admin only */}
      {canReset && (
        <Button variant="danger" disabled={running || seeding || resetting}
                onClick={async () => { setResetting(true); await api.reset(); onAction(); setResetting(false); }}>
          {resetting ? 'Resetting…' : 'Reset'}
        </Button>
      )}
    </div>
  );
}

function UserMenu() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const btnRef = useRef(null);
  const panelRef = useRef(null);
  const [pos, setPos] = useState({ top: 0, right: 0 });

  const toggle = () => {
    if (!open && btnRef.current) {
      const r = btnRef.current.getBoundingClientRect();
      setPos({ top: r.bottom + 6, right: window.innerWidth - r.right });
    }
    setOpen((o) => !o);
  };

  useEffect(() => {
    if (!open) return;
    const close = (e) => {
      const inBtn = btnRef.current && btnRef.current.contains(e.target);
      const inPanel = panelRef.current && panelRef.current.contains(e.target);
      if (!inBtn && !inPanel) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  if (!user) return null;
  return (
    <>
      <button ref={btnRef} onClick={toggle} className="flex items-center gap-2 text-xs text-slate-300">
        <span className="h-7 w-7 rounded-full bg-gradient-to-br from-sky-500 to-teal-600 flex items-center justify-center text-white font-bold">
          {(user.email || '?')[0].toUpperCase()}
        </span>
        <span className="hidden md:block">{user.role}</span>
      </button>
      {open && typeof document !== 'undefined' && createPortal(
        <div ref={panelRef} style={{ position: 'fixed', top: pos.top, right: pos.right, zIndex: 9999 }}
          className="w-52 rounded-lg border border-slate-700 bg-slate-900 shadow-2xl p-2 text-xs">
          <div className="px-2 py-1 text-slate-400 truncate">{user.email}</div>
          <div className="px-2 py-1 text-teal-400 capitalize font-semibold">{user.role}</div>
          {isAdmin(user) && (
            <button
              type="button"
              onClick={() => { setOpen(false); nav('/users'); }}
              className="w-full text-left px-2 py-1.5 rounded hover:bg-slate-800 text-sky-300"
            >
              Manage users
            </button>
          )}
          <hr className="border-slate-700 my-1"/>
          <button onClick={() => { setOpen(false); logout(); }} className="w-full text-left px-2 py-1.5 rounded hover:bg-slate-800 text-rose-300">Sign out</button>
        </div>,
        document.body
      )}
    </>
  );
}

export default function App() {
  const [health, setHealth] = useState(null);
  const [tick, setTick] = useState(0);
  const [lastIngest, setLastIngest] = useState(null);
  const [user, setUser] = useState(null);
  const [authReady, setAuthReady] = useState(!getToken());
  const bump = () => setTick((t) => t + 1);
  const recordIngest = (info) => {
    if (info) setLastIngest(info);
    bump();
  };

  useEffect(() => {
    if (!user) return;
    api.health().then(setHealth).catch(() => setHealth(null));
  }, [tick, user]);

  useEffect(() => {
    if (!getToken()) {
      setAuthReady(true);
      return;
    }
    api.me()
      .then(setUser)
      .catch(() => { setToken(''); setUser(null); })
      .finally(() => setAuthReady(true));
  }, []);

  const login = (token, u) => { setToken(token); setUser(u); };
  const logout = () => {
    localStorage.removeItem('vigilai_token');
    setToken('');
    setUser(null);
  };

  const [cmdOpen, setCmdOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const openCmd = useCallback(() => setCmdOpen(true), []);
  const closeCmd = useCallback(() => setCmdOpen(false), []);
  const closeNav = useCallback(() => setNavOpen(false), []);
  const location = useLocation();
  const isBiotechHome = location.pathname === '/' || location.pathname === '/home';
  const isLoginPath = location.pathname === '/login';

  useEffect(() => {
    if (!user) return undefined;
    const handler = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') { e.preventDefault(); setCmdOpen((o) => !o); }
      if (e.key === 'Escape') { setCmdOpen(false); setNavOpen(false); }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [user]);

  useEffect(() => {
    const onResize = () => {
      if (window.innerWidth > 1200) setNavOpen(false);
    };
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  return (
    <ThemeProvider>
    <AuthContext.Provider value={{ user, login, logout }}>
      {!authReady ? (
        <div className="login-gate min-h-[100dvh] flex items-center justify-center text-sm text-[var(--app-text-muted)]">
          Loading VigilAI…
        </div>
      ) : isLoginPath ? (
        <Login />
      ) : isBiotechHome ? (
        <RefreshContext.Provider value={{ tick, bump, lastIngest, recordIngest }}>
          <BiotechHomepagePage />
        </RefreshContext.Provider>
      ) : !user ? (
        <Navigate to="/login" replace />
      ) : (
      <ProjectProvider>
      <RefreshContext.Provider value={{ tick, bump, lastIngest, recordIngest }}>
        {cmdOpen && <CommandPalette onClose={closeCmd} />}
        <div className="app-shell">
          {navOpen && (
            <button
              type="button"
              aria-label="Close navigation"
              className="app-sidebar-backdrop"
              onClick={closeNav}
            />
          )}
          <Sidebar health={health} open={navOpen} onNavigate={closeNav} user={user} />
          <div className="app-main-column">
            <header className="app-header px-3 sm:px-4 md:px-5 py-2.5 border-b">
              <div className="app-header-row">
                <div className="app-header-brand min-w-0">
                  <button
                    type="button"
                    aria-label="Open navigation"
                    aria-expanded={navOpen}
                    onClick={() => setNavOpen((o) => !o)}
                    className="app-nav-toggle shrink-0 rounded-lg border border-[var(--app-border)] px-2.5 py-1.5 text-sm text-[var(--app-text-muted)] hover:bg-[var(--app-surface-hover)]"
                  >
                    ☰
                  </button>
                  <div className="min-w-0 flex-1">
                    <h1 className="app-header-title-full text-sm lg:text-base font-semibold text-[var(--app-text)] leading-tight truncate">
                      Social listening for patient safety
                      <span className="text-[var(--app-accent)] opacity-90"> · Worldwide</span>
                    </h1>
                    <h1 className="app-header-title-short text-sm font-semibold text-[var(--app-text)] leading-tight truncate">
                      VigilAI <span className="text-[var(--app-accent)] opacity-90">· PV</span>
                    </h1>
                    <p className="app-header-sub text-[10px] md:text-[11px] text-[var(--app-text-muted)] leading-tight truncate">
                      Entities · disproportionality · WHO-UMC · MedDRA · E2B
                    </p>
                  </div>
                </div>
                <div className="app-header-actions">
                  <button type="button" onClick={openCmd}
                    className="hidden xl:flex items-center gap-1.5 text-[11px] text-[var(--app-text-muted)] border border-[var(--app-border)] rounded-lg px-2.5 py-1 hover:text-[var(--app-text)] transition-colors shrink-0">
                    <span>⌘K</span>
                    <span className="text-[var(--app-text-faint)]">Quick nav</span>
                  </button>
                  <ProjectSelector />
                  <ThemeToggle />
                  <DemoBar onAction={bump} />
                  <UserMenu />
                </div>
              </div>
            </header>
            <main className="app-main-scroll">
              <Routes>
                <Route path="/dashboard" element={<Dashboard />} />
                <Route path="/signals" element={<SignalWorkbench />} />
                <Route path="/signals/:id" element={<SignalDetail />} />
                <Route path="/lenses" element={<Lenses />} />
                <Route path="/graph" element={<Evidence />} />
                <Route path="/projects" element={<Projects />} />
                <Route path="/source-queue" element={<DiscoveryHub />} />
                <Route path="/sources" element={<SourcesHub />} />
                <Route path="/forge" element={<Forge />} />
                <Route path="/users" element={<UsersAdmin />} />
                <Route path="/corporate" element={<Navigate to="/" replace />} />
                <Route path="/classic" element={<Navigate to="/dashboard" replace />} />
                <Route path="/kpis" element={<Navigate to="/dashboard?tab=ops" replace />} />
                <Route path="/lifecycle" element={<Navigate to="/signals?tab=lifecycle" replace />} />
                <Route path="/alerts" element={<Navigate to="/signals?tab=alerts" replace />} />
                <Route path="/smq" element={<Navigate to="/lenses?tab=smq" replace />} />
                <Route path="/class-effects" element={<Navigate to="/lenses?tab=class" replace />} />
                <Route path="/vaccine" element={<Navigate to="/lenses?tab=vaccine" replace />} />
                <Route path="/spatial" element={<Navigate to="/lenses?tab=spatial" replace />} />
                <Route path="/divergence" element={<Navigate to="/lenses?tab=divergence" replace />} />
                <Route path="/story" element={<Navigate to="/graph?tab=story" replace />} />
                <Route path="/feed" element={<Navigate to="/sources?tab=live" replace />} />
                <Route path="/command" element={<Navigate to="/sources?tab=agent" replace />} />
                <Route path="/onboarding" element={<Navigate to="/source-queue?tab=manual" replace />} />
                <Route path="/surveillance" element={<Navigate to="/sources?tab=networks" replace />} />
              </Routes>
            </main>
          </div>
        </div>
      </RefreshContext.Provider>
      </ProjectProvider>
      )}
    </AuthContext.Provider>
    </ThemeProvider>
  );
}
