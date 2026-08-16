// Thin API client for the VigilAI backend (worldwide).
// Production (Vercel): leave VITE_API_BASE empty so /api is same-origin and
// vercel.json proxies to Render — works on networks that block onrender.com.
// Local Vite: empty BASE uses the dev proxy → 127.0.0.1:8010.
const BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '');


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

function _errDetail(detail) {
  if (detail == null) return null;
  if (typeof detail === 'string') return detail;
  try { return JSON.stringify(detail); } catch { return String(detail); }
}

async function req(path, opts = {}, _attempt = 1) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  if (_token) headers.Authorization = `Bearer ${_token}`;
  if (_projectId) headers['X-Project-Id'] = _projectId;
  const maxAttempts = opts._maxAttempts || 2;
  let res;
  try {
    res = await fetch(`${BASE}${path}`, { ...opts, headers });
  } catch (err) {
    // Free Render sleeps; first call from a new device often fails mid-wake.
    if (_attempt < maxAttempts) {
      await new Promise((r) => setTimeout(r, 2000 * _attempt));
      return req(path, opts, _attempt + 1);
    }
    const hint = BASE
      ? `Network error talking to API (${BASE}). Wake the API / check firewall, then retry.`
      : 'Network error reaching /api (Vercel→Render proxy). Wake https://vigil-ai-api.onrender.com/api/health then retry.';
    throw new Error(err?.message ? `${hint} [${err.message}]` : hint);
  }
  // Gateway / cold-start responses from Cloudflare↔Render
  if ([502, 503, 520, 521, 522, 524].includes(res.status) && _attempt < maxAttempts) {
    await new Promise((r) => setTimeout(r, 2500 * _attempt));
    return req(path, opts, _attempt + 1);
  }
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const j = await res.json();
      const d = _errDetail(j.detail);
      if (d) msg = d;
    } catch { /* ignore */ }
    if ([502, 503, 504].includes(res.status)) {
      msg = 'API gateway timeout while crawling (Render may still be working). Retry with one source; signals refresh in the background.';
    } else if (
      (res.status === 404 || /not found/i.test(msg))
      && !/could not resolve|resolved as an adverse|query is required/i.test(msg)
    ) {
      msg = 'Endpoint not found on API — hard-refresh the app (Ctrl+Shift+R). If it persists, the Render deploy may be stale.';
    }
    throw new Error(msg);
  }
  const ct = res.headers.get('content-type') || '';
  return ct.includes('application/json') ? res.json() : res.text();
}

/** Ping API so Render free cold-starts before a multi-source Fetch. */
export async function wakeApi(timeoutMs = 90000) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    await req('/api/health', { signal: ctrl.signal, _maxAttempts: 5 });
    return true;
  } catch {
    return false;
  } finally {
    clearTimeout(t);
  }
}

