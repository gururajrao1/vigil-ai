// Thin API client for the VigilAI backend (worldwide).
const BASE = import.meta.env.VITE_API_BASE || '';

let _token = localStorage.getItem('vigilai_token') || '';
let _projectId = localStorage.getItem('vigilai_project_id') || '';

export function setToken(t) {
  _token = t || '';
  if (t) localStorage.setItem('vigilai_token', t);
  else localStorage.removeItem('vigilai_token');
}
export function getToken() { return _token; }

export function setProjectId(id) {
  _projectId = id ? String(id) : '';
  if (_projectId) localStorage.setItem('vigilai_project_id', _projectId);
  else localStorage.removeItem('vigilai_project_id');
}
export function getProjectId() { return _projectId; }

async function req(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  if (_token) headers.Authorization = `Bearer ${_token}`;
  if (_projectId) headers['X-Project-Id'] = _projectId;
  const res = await fetch(`${BASE}${path}`, { ...opts, headers });
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try { const j = await res.json(); if (j.detail) msg = j.detail; } catch { /* ignore */ }
    throw new Error(msg);
  }
  const ct = res.headers.get('content-type') || '';
  return ct.includes('application/json') ? res.json() : res.text();
}

export const api = {
  health: () => req('/api/health'),
  llmStatus: () => req('/api/llm/status'),
  stats: () => req('/api/dashboard/stats'),
  overview: () => req('/api/trends/overview'),
  sources: () => req('/api/sources'),
  sourceStats: () => req('/api/sources/stats'),

  signals: (params = {}) => {
    const q = new URLSearchParams(
      Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== '' && v !== 'ALL' && v !== false))
    ).toString();
    return req(`/api/signals${q ? `?${q}` : ''}`);
  },
  drugToEvents: (drug) => req(`/api/analytics/drug-to-events/${encodeURIComponent(drug)}`),
  eventToDrugs: (event) => req(`/api/analytics/event-to-drugs/${encodeURIComponent(event)}`),
  recompute: () => req('/api/recompute', { method: 'POST' }),
  normalizeLabels: () => req('/api/normalize/labels', { method: 'POST' }),
  signal: (id) => req(`/api/signals/${id}`),
  signalAudit: (id) => req(`/api/analytics/signal-audit/${id}`),
  termMap: (q) => req(`/api/nlp/term-map?q=${encodeURIComponent(q)}`),
  termGlossary: () => req('/api/nlp/term-glossary'),
  auditChain: () => req('/api/audit/chain'),
  regenerateNarrative: (id) => req(`/api/signals/${id}/narrative`, { method: 'POST' }),
  draftAssessment: (id) => req(`/api/signals/${id}/copilot`, { method: 'POST' }),
  posts: (params = {}) => {
    const q = new URLSearchParams(params).toString();
    return req(`/api/posts${q ? `?${q}` : ''}`);
  },
  alerts: () => req('/api/alerts'),
  kg: () => req('/api/knowledge-graph'),
  kgFilters: (projectId) =>
    projectId
      ? req(`/api/projects/${projectId}/graph/filters`)
      : req('/api/knowledge-graph/filters'),
  e2bUrl: (id) => `${BASE}/api/signals/${id}/e2b`,
  e2bR2Url: (id) => `${BASE}/api/signals/${id}/e2b-r2`,
  ciomsUrl: (id) => `${BASE}/api/signals/${id}/cioms`,
  downloadCioms: async (id, drug, event) => {
    const headers = {};
    if (_token) headers.Authorization = `Bearer ${_token}`;
    const res = await fetch(`${BASE}/api/signals/${id}/cioms`, { headers });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const drugSlug = (drug || 'drug').replace(/\s+/g, '_').toLowerCase().slice(0, 20);
    const eventSlug = (event || 'event').replace(/\s+/g, '_').toLowerCase().slice(0, 20);
    a.href = url;
    a.download = `cioms_${drugSlug}_${eventSlug}.html`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },

  // demo controls
  seed: (days = 21) => req(`/api/ingest/seed?days=${days}`, { method: 'POST' }),
  recompute: () => req('/api/recompute', { method: 'POST' }),
  streamTick: (n = 3, recompute = false) =>
    req(`/api/stream/tick?n=${n}&recompute=${recompute}`, { method: 'POST' }),
  crawlReddit: (query, { recompute = true } = {}) =>
    req(`/api/ingest/reddit?query=${encodeURIComponent(query)}&recompute=${recompute}`, { method: 'POST' }),
  crawlRedditHealth: (query, { recompute = true } = {}) =>
    req(`/api/ingest/reddit-health?query=${encodeURIComponent(query)}&recompute=${recompute}`, { method: 'POST' }),
  redditHealthSubs: () => req('/api/ingest/reddit-health/subs'),
  crawlGoogleNews: (query, { recompute = true } = {}) => {
    const params = new URLSearchParams({ recompute: String(recompute) });
    if (query) params.set('query', query);
    return req(`/api/ingest/google-news?${params}`, { method: 'POST' });
  },
  googleNewsQueries: () => req('/api/ingest/google-news/queries'),
  crawlFaersLive: (limit = 30, daysBack = 90, { recompute = true } = {}) =>
    req(`/api/ingest/faers-live?limit=${limit}&days_back=${daysBack}&recompute=${recompute}`, { method: 'POST' }),
  crawlDailymedRss: (limit = 40, { recompute = true } = {}) =>
    req(`/api/ingest/dailymed-rss?limit=${limit}&recompute=${recompute}`, { method: 'POST' }),
  crawlPubmedLive: (query, limit = 20, { recompute = true } = {}) => {
    const params = new URLSearchParams({ limit: String(limit), recompute: String(recompute) });
    if (query) params.set('query', query);
    return req(`/api/ingest/pubmed-live?${params}`, { method: 'POST' });
  },
  crawlRedditPullpush: (query = 'side effect adverse reaction', { recompute = true } = {}) =>
    req(`/api/ingest/reddit-pullpush?query=${encodeURIComponent(query)}&recompute=${recompute}`, { method: 'POST' }),
  crawlTwitter: (query = 'drug side effect adverse reaction', { recompute = true } = {}) =>
    req(`/api/ingest/twitter?query=${encodeURIComponent(query)}&recompute=${recompute}`, { method: 'POST' }),
  crawlHackerNews: (query, limit = 30, { recompute = true } = {}) => {
    const params = new URLSearchParams({ limit: String(limit), recompute: String(recompute) });
    if (query) params.set('query', query);
    return req(`/api/ingest/hackernews?${params}`, { method: 'POST' });
  },
  crawlLifeScience: (feedId, limit = 50, { recompute = true } = {}) => {
    const params = new URLSearchParams({ limit: String(limit), recompute: String(recompute) });
    if (feedId) params.set('feed_id', feedId);
    return req(`/api/ingest/life-science?${params}`, { method: 'POST' });
  },
  lifeScienceFeeds: () => req('/api/ingest/life-science/feeds'),
  crawlYoutube: (query, limit = 20, { recompute = true } = {}) => {
    const params = new URLSearchParams({ limit: String(limit), recompute: String(recompute) });
    if (query) params.set('query', query);
    return req(`/api/ingest/youtube?${params}`, { method: 'POST' });
  },
  crawlMhraDevices: (limit = 40, { recompute = true } = {}) =>
    req(`/api/ingest/mhra-devices?limit=${limit}&recompute=${recompute}`, { method: 'POST' }),
  crawlMaudeLive: (limit = 30, { recompute = true } = {}) =>
    req(`/api/ingest/maude-live?limit=${limit}&recompute=${recompute}`, { method: 'POST' }),
  lookupEudamed: (device) =>
    req(`/api/device/eudamed?device=${encodeURIComponent(device)}`),
  crawlFdaRss: (feed, { recompute = true } = {}) => {
    const params = new URLSearchParams({ recompute: String(recompute) });
    if (feed) params.set('feed', feed);
    return req(`/api/ingest/fda-rss?${params}`, { method: 'POST' });
  },
  fdaRssFeeds: () => req('/api/ingest/fda-rss/feeds'),
  reset: () => req('/api/reset', { method: 'POST' }),

  // auth
  login: (email, password) => req('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
  register: (email, password, full_name) => req('/api/auth/register', { method: 'POST', body: JSON.stringify({ email, password, full_name }) }),
  me: () => req('/api/auth/me'),
  users: () => req('/api/auth/users'),
  setUserRole: (id, role) => req(`/api/auth/users/${id}/role`, { method: 'PATCH', body: JSON.stringify({ role }) }),

  // forge
  forgeGenerate: (payload) => req('/api/forge/generate', { method: 'POST', body: JSON.stringify(payload) }),
  forgeRecords: (batchId) => req(`/api/forge/records${batchId ? `?batch_id=${batchId}` : ''}`),
  forgeJsonlUrl: (batchId) => `${BASE}/api/forge/export/jsonl${batchId ? `?batch_id=${batchId}` : ''}`,
  forgeCsvUrl: (batchId) => `${BASE}/api/forge/export/csv${batchId ? `?batch_id=${batchId}` : ''}`,

  // FHIR/HL7 ingestion
  ingestFhir: (bundle) => req('/api/ingest/fhir', { method: 'POST', body: JSON.stringify(bundle) }),

  // agentic
  onboardForum: (url, ingest = false) =>
    req('/api/agentic/onboard-forum', {
      method: 'POST',
      body: JSON.stringify({ url, ingest: !!ingest }),
    }),
  agentChat: (message, execute = true) =>
    req('/api/agentic/chat', {
      method: 'POST',
      body: JSON.stringify({ message, execute: !!execute }),
    }),

  ackAlert: (id, action = 'seen', by = 'analyst', notes = '') => {
    const q = new URLSearchParams({ action, by, notes });
    return req(`/api/alerts/${id}/ack?${q}`, { method: 'POST' });
  },
  notifyAlert: (id, { dryRun = false, andInvestigate = true, by = 'analyst' } = {}) => {
    const q = new URLSearchParams({
      dry_run: dryRun ? 'true' : 'false',
      and_investigate: andInvestigate ? 'true' : 'false',
      by,
    });
    return req(`/api/alerts/${id}/notify?${q}`, { method: 'POST' });
  },
  outboundAlerts: () => req('/api/alerts/outbound'),

  // signal review (HCP feedback loop)
  reviewSignal: (id, state, by = 'analyst') =>
    req(`/api/signals/${id}/review?state=${state}&by=${encodeURIComponent(by)}`, { method: 'POST' }),

  // KPIs / quality / audit
  kpis: () => req('/api/kpis'),
  audit: (limit = 100) => req(`/api/audit?limit=${limit}`),

  // surveillance source registry
  surveillanceSources: () => req('/api/surveillance/sources'),

  // pharmacogenomics (PGx) reference table
  pgxReference: () => req('/api/pgx'),

  // FDA boxed (black-box) warning reference table
  boxedWarnings: () => req('/api/boxed-warnings'),

  // mechanistic plausibility (MoA -> AE) reference knowledge base
  mechanismReference: () => req('/api/mechanism'),

  // SMQ (Standardised MedDRA Query) syndrome-level aggregation
  smq: () => req('/api/smq'),

  // class effect (ATC roll-up) + chemical read-across
  classEffect: () => req('/api/class-effect'),

  // vaccine pharmacovigilance (AESI reference + vaccine-signal AESI summary)
  vaccine: () => req('/api/vaccine'),

  // spatial (geographic) cluster detection — Kulldorff-style scan statistic
  spatial: () => req('/api/spatial'),

  // empirical calibration (negative-control null) + E-values
  calibration: () => req('/api/calibration'),

  // UMC vigiGrade-style report-completeness summary (documentation-quality surrogate)
  completeness: () => req('/api/completeness'),

  // labeling-gap detection (novel / in_label / boxed / unknown tier counts + novel list)
  labelGap: () => req('/api/label-gap'),

  // GVP Module IX signal lifecycle management
  updateLifecycle: (id, body) =>
    req(`/api/signals/${id}/lifecycle`, { method: 'PATCH', body: JSON.stringify(body) }),
  lifecycleSummary: () => req('/api/lifecycle/summary'),

  // background monitoring scheduler
  schedulerStatus: () => req('/api/scheduler/status'),
  schedulerStart: ({ interval = 30, mode = 'stream', query = 'drug side effects' } = {}) =>
    req(`/api/scheduler/start?interval=${interval}&mode=${mode}&query=${encodeURIComponent(query)}`, { method: 'POST' }),
  schedulerStop: () => req('/api/scheduler/stop', { method: 'POST' }),

  // streaming ingestion worker (stream-session metadata: session_id, total_posts_ingested, ...)
  streamStatus: () => req('/api/stream/status'),
  streamStart: ({ interval = 15, mode = 'stream', query = 'drug side effects' } = {}) =>
    req(`/api/stream/start?interval=${interval}&mode=${mode}&query=${encodeURIComponent(query)}`, { method: 'POST' }),
  streamStop: () => req('/api/stream/stop', { method: 'POST' }),

  // Agentic pipeline — project workspaces (Steps 1–6)
  pipelineCapabilities: () => req('/api/projects/capabilities'),
  projects: () => req('/api/projects'),
  projectActive: () => req('/api/projects/active'),
  createProject: (body) => req('/api/projects', { method: 'POST', body: JSON.stringify(body) }),
  updateProject: (id, body) => req(`/api/projects/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  seedProject: (id, days = 21) =>
    req(`/api/projects/${id}/seed?days=${days}`, { method: 'POST' }),
  pathfinderRun: (projectId, sync = false) =>
    req(`/api/projects/${projectId}/pathfinder/run${sync ? '-sync' : ''}`, { method: 'POST' }),
  pathfinderRuns: (projectId) => req(`/api/projects/${projectId}/pathfinder/runs`),
  suggestedSources: (projectId, status) => {
    const q = status ? `?status=${encodeURIComponent(status)}` : '';
    return req(`/api/projects/${projectId}/sources/suggested${q}`);
  },
  approveSource: (projectId, sourceId, storageProfile) =>
    req(`/api/projects/${projectId}/sources/${sourceId}/approve`, {
      method: 'POST',
      body: JSON.stringify({ storage_profile: storageProfile || null }),
    }),
  rejectSource: (projectId, sourceId) =>
    req(`/api/projects/${projectId}/sources/${sourceId}/reject`, { method: 'POST' }),
  divergencePairs: (projectId) => req(`/api/projects/${projectId}/divergence/pairs`),
  divergence: (projectId, drug, symptom, days = 90) =>
    req(`/api/projects/${projectId}/divergence?drug=${encodeURIComponent(drug)}&symptom=${encodeURIComponent(symptom)}&days=${days}`),
  storyCandidates: (projectId) => req(`/api/projects/${projectId}/story/candidates`),
  storyCandidatesGlobal: () => req('/api/story/candidates'),
  story: (projectId, event, drugs) =>
    req(`/api/projects/${projectId}/story?event=${encodeURIComponent(event)}&drugs=${encodeURIComponent(drugs)}`),
  storyGlobal: (event, drugs) =>
    req(`/api/story?event=${encodeURIComponent(event)}&drugs=${encodeURIComponent(drugs)}`),
  storyPdfUrl: (projectId, event, drugs) =>
    `${BASE}/api/projects/${projectId}/story/pdf?event=${encodeURIComponent(event)}&drugs=${encodeURIComponent(drugs)}`,
  storyPdfUrlGlobal: (event, drugs) =>
    `${BASE}/api/story/pdf?event=${encodeURIComponent(event)}&drugs=${encodeURIComponent(drugs)}`,
  ingestRegistries: (query = 'adverse event', limitPer = 10) =>
    req(`/api/ingest/registries?query=${encodeURIComponent(query)}&limit_per=${limitPer}`, { method: 'POST' }),
  sparqlGraph: (projectId, { drug = '', symptom = '', region = '', country = '', condition = '', focusNode = null } = {}) => {
    const params = new URLSearchParams();
    if (drug) params.set('drug', drug);
    if (symptom) params.set('symptom', symptom);
    if (region) params.set('region', region);
    if (country) params.set('country', country);
    if (condition) params.set('condition', condition);
    if (focusNode) params.set('focus_node', focusNode);
    const q = params.toString();
    return req(`/api/projects/${projectId}/graph/sparql${q ? `?${q}` : ''}`);
  },
};
