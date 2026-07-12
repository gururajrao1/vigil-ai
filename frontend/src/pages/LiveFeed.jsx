import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { useRefresh } from '../App';
import { Badge, Button, Card, CardHeader, Spinner } from '../components/ui';

const MODES = [
  { id: 'google_news',  label: 'Google News (live)',        note: '5 curated PV queries — works on work laptops' },
  { id: 'faers_live',   label: 'FDA FAERS live reports',    note: 'Real AE reports from openFDA — regulatory-grade' },
  { id: 'dailymed_rss', label: 'DailyMed label updates',   note: 'New/revised drug labels from NLM RSS' },
  { id: 'pubmed_live',  label: 'PubMed literature',        note: 'PV / drug safety articles via NCBI' },
  { id: 'fda_rss',      label: 'FDA alerts + recalls',    note: 'MedWatch · recalls · press releases (3 feeds)' },
  { id: 'hackernews',   label: 'HackerNews discussions',  note: 'Drug safety on HN via Algolia — no key' },
  { id: 'life_science', label: 'Life-science news pack',  note: 'ScienceDaily · STAT · Nature Med · WHO · FiercePharma — no key' },
  { id: 'youtube',      label: 'YouTube videos + comments', note: 'Titles/descriptions + AE comments — needs YOUTUBE_API_KEY' },
  { id: 'mhra_devices', label: 'MHRA device alerts (UK)', note: 'Field Safety Notices — pacemakers, stents, ventilators' },
  { id: 'maude_live',   label: 'MAUDE live (device MDRs)', note: 'Real FDA device adverse event reports' },
  { id: 'twitter',         label: 'X / Twitter (live)',             note: 'Live tweets — TWITTERAPI_IO_KEY configured' },
  { id: 'reddit_pullpush', label: 'Reddit via Pullpush (corp-safe)', note: '29 health subs via mirror — not blocked on work networks' },
  { id: 'reddit',          label: 'Reddit search (direct)',         note: 'Public RSS — may be blocked on corporate networks' },
  { id: 'reddit_health',   label: 'Reddit health subs (direct)',    note: '29 curated communities — direct reddit.com' },
  { id: 'stream',       label: 'Synthetic sim',             note: 'Demo only — not real posts' },
];

const QUERIES = [
  '',
  'drug side effect OR adverse drug reaction',
  'vaccine adverse reaction',
  'FDA drug recall',
  'pharmacovigilance signal',
];