/** Login/register with wake + retries — free Render often needs 15–60s on first hit. */
async function authRequest(path, body) {
  await wakeApi(90000);
  return req(path, {
    method: 'POST',
    body: JSON.stringify(body),
    _maxAttempts: 5,
  });
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
  askCopilot: (id, question) =>
    req(`/api/signals/${id}/copilot/ask`, {
      method: 'POST',
      body: JSON.stringify({ question }),
    }),
  inspectionPortfolio: (limit = 200) => req(`/api/inspection/portfolio?limit=${limit}`),
  inspectionSignal: (id) => req(`/api/inspection/signals/${id}`),
  downloadSjl: async (id) => {
    const headers = {};
    if (_token) headers.Authorization = `Bearer ${_token}`;
    if (_projectId) headers['X-Project-Id'] = _projectId;
    const res = await fetch(`${BASE}/api/inspection/signals/${id}/sjl?fmt=md`, { headers });
    if (!res.ok) throw new Error(`SJL export failed (${res.status})`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `sjl_${id}.md`;
    a.click();
    URL.revokeObjectURL(url);
  },
  governanceCredibility: () => req('/api/governance/credibility'),
  governanceCou: () => req('/api/governance/cou'),
  pgxAssociations: (drug, event = '') =>
    req(`/api/pgx/associations?drug=${encodeURIComponent(drug)}&event=${encodeURIComponent(event)}&offline=true`),
  signalPgxProfile: (id) => req(`/api/signals/${id}/pgx-profile`),
  signalLongitudinalBiologics: (id) => req(`/api/signals/${id}/longitudinal-biologics`),
  signalLotClustering: (id) => req(`/api/signals/${id}/lot-clustering`),
  benefitRiskProact: (drug, event, opts = {}) => {
    const q = new URLSearchParams({
      drug,
      event,
      strength: opts.strength || 'WEAK',
      post_count: String(opts.post_count || 0),
      offline: 'true',
    });
    return req(`/api/benefit-risk/proact?${q}`);
  },
  signalBenefitRiskProact: (id) => req(`/api/signals/${id}/benefit-risk-proact?offline=true`),
  frontiersSummary: () => req('/api/frontiers/summary'),
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
  sarMdUrl: (id) => `${BASE}/api/signals/${id}/sar.md`,
  sarPdfUrl: (id) => `${BASE}/api/signals/${id}/sar.pdf`,
  downloadSar: async (id, drug, event, format = 'pdf') => {
    const headers = {};
    if (_token) headers.Authorization = `Bearer ${_token}`;
    if (_projectId) headers['X-Project-Id'] = _projectId;
    const ext = format === 'md' ? 'md' : 'pdf';
    const res = await fetch(`${BASE}/api/signals/${id}/sar.${ext}`, { headers });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const drugSlug = (drug || 'drug').replace(/\s+/g, '_').toLowerCase().slice(0, 20);
    const eventSlug = (event || 'event').replace(/\s+/g, '_').toLowerCase().slice(0, 20);
    a.href = url;
    a.download = `sar_${drugSlug}_${eventSlug}.${ext}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },
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

  signalMasking: (id) => req(`/api/signals/${id}/masking`),
  signalUnmask: (id, excludeDrugs = []) => {
    const q = new URLSearchParams();
    (excludeDrugs || []).forEach((d) => q.append('exclude_drugs', d));
    const qs = q.toString();
    return req(`/api/signals/${id}/unmask${qs ? `?${qs}` : ''}`);
  },
  remineLab: (params = {}) => {
    const qs = new URLSearchParams(
      Object.entries({ limit: 24, offset: 0, only: 'all', sort: 'impact', ...params })
        .filter(([, v]) => v != null && v !== ''),
    ).toString();
    return req(`/api/remine/lab?${qs}`);
  },
  // GET so read-only viewers can run the sensitivity analysis too
  remineRunPair: (drug, event, excludeDrugs = []) => {
    const q = new URLSearchParams({ drug, event });
    excludeDrugs.forEach((d) => q.append('exclude_drugs', d));
    return req(`/api/remine/run?${q.toString()}`);
  },
  signalCasefile: (id) => req(`/api/signals/${id}/casefile`),
  signalDdi: (id) => req(`/api/signals/${id}/ddi`),
  signalSar: (id) => req(`/api/signals/${id}/sar`),
  ddi: (params = {}) => {
    const q = new URLSearchParams(
      Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== '' && v !== false))
    ).toString();
    return req(`/api/ddi${q ? `?${q}` : ''}`);
  },
  pregnancy: () => req('/api/pregnancy'),
  riskStrata: (params = {}) => {
    const q = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v != null && v !== '')
    ).toString();
    return req(`/api/risk-strata${q ? `?${q}` : ''}`);
  },
  riskStrataPredict: (productId, targetAe, minConfidence = 0.55) =>
    req(
      `/api/risk-strata/predict?product_id=${encodeURIComponent(productId)}`
      + `&target_ae_pt=${encodeURIComponent(targetAe)}`
      + `&min_confidence=${minConfidence}`,
      { method: 'POST' },
    ),
  riskStrataRank: (productId, targetAe, topN = 5, includeExploratory = false) =>
    req(
      `/api/risk-strata/rank?product_id=${encodeURIComponent(productId)}`
      + `&target_ae_pt=${encodeURIComponent(targetAe)}`
      + `&top_n=${topN}`
      + `&include_exploratory=${includeExploratory}`,
    ),
  ontologyExpand: (term, { online = false } = {}) =>
    req(`/api/ontology/expand?term=${encodeURIComponent(term)}&online=${online}`),
  ontologyCompare: (product, { online = false } = {}) =>
    req(`/api/ontology/compare?product=${encodeURIComponent(product)}&online=${online}`),
  ontologyEngineMap: (verbatim, { entityType = 'auto', failureMode = '', online = false } = {}) =>
    req(
      `/api/ontology/engine/map?verbatim=${encodeURIComponent(verbatim)}`
      + `&entity_type=${entityType}&failure_mode=${encodeURIComponent(failureMode)}&online=${online}`,
    ),
  ontologyEngineMeddraChain: (term, { online = false } = {}) =>
    req(`/api/ontology/engine/meddra-chain?term=${encodeURIComponent(term)}&online=${online}`),
  ontologyEngineHierarchy: ({ socCode = '' } = {}) =>
    req(`/api/ontology/engine/hierarchy?soc_code=${encodeURIComponent(socCode)}`),
  ontologyEngineDrugChemical: (term, { online = false } = {}) =>
    req(`/api/ontology/engine/drug-chemical?term=${encodeURIComponent(term)}&online=${online}`),
  ontologyEngineDevice: (term, { failureMode = '' } = {}) =>
    req(
      `/api/ontology/engine/device?term=${encodeURIComponent(term)}`
      + `&failure_mode=${encodeURIComponent(failureMode)}`,
    ),
  ontologyEngineDisproportionality: ({ product = '', minCount = 1, topN = 100 } = {}) =>
    req(
      `/api/ontology/engine/disproportionality?product=${encodeURIComponent(product)}`
      + `&min_count=${minCount}&top_n=${topN}`,
    ),
  ontologyEngineKnowledgeGraph: ({ product = '', limit = 300 } = {}) =>
    req(
      `/api/ontology/engine/knowledge-graph?product=${encodeURIComponent(product)}&limit=${limit}`,
    ),
  ontologyEngineStatus: () => req('/api/ontology/engine/status'),
  searchOmni: (q, { online = false, subset = '', includeAnalytics = true } = {}) =>
    req(
      `/api/search/omni?q=${encodeURIComponent(q)}&online=${online}`
      + `&subset=${encodeURIComponent(subset)}&include_analytics=${includeAnalytics}`,
    ),
  searchResolveBrand: (term, { online = false } = {}) =>
    req(`/api/search/resolve-brand?term=${encodeURIComponent(term)}&online=${online}`),
  searchAutocomplete: (q, { kind = 'drug', limit = 8 } = {}) =>
    req(`/api/search/autocomplete?q=${encodeURIComponent(q)}&kind=${kind}&limit=${limit}`),
  searchUniverseSubset: (term, { subset = '', online = false, topN = 40 } = {}) =>
    req(
      `/api/search/universe-subset?term=${encodeURIComponent(term)}`
      + `&subset=${encodeURIComponent(subset)}&online=${online}&top_n=${topN}`,
    ),
  searchStatus: () => req('/api/search/status'),
  normalizationStatus: () => req('/api/normalization/status'),
  normalizationLink: (term, { topK = 5 } = {}) =>
    req(`/api/normalization/link?term=${encodeURIComponent(term)}&top_k=${topK}`),
  normalizationTrace: (term) =>
    req(`/api/normalization/trace?term=${encodeURIComponent(term)}`),
  normalizationGeo: (location) =>
    req(`/api/normalization/geo?location=${encodeURIComponent(location)}`),
  normalizationNormalize: (clinical, location = '') =>
    req(`/api/normalization/normalize?clinical=${encodeURIComponent(clinical)}&location=${encodeURIComponent(location)}`),
  normalizationAggregate: (mentions) =>
    req('/api/normalization/aggregate', { method: 'POST', body: JSON.stringify({ mentions }) }),
  normalizationEval: () => req('/api/normalization/eval'),
  normalizationExpand: (q, { online = false } = {}) =>
    req(`/api/normalization/expand?q=${encodeURIComponent(q)}&online=${online}`),
  normalizationCorpus: (q, { online = false } = {}) =>
    req(`/api/normalization/corpus?q=${encodeURIComponent(q)}&online=${online}`),
  featureStoreMatrix: ({ productId, targetAe, includeExplainability = false } = {}) => {
    const q = new URLSearchParams();
    if (productId) q.set('product_id', productId);
    if (targetAe) q.set('target_ae_pt', targetAe);
    q.set('include_explainability', String(includeExplainability));
    return req(`/api/feature-store/matrix?${q}`);
  },
  fourGate: (text, { useTransformer = false, useOptionalBionlp = false, discardNearNeutral = true } = {}) =>
    req('/api/nlp/four-gate', {
      method: 'POST',
      body: JSON.stringify({
        text,
        use_transformer: useTransformer,
        use_optional_bionlp: useOptionalBionlp,
        discard_near_neutral: discardNearNeutral,
      }),
    }),
  bioieBenchmark: () => req('/api/nlp/bioie-benchmark'),
  optionalBackends: () => req('/api/nlp/optional-backends'),
  omopStats: () => req('/api/omop/stats'),
  omopSync: ({ limit = 200, aeOnly = true } = {}) =>
    req(`/api/omop/sync?limit=${limit}&ae_only=${aeOnly}`, { method: 'POST' }),
  omopSignalsByRxcui: (rxcui) =>
    req(`/api/v1/signals/${encodeURIComponent(rxcui)}`),
  omopSeedConcepts: () => req('/api/v1/omop/concepts/seed', { method: 'POST' }),
  privacyHygiene: ({ title = '', body = '', author = '' } = {}) =>
    req('/api/privacy/hygiene', {
      method: 'POST',
      body: JSON.stringify({ title, body, author, bump_duplicate: false }),
    }),
  ingestAdapter: (adapter, { limit = 15, query, applyHygiene = true } = {}) => {
    const q = new URLSearchParams({
      limit: String(limit),
      apply_hygiene: String(applyHygiene),
    });
    if (query) q.set('query', query);
    return req(`/api/ingest/adapters/${encodeURIComponent(adapter)}?${q}`, { method: 'POST' });
  },
  ingestPvDemo: ({ recompute = true } = {}) =>
    req(`/api/ingest/pv-demo?recompute=${recompute}`, { method: 'POST' }),

  // demo controls
  seed: (days = 21) => req(`/api/ingest/seed?days=${days}`, { method: 'POST' }),
  recompute: () => req('/api/recompute', { method: 'POST' }),
  streamTick: (n = 3, recompute = false) =>
    req(`/api/stream/tick?n=${n}&recompute=${recompute}`, { method: 'POST' }),
  crawlReddit: (query, { recompute = false } = {}) =>
    req(`/api/ingest/reddit?query=${encodeURIComponent(query)}&recompute=${recompute}`, { method: 'POST' }),
  crawlRedditHealth: (query, { recompute = false } = {}) =>
    req(`/api/ingest/reddit-health?query=${encodeURIComponent(query)}&recompute=${recompute}`, { method: 'POST' }),
  redditHealthSubs: () => req('/api/ingest/reddit-health/subs'),
  crawlGoogleNews: (query, { recompute = false } = {}) => {
    const params = new URLSearchParams({ recompute: String(recompute) });
    if (query) params.set('query', query);
    return req(`/api/ingest/google-news?${params}`, { method: 'POST' });
  },
  googleNewsQueries: () => req('/api/ingest/google-news/queries'),
  crawlFaersLive: (limit = 30, daysBack = 90, { recompute = false } = {}) =>
    req(`/api/ingest/faers-live?limit=${limit}&days_back=${daysBack}&recompute=${recompute}`, { method: 'POST' }),
  crawlVaers: (limit = 40, { recompute = false, forceFixture = false } = {}) =>
    req(`/api/ingest/vaers?limit=${limit}&recompute=${recompute}&force_fixture=${forceFixture}`, { method: 'POST' }),
  crawlFaersBulk: (limit = 50, { recompute = false, forceFixture = false } = {}) =>
    req(`/api/ingest/faers-bulk?limit=${limit}&recompute=${recompute}&force_fixture=${forceFixture}`, { method: 'POST' }),
  crawlDailymedRss: (limit = 40, { recompute = false } = {}) =>
    req(`/api/ingest/dailymed-rss?limit=${limit}&recompute=${recompute}`, { method: 'POST' }),
  crawlPubmedLive: (query, limit = 20, { recompute = false, daysBack = 730 } = {}) => {
    const params = new URLSearchParams({
      limit: String(limit),
      recompute: String(recompute),
      days_back: String(daysBack),
    });
    if (query) params.set('query', query);
    return req(`/api/ingest/pubmed-live?${params}`, { method: 'POST' });
  },
  crawlEuropePmc: (query, limit = 20, { recompute = false } = {}) => {
    const params = new URLSearchParams({ limit: String(limit), recompute: String(recompute) });
    if (query) params.set('query', query);
    return req(`/api/ingest/europe-pmc?${params}`, { method: 'POST' });
  },
  crawlSemanticScholar: (query, limit = 20, { recompute = false } = {}) => {
    const params = new URLSearchParams({ limit: String(limit), recompute: String(recompute) });
    if (query) params.set('query', query);
    return req(`/api/ingest/semantic-scholar?${params}`, { method: 'POST' });
  },
  crawlCochraneCentral: (query, limit = 20, { recompute = false } = {}) => {
    const params = new URLSearchParams({ limit: String(limit), recompute: String(recompute) });
    if (query) params.set('query', query);
    return req(`/api/ingest/cochrane-central?${params}`, { method: 'POST' });
  },
  crawlRedditPullpush: (query = 'side effect adverse reaction', { recompute = false } = {}) =>
    req(`/api/ingest/reddit-pullpush?query=${encodeURIComponent(query)}&recompute=${recompute}`, { method: 'POST' }),
  crawlTwitter: (query = 'drug side effect adverse reaction', { recompute = false } = {}) =>
    req(`/api/ingest/twitter?query=${encodeURIComponent(query)}&recompute=${recompute}`, { method: 'POST' }),
  crawlHackerNews: (query, limit = 30, { recompute = false } = {}) => {
    const params = new URLSearchParams({ limit: String(limit), recompute: String(recompute) });
    if (query) params.set('query', query);
    return req(`/api/ingest/hackernews?${params}`, { method: 'POST' });
  },
  crawlLifeScience: (feedId, limit = 50, { recompute = false } = {}) => {
    const params = new URLSearchParams({ limit: String(limit), recompute: String(recompute) });
    if (feedId) params.set('feed_id', feedId);
    return req(`/api/ingest/life-science?${params}`, { method: 'POST' });
  },
  lifeScienceFeeds: () => req('/api/ingest/life-science/feeds'),
  crawlYoutube: (query, limit = 20, { recompute = false } = {}) => {
    const params = new URLSearchParams({ limit: String(limit), recompute: String(recompute) });
    if (query) params.set('query', query);
    return req(`/api/ingest/youtube?${params}`, { method: 'POST' });
  },
  crawlMhraDevices: (limit = 40, { recompute = false } = {}) =>
    req(`/api/ingest/mhra-devices?limit=${limit}&recompute=${recompute}`, { method: 'POST' }),
  crawlMaudeLive: (limit = 30, { recompute = false } = {}) =>
    req(`/api/ingest/maude-live?limit=${limit}&recompute=${recompute}`, { method: 'POST' }),
  crawlDeviceNews: (limit = 40, { recompute = false } = {}) =>
    req(`/api/ingest/device-news?limit=${limit}&recompute=${recompute}`, { method: 'POST' }),
  crawlDeviceRecalls: (limit = 30, { recompute = false } = {}) =>
    req(`/api/ingest/device-recalls?limit=${limit}&recompute=${recompute}`, { method: 'POST' }),
  reprocess: ({ recompute = false } = {}) =>
    req(`/api/reprocess?recompute=${recompute}`, { method: 'POST' }),
  lookupEudamed: (device) =>
    req(`/api/device/eudamed?device=${encodeURIComponent(device)}`),
  crawlFdaRss: (feed, { recompute = false } = {}) => {
    const params = new URLSearchParams({ recompute: String(recompute) });
    if (feed) params.set('feed', feed);
    return req(`/api/ingest/fda-rss?${params}`, { method: 'POST' });
  },
  fdaRssFeeds: () => req('/api/ingest/fda-rss/feeds'),
  reset: () => req('/api/reset', { method: 'POST' }),

  // auth
  login: (email, password) => authRequest('/api/auth/login', { email, password }),
  register: (email, password, full_name) => authRequest('/api/auth/register', { email, password, full_name }),
  me: () => req('/api/auth/me'),
  users: () => req('/api/auth/users'),
  createUser: ({ email, password, full_name = '', role = 'analyst' }) =>
    req('/api/auth/users', {
      method: 'POST',
      body: JSON.stringify({ email, password, full_name, role }),
    }),
  setUserRole: (id, role) => req(`/api/auth/users/${id}/role`, { method: 'PATCH', body: JSON.stringify({ role }) }),

  // forge
  forgeGenerate: (payload) => req('/api/forge/generate', { method: 'POST', body: JSON.stringify(payload) }),
  forgeRecords: (batchId) => req(`/api/forge/records${batchId ? `?batch_id=${batchId}` : ''}`),
  forgeJsonlUrl: (batchId) => `${BASE}/api/forge/export/jsonl${batchId ? `?batch_id=${batchId}` : ''}`,
  forgeCsvUrl: (batchId) => `${BASE}/api/forge/export/csv${batchId ? `?batch_id=${batchId}` : ''}`,
  /** Wake Render, then download forge export as a file (avoids Cloudflare 520 on cold/dead origin). */
  async forgeDownload(format, batchId) {
    await wakeApi(90000);
    const path = format === 'csv'
      ? `/api/forge/export/csv${batchId ? `?batch_id=${encodeURIComponent(batchId)}` : ''}`
      : `/api/forge/export/jsonl${batchId ? `?batch_id=${encodeURIComponent(batchId)}` : ''}`;
    const headers = {};
    if (_token) headers.Authorization = `Bearer ${_token}`;
    let res;
    let attempt = 0;
    while (attempt < 3) {
      attempt += 1;
      try {
        res = await fetch(`${BASE}${path}`, { headers });
        if (res.ok) break;
        // 520/502/503 from Cloudflare/Render while origin restarts
        if ([502, 503, 520, 521, 522, 524].includes(res.status) && attempt < 3) {
          await new Promise((r) => setTimeout(r, 3000 * attempt));
          continue;
        }
        throw new Error(`Export failed (${res.status})`);
      } catch (err) {
        if (attempt >= 3) throw err;
        await new Promise((r) => setTimeout(r, 3000 * attempt));
      }
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = format === 'csv' ? 'forge_export.csv' : 'forge_export.jsonl';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },

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
  labelFilter: (product, event, { online = false } = {}) =>
    req(`/api/label-filter?product=${encodeURIComponent(product)}&event=${encodeURIComponent(event)}&online=${online}`),
  narrativeCausality: (body) =>
    req('/api/nlp/causality', { method: 'POST', body: JSON.stringify(body) }),
  triangulation: (id) => req(`/api/signals/${id}/triangulation`),
  gvpRegister: ({ limit = 25, offset = 0 } = {}) =>
    req(`/api/gvp/register?limit=${limit}&offset=${offset}`),
  exportPbrerPdfUrl: () => `${BASE}/api/gvp/pbrer.pdf`,
  exportPbrerDocxUrl: () => `${BASE}/api/gvp/pbrer.docx`,

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
  biotechHomepage: (focusDrug) => {
    const params = new URLSearchParams();
    if (focusDrug) params.set('focus_drug', focusDrug);
    const q = params.toString();
    return req(`/api/biotech/homepage${q ? `?${q}` : ''}`);
  },
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
