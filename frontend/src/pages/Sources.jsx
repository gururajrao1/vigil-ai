import { useEffect, useState } from 'react';
import { api } from '../api';
import { Badge, Button, Card, CardHeader, Spinner } from '../components/ui';

// Per-source ingest actions wired to existing API endpoints.
const SOURCE_ACTIONS = {
  reddit_pullpush: {
    label: '🔴 Crawl Reddit (Pullpush mirror)',
    fn: () => api.crawlRedditPullpush(),
    note: 'Works on corporate networks — same 29 health subs via archive API',
  },
  reddit: {
    label: '🔴 Crawl Reddit (direct)',
    fn: () => api.crawlReddit('drug adverse reaction'),
    note: 'Direct reddit.com — may be blocked on corporate networks',
  },
  reddit_health: {
    label: '🔴 Crawl health subs (direct)',
    fn: () => api.crawlRedditHealth('drug adverse reaction'),
    note: '29 health communities — direct reddit.com',
  },
  google_news: {
    label: '📰 Fetch Google News',
    fn: () => api.crawlGoogleNews(),
    note: 'All 5 curated PV queries — works on work laptops',
  },
  faers_live: {
    label: '🏥 Fetch FAERS reports',
    fn: () => api.crawlFaersLive(),
    note: 'Last 90 days serious AE reports from openFDA',
  },
  faers_bulk: {
    label: '📦 Fetch FAERS bulk subset',
    fn: () => api.crawlFaersBulk(),
    note: 'Quarterly ASCII-style slice + fixtures · polypharmacy for DDI',
  },
  vaers: {
    label: '💉 Fetch VAERS reports',
    fn: () => api.crawlVaers(),
    note: 'Vaccine AE reports · offline fixtures when CDC blocked',
  },
  dailymed_rss: {
    label: '💊 Fetch label updates',
    fn: () => api.crawlDailymedRss(),
    note: 'New & revised drug labels from NLM',
  },
  pubmed_live: {
    label: '🔬 Fetch PubMed abstracts',
    fn: () => api.crawlPubmedLive(),
    note: 'Full abstracts via efetch · MeSH PV / project-scoped queries',
  },
  europe_pmc: {
    label: '📗 Fetch Europe PMC abstracts',
    fn: () => api.crawlEuropePmc(),
    note: 'EMBL-EBI literature REST · offline fixtures if blocked',
  },
  semantic_scholar: {
    label: '🎓 Fetch Semantic Scholar',
    fn: () => api.crawlSemanticScholar(),
    note: 'Academic Graph abstracts · optional SEMANTIC_SCHOLAR_API_KEY',
  },
  cochrane_central: {
    label: '📘 Fetch Cochrane CENTRAL',
    fn: () => api.crawlCochraneCentral(),
    note: 'Trial-register abstracts via Europe PMC SRC:cctr',
  },
  hackernews: {
    label: '🔶 Crawl HackerNews',
    fn: () => api.crawlHackerNews(),
    note: 'Drug safety/pharmacovigilance discussions via Algolia (no key)',
  },
  life_science: {
    label: '🧬 Fetch life-science news',
    fn: () => api.crawlLifeScience(),
    note: 'ScienceDaily · STAT · Nature Medicine · WHO · FiercePharma · Endpoints · GEN',
  },
  youtube: {
    label: '📺 Crawl YouTube (videos + comments)',
    fn: () => api.crawlYoutube(),
    note: 'Video titles/descriptions + AE comment threads (needs YOUTUBE_API_KEY)',
    disabled: !window?.location,   // always enabled — backend handles missing key gracefully
  },
  mhra_devices: {
    label: '🇬🇧 Fetch MHRA device alerts',
    fn: () => api.crawlMhraDevices(),
    note: 'UK Field Safety Notices + device safety info',
  },
  maude_live: {
    label: '🩺 Fetch MAUDE MDRs',
    fn: () => api.crawlMaudeLive(),
    note: 'Real FDA device adverse event reports',
  },
  device_news: {
    label: '📡 Fetch device safety news',
    fn: () => api.crawlDeviceNews(),
    note: 'CGM · pump · implant · CPAP safety headlines',
  },
  device_recalls: {
    label: '⚠️ Fetch FDA device recalls',
    fn: () => api.crawlDeviceRecalls(),
    note: 'openFDA device/enforcement Class I/II recalls',
  },
  eudamed: null,
  fda_medwatch: {
    label: '🚨 Fetch MedWatch alerts',
    fn: () => api.crawlFdaRss('fda_medwatch'),
    note: 'Safety alerts, market withdrawals, label warnings',
  },
  fda_recalls: {
    label: '🚨 Fetch FDA recalls',
    fn: () => api.crawlFdaRss('fda_recalls'),
    note: 'Drugs, devices, biologics recalls',
  },
  fda_press: {
    label: '📣 Fetch FDA press releases',
    fn: () => api.crawlFdaRss('fda_press'),
    note: 'Approvals, safety comms, public health announcements',
  },
  openfda: null,
  fhir: null,
  twitter: {
    label: '🐦 Crawl X/Twitter',
    fn: () => api.crawlTwitter('drug side effect adverse reaction'),
    note: 'Live — key configured',
  },
  forum: null,
};