function StreamControl({ onBatch }) {
  const [status, setStatus] = useState(null);
  const [mode, setMode] = useState('google_news');
  const [query, setQuery] = useState('');
  const [interval, setIntervalSec] = useState(45);
  const [subCount, setSubCount] = useState(null);
  const [newsQueryCount, setNewsQueryCount] = useState(null);
  const [lsFeedCount, setLsFeedCount] = useState(null);
  const poll = useRef(null);

  const refresh = () => api.streamStatus().then(setStatus).catch(() => setStatus(null));
  useEffect(() => {
    refresh();
    api.redditHealthSubs().then((d) => setSubCount(d.count)).catch(() => setSubCount(null));
    api.googleNewsQueries().then((d) => setNewsQueryCount(d.count)).catch(() => setNewsQueryCount(null));
    api.lifeScienceFeeds().then((d) => setLsFeedCount(d.count)).catch(() => setLsFeedCount(null));
  }, []);

  useEffect(() => {
    if (status?.running) {
      poll.current = setInterval(() => {
        refresh();
        onBatch?.();
      }, 5000);
    }
    return () => clearInterval(poll.current);
  }, [status?.running]);

  const startStream = async () => {
    const q = query.trim() || (mode === 'google_news' ? ' ' : '');
    await api.streamStart({ interval, mode, query: q === ' ' ? '' : q });
    refresh();
    onBatch?.();
  };
  const stopStream = async () => {
    await api.streamStop();
    refresh();
  };
  const running = status?.running;
  const live = mode !== 'stream';

  return (
    <Card className={`p-4 ${live ? 'border-emerald-800/40 bg-emerald-500/[0.03]' : 'border-amber-800/40 bg-amber-500/[0.03]'}`}>
      <CardHeader
        title="Continuous ingestion"
        subtitle={mode === 'google_news'
          ? 'Pulls live Google News RSS on a timer — works on corporate networks where Reddit is blocked.'
          : live
            ? 'Pulls live posts on a timer, runs NLP, recomputes signals — runs server-side even if you close this tab.'
            : 'Synthetic simulator for demos. Switch mode to Google News for real-world data.'}
        right={
          <Badge
            value={running
              ? `● ${status?.mode ?? mode} · ${status?.session_id?.slice(0, 8) ?? '…'}`
              : '○ idle'}
            className={running
              ? (live ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
                     : 'bg-amber-500/15 text-amber-300 border-amber-500/30')
              : 'bg-slate-600/20 text-slate-400 border-slate-600/30'}
          />
        }
      />
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <label className="text-xs text-slate-400">
          Source
          <select value={mode} disabled={running} onChange={(e) => setMode(e.target.value)}
                  className="mt-1 block rounded-lg bg-slate-900 border border-slate-700 text-slate-200 text-sm px-2 py-1.5 w-full min-w-0 sm:min-w-[200px]">
            {MODES.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select>
        </label>
        <label className="text-xs text-slate-400 flex-1 min-w-[140px] sm:min-w-[180px]">
          Search query
          <input type="text" value={query} disabled={running || mode === 'stream'}
                 onChange={(e) => setQuery(e.target.value)}
                 placeholder={mode === 'google_news'
                   ? 'Leave empty = all 5 curated PV queries'
                   : mode === 'life_science'
                     ? 'Leave empty = all outlets · or feed id (stat, sciencedaily…)'
                     : 'Search terms…'}
                 list="live-feed-queries"
                 className="mt-1 block w-full rounded-lg bg-slate-900 border border-slate-700 text-slate-200 text-sm px-2 py-1.5" />
          <datalist id="live-feed-queries">
            {QUERIES.map((q) => <option key={q} value={q} />)}
          </datalist>
        </label>
        <label className="text-xs text-slate-400">
          Interval (s)
          <input type="number" min={15} max={300} value={interval} disabled={running}
                 onChange={(e) => setIntervalSec(Math.max(15, Number(e.target.value) || 30))}
                 className="mt-1 block w-20 rounded-lg bg-slate-900 border border-slate-700 text-slate-200 text-sm px-2 py-1.5" />
        </label>
        <Button variant={running ? 'danger' : 'primary'} onClick={running ? stopStream : startStream}>
          {running ? '■ Stop' : (live ? '▶ Start live monitoring' : '▶ Start synthetic sim')}
        </Button>
      </div>
      {mode === 'google_news' && newsQueryCount != null && (
        <p className="mt-2 text-[11px] text-slate-500">
          {query.trim()
            ? <>Custom query: <span className="text-slate-300">{query}</span></>
            : <>Running <span className="text-slate-300">{newsQueryCount}</span> curated PV queries (drug AEs, vaccine safety, recalls, FDA warnings, PV news)</>}
        </p>
      )}
      {mode === 'life_science' && lsFeedCount != null && (
        <p className="mt-2 text-[11px] text-slate-500">
          {query.trim()
            ? <>Single outlet: <span className="text-slate-300">{query}</span> (feed id)</>
            : <>Pulling <span className="text-slate-300">{lsFeedCount}</span> outlets — ScienceDaily, STAT, Nature Medicine, WHO, FiercePharma, Endpoints, GEN, NPR Health, Medical Xpress</>}
        </p>
      )}
      {mode === 'reddit_health' && subCount != null && (
        <p className="mt-2 text-[11px] text-slate-500">
          Searching <span className="text-slate-300">{subCount}</span> health subreddits each tick
          (AskDocs, pharmacy, cancer, vaccines, ADHD, diabetes, accutane…)
        </p>
      )}
      {status && (
        <div className="mt-3 space-y-1.5">
          <div className="text-xs text-slate-400 flex flex-wrap gap-x-4 gap-y-1">
            <span>mode: <span className="text-slate-200">{status.mode}</span>
              {status.last_source_used && status.last_source_used !== status.mode && (
                <span className="ml-1 text-amber-400" title="Self-healed to fallback source">
                  → {status.last_source_used} ⚡
                </span>
              )}
            </span>
            <span>interval: <span className="text-slate-200">{status.interval_seconds}s</span></span>
            <span>batches: <span className="text-slate-200">{status.batches_processed ?? 0}</span></span>
            <span>posts: <span className="text-slate-200">{status.total_posts_ingested ?? 0}</span></span>
            {status.latest_batch_at && (
              <span>latest: <span className="text-slate-200">{status.latest_batch_at.replace('T', ' ').slice(11, 19)}</span> (+{status.last_ingested})</span>
            )}
            {status.last_error && (
              <span className={status.last_error.startsWith('[self-heal]') ? 'text-amber-400' : 'text-rose-400'}>
                {status.last_error.startsWith('[self-heal]') ? '⚡ ' : '✗ '}{status.last_error}
              </span>
            )}
          </div>
          {/* Source health panel */}
          {Object.keys(status.source_health || {}).length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-1">
              {Object.values(status.source_health).map((h) => (
                <span key={h.source_id}
                  title={`✓ ${h.total_successes} · ✗ ${h.total_failures}${h.last_error ? ' · ' + h.last_error : ''}`}
                  className={`text-[10px] rounded px-1.5 py-0.5 border font-mono ${
                    h.quarantined
                      ? 'bg-rose-900/30 border-rose-700/40 text-rose-300'
                      : h.consecutive_failures > 0
                        ? 'bg-amber-900/30 border-amber-700/40 text-amber-300'
                        : 'bg-emerald-900/20 border-emerald-800/30 text-emerald-400'
                  }`}>
                  {h.quarantined ? '🔴' : h.consecutive_failures > 0 ? '🟡' : '🟢'} {h.source_id}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

export default function LiveFeed({ embedded = false }) {
  const { bump, tick } = useRefresh();
  const [posts, setPosts] = useState(null);
  const [aeOnly, setAeOnly] = useState(false);
  const [bootstrapping, setBootstrapping] = useState(false);

  const load = () => api.posts({ ae_only: aeOnly, limit: 40 }).then((d) => setPosts(d.posts)).catch(() => setPosts([]));
  useEffect(() => { load(); }, [aeOnly, tick]);

  const bootstrapLive = async () => {
    setBootstrapping(true);
    try {
      await api.reset();
      await api.crawlGoogleNews();
      await api.crawlLifeScience();
      load();
      bump();
    } catch (e) {
      console.error(e);
    }
    setBootstrapping(false);
  };

  return (
    <div className="space-y-4">
      <Card className="p-4 border-slate-700/60">
        <CardHeader
          title="Real-time setup (live news)"
          subtitle="Clear demo data, bootstrap from Google News + life-science RSS, then start continuous monitoring below."
        />
        <div className="mt-3 flex flex-wrap gap-2">
          <Button variant="ghost" disabled={bootstrapping} onClick={bootstrapLive}>
            {bootstrapping ? 'Bootstrapping…' : '① Reset + bootstrap news packs'}
          </Button>
          <span className="text-xs text-slate-500 self-center">
            Google News + ScienceDaily/STAT/Nature Med/WHO — no API key
          </span>
        </div>
      </Card>

      <StreamControl onBatch={() => { load(); bump(); }} />

      <div className="flex items-center justify-end">
        <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
          <input type="checkbox" checked={aeOnly} onChange={(e) => setAeOnly(e.target.checked)} className="accent-rose-500" />
          Adverse events only
        </label>
      </div>

      {!posts ? <Spinner /> : (
        <div className="space-y-2">
          {posts.length === 0 && (
            <Card className="p-8 text-center text-slate-500 text-sm">
              No posts yet. Click <strong>Reset + bootstrap news packs</strong> or start live monitoring.
            </Card>
          )}
          {posts.map((p) => (
            <Card key={p.id} className="p-3">
              <div className="flex items-center justify-between text-xs text-slate-500 mb-1.5 gap-2">
                <span className="uppercase tracking-wide truncate">
                  {p.platform} · {p.posted_at?.replace('T', ' ').slice(0, 16)}
                  {p.text_full_len > 600 && (
                    <span className="normal-case text-slate-600 ml-1">({p.text_full_len} chars)</span>
                  )}
                </span>
                <div className="flex gap-1.5 shrink-0">
                  {p.ae_flag
                    ? <Badge value="ADVERSE EVENT" className="bg-rose-500/15 text-rose-300 border-rose-500/30" />
                    : <Badge value="no AE" className="bg-slate-700/40 text-slate-400 border-slate-600/40" />}
                  <Badge value={p.sentiment.label} className={p.sentiment.label === 'NEGATIVE' ? 'bg-rose-500/15 text-rose-300 border-rose-500/30' : 'bg-slate-600/20 text-slate-300 border-slate-600/30'} />
                </div>
              </div>
              {p.title && (
                <div className="text-xs text-slate-400 mb-1 truncate" title={p.title}>{p.title}</div>
              )}
              <p className="text-sm text-slate-200 whitespace-pre-wrap break-words line-clamp-6">{p.text}</p>
              {p.url && (
                <a href={p.url} target="_blank" rel="noreferrer"
                  className="text-[10px] text-teal-500/80 hover:text-teal-400 mt-1 inline-block truncate max-w-full">
                  {p.url}
                </a>
              )}
              <div className="flex flex-wrap gap-1.5 mt-2">
                {(p.entities.drugs || []).map((d, i) => <span key={`d${i}`} className="rounded bg-sky-500/15 text-sky-300 px-1.5 py-0.5 text-[10px] capitalize">💊 {d.normalized}</span>)}
                {(p.entities.symptoms || []).map((s, i) => <span key={`s${i}`} className="rounded bg-rose-500/15 text-rose-300 px-1.5 py-0.5 text-[10px] capitalize">⚕ {s.normalized}</span>)}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