const SAMPLE_BUNDLE = JSON.stringify({
  resourceType: "Bundle",
  id: "vigilai-sample",
  type: "collection",
  entry: [
    {
      resource: {
        resourceType: "AdverseEvent",
        id: "ae-sample-1",
        status: "completed",
        actuality: "actual",
        event: { coding: [{ display: "rhabdomyolysis" }] },
        suspectEntity: [{ instance: { display: "simvastatin" } }],
        seriousness: { coding: [{ code: "hospitalization" }] },
        outcome: { coding: [{ code: "resolvedWithSequelae" }] },
        location: { display: "United States" },
        recordedDate: "2024-03-15"
      }
    },
    {
      resource: {
        resourceType: "AdverseEvent",
        id: "ae-sample-2",
        status: "completed",
        actuality: "actual",
        event: { coding: [{ display: "angioedema" }] },
        suspectEntity: [{ instance: { display: "lisinopril" } }],
        seriousness: { coding: [{ code: "lifeThreatening" }] },
        outcome: { coding: [{ code: "resolved" }] },
        location: { display: "Germany" },
        recordedDate: "2024-04-02"
      }
    }
  ]
}, null, 2);

export default function Sources({ embedded = false }) {
  const [sources, setSources] = useState(null);
  const [llm, setLlm] = useState(null);
  const [sourceStats, setSourceStats] = useState({});
  const [fhirJson, setFhirJson] = useState('');
  const [fhirBusy, setFhirBusy] = useState(false);
  const [fhirResult, setFhirResult] = useState(null);
  const [fhirError, setFhirError] = useState(null);
  const [crawlBusy, setCrawlBusy] = useState(null);
  const [crawlResults, setCrawlResults] = useState({});

  const loadStats = () => api.sourceStats().then((d) => {
    const map = {};
    (d.stats || []).forEach((s) => { map[s.source_id] = s; });
    setSourceStats(map);
  }).catch(() => {});

  useEffect(() => {
    api.sources().then((d) => setSources(d.sources)).catch(() => setSources([]));
    api.llmStatus().then(setLlm).catch(() => setLlm(null));
    loadStats();
  }, []);

  const runCrawl = async (id, fn) => {
    setCrawlBusy(id);
    try {
      const r = await fn();
      setCrawlResults((prev) => ({ ...prev, [id]: r }));
      loadStats();
      // Queue signal rebuild off the request path (avoids Vercel proxy timeouts).
      api.recompute().catch(() => {});
    } catch (e) {
      setCrawlResults((prev) => ({ ...prev, [id]: { error: e.message } }));
    }
    setCrawlBusy(null);
  };

  const handleFhirIngest = async () => {
    setFhirError(null);
    setFhirResult(null);
    let parsed;
    try {
      parsed = JSON.parse(fhirJson);
    } catch {
      setFhirError('Invalid JSON — please paste a valid FHIR Bundle or resource.');
      return;
    }
    setFhirBusy(true);
    try {
      const r = await api.ingestFhir(parsed);
      setFhirResult(r);
    } catch (e) {
      setFhirError(e.message || 'Ingest failed.');
    } finally {
      setFhirBusy(false);
    }
  };

  if (!sources) return <Spinner />;

  return (
    <div className="space-y-6">
      <Card className="p-4">
        <CardHeader title="Worldwide data sources" subtitle="Every live source runs with no API key; keyed sources degrade gracefully when unconfigured." />
        <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3">
          {sources.map((s) => {
            const action = SOURCE_ACTIONS[s.id];
            const res = crawlResults[s.id];
            return (
              <div key={s.id} className="rounded-lg border border-slate-800 bg-slate-950/40 p-4">
                <div className="flex items-center justify-between">
                  <div className="font-medium text-slate-100">{s.name}</div>
                  <Badge value={s.status}
                         className={s.status === 'live' ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' : 'bg-amber-500/15 text-amber-300 border-amber-500/30'} />
                </div>
                <div className="mt-1 text-xs text-slate-400">{s.note}</div>
                <div className="mt-2 flex gap-2 text-[11px] flex-wrap">
                  <Badge value={s.type} className="bg-slate-700/40 text-slate-300 border-slate-600/40" />
                  <Badge value={s.scope} className="bg-sky-500/10 text-sky-300 border-sky-500/20" />
                  <Badge value={s.key_required ? 'key required' : 'no key'} className="bg-slate-700/40 text-slate-300 border-slate-600/40" />
                </div>
                {action && (
                  <div className="mt-3 flex items-center gap-3 flex-wrap">
                    <Button
                      type="button"
                      size="sm"
                      variant={action.disabled ? 'ghost' : 'gradient'}
                      disabled={!!crawlBusy || action.disabled}
                      loading={crawlBusy === s.id}
                      onClick={() => runCrawl(s.id, action.fn)}
                    >
                      {crawlBusy === s.id ? 'Fetching…' : action.label}
                    </Button>
                    <span className={`text-[10px] ${action.disabled ? 'text-amber-600' : 'text-slate-600'}`}>
                      {action.note}
                    </span>
                    {res && !res.error && (
                      <span className="text-[10px] text-emerald-400">
                        ✓ +{res.ingested ?? 0} new · {res.fetched ?? res.unique_fetched ?? 0} fetched
                      </span>
                    )}
                    {res?.error && <span className="text-[10px] text-rose-400">✗ {res.error}</span>}
                  </div>
                )}
                {!action && s.id === 'eudamed' && (
                  <p className="mt-2 text-[10px] text-slate-600">Used for device signal enrichment — queried automatically on device Signal Detail</p>
                )}
                {/* Per-source post count + AE yield sparkline */}
                {sourceStats[s.id] && (
                  <div className="mt-2 flex items-center gap-3">
                    <div className="text-[10px] text-slate-500">
                      <span className="text-slate-300 font-mono">{sourceStats[s.id].total_posts}</span> posts ingested
                    </div>
                    <div className="text-[10px] text-slate-500">
                      AE yield: <span className={`font-mono ${sourceStats[s.id].ae_rate > 0.4 ? 'text-emerald-400' : 'text-slate-300'}`}>
                        {(sourceStats[s.id].ae_rate * 100).toFixed(0)}%
                      </span>
                    </div>
                    {/* Mini bar showing AE rate */}
                    <div className="flex-1 h-1.5 rounded-full bg-slate-800 overflow-hidden max-w-[60px]">
                      <div className="h-full rounded-full bg-emerald-500/60"
                           style={{ width: `${Math.min(100, sourceStats[s.id].ae_rate * 100)}%` }} />
                    </div>
                  </div>
                )}
                {!action && s.id === 'eudamed' && (
                  <p className="mt-2 text-[10px] text-slate-600">Used for device signal enrichment — queried automatically on device Signal Detail</p>
                )}
                {!action && s.id === 'openfda' && (
                  <p className="mt-2 text-[10px] text-slate-600">Queried automatically on Signal Detail — not a post ingest source</p>
                )}
                {!action && s.id === 'forum' && (
                  <p className="mt-2 text-[10px] text-slate-600">Use <strong className="text-slate-400">Forum Onboarding</strong> page to analyze any forum URL</p>
                )}
              </div>
            );
          })}
        </div>
      </Card>

      {/* ── FHIR / HL7 Import ── */}
      <Card className="p-4">
        <CardHeader
          title="FHIR / HL7 Ingestion"
          subtitle="Paste a FHIR R4 Bundle or single AdverseEvent / MedicationStatement resource (JSON). Posts are ingested with platform='fhir' and flow through the same NLP → signal pipeline."
        />
        <div className="mt-3 space-y-3">
          <div className="flex gap-2">
            <Button type="button" size="sm" variant="outline" onClick={() => setFhirJson(SAMPLE_BUNDLE)}>
              Load sample bundle
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => { setFhirJson(''); setFhirResult(null); setFhirError(null); }}
            >
              Clear
            </Button>
          </div>
          <textarea
            value={fhirJson}
            onChange={(e) => setFhirJson(e.target.value)}
            rows={12}
            placeholder='{"resourceType":"Bundle","type":"collection","entry":[...]}'
            className="w-full p-3 text-xs font-mono resize-y"
          />
          <div className="flex items-center gap-3">
            <Button
              type="button"
              variant="gradient"
              onClick={handleFhirIngest}
              disabled={fhirBusy || !fhirJson.trim()}
              loading={fhirBusy}
            >
              {fhirBusy ? 'Ingesting…' : 'Ingest FHIR Bundle'}
            </Button>
            {fhirBusy && <span className="text-xs text-slate-400 animate-pulse">Running NLP pipeline…</span>}
          </div>

          {fhirError && (
            <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-300">
              {fhirError}
            </div>
          )}

          {fhirResult && (
            <div className="rounded-lg border border-teal-500/30 bg-teal-500/10 p-4 space-y-2">
              <div className="text-sm font-semibold text-teal-300">Ingestion complete</div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-2">
                <Stat k="Parsed" v={fhirResult.parsed ?? '—'} />
                <Stat k="Ingested (new)" v={fhirResult.ingested ?? '—'} good={fhirResult.ingested > 0} />
                <Stat k="Signals" v={fhirResult.signals ?? '—'} good={fhirResult.signals > 0} />
                <Stat k="Alerts" v={fhirResult.alerts ?? '—'} />
              </div>
              {fhirResult.detail && (
                <div className="text-xs text-slate-400 mt-1">{fhirResult.detail}</div>
              )}
            </div>
          )}
        </div>
      </Card>

      <Card className="p-4">
        <CardHeader title="AI engine status" subtitle="Local-first, keyless" />
        <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
          <Stat k="LLM enabled" v={llm?.use_llm ? 'yes' : 'no'} />
          <Stat k="Ollama" v={llm?.ollama ? 'online' : 'offline'} good={llm?.ollama} />
          <Stat k="Model" v={llm?.ollama_model || '—'} />
          <Stat k="OpenRouter" v={llm?.openrouter ? 'configured' : 'not set'} />
        </div>
      </Card>
    </div>
  );
}

function Stat({ k, v, good }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-3">
      <div className="text-[10px] uppercase text-slate-500">{k}</div>
      <div className={`text-sm font-semibold ${good ? 'text-emerald-300' : 'text-slate-200'}`}>{v}</div>
    </div>
  );
}
