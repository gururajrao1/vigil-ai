/** Client-side layout when /api/biotech/homepage is not yet on the API host. */

function pickSpotlight(signals, focusDrug) {
  const list = Array.isArray(signals) ? signals : [];
  const scoped = focusDrug
    ? list.filter((s) => (s.drug || '').toLowerCase().includes(focusDrug.toLowerCase()))
    : list;
  const pool = scoped.length ? scoped : list;
  const strong = pool.filter((s) => (s.strength || '').toUpperCase() === 'STRONG');
  const ranked = (strong.length ? strong : pool)
    .slice()
    .sort((a, b) => (b.prr || 0) - (a.prr || 0));
  return ranked[0] || null;
}

function spotlightNode(sig, focusDrug) {
  if (!sig) {
    return {
      eyebrow: 'Signal narrative · waiting on corpus',
      headline: 'Load a workspace corpus to illuminate the first anomaly story',
      narrative:
        'When social-listening posts clear the 4-gate AE detector, VigilAI frames the pair as an editorial spotlight — prose first, math as flags.',
      drug: '—',
      event: '—',
      flags: [],
      provenance_note: 'Live unstructured pipeline · no pair in scope yet',
      focus_drug: focusDrug || null,
    };
  }
  const drug = sig.drug || 'product';
  const event = sig.meddra?.pt || sig.symptom || 'event';
  const flags = [];
  if (sig.prr != null) flags.push({ key: 'PRR', value: Number(sig.prr).toFixed(2), tone: 'mint' });
  if (sig.eb05 != null) flags.push({ key: 'EB05', value: Number(sig.eb05).toFixed(2), tone: 'sky' });
  if (sig.ror != null) flags.push({ key: 'ROR', value: Number(sig.ror).toFixed(2), tone: 'mint' });
  flags.push({ key: 'N', value: String(sig.post_count || 0), tone: 'neutral' });
  flags.push({ key: 'TIER', value: sig.strength || '—', tone: 'sky' });
  return {
    eyebrow: 'Signal narrative spotlight',
    headline: `${drug} → ${event}`,
    narrative: `In the current workspace, ${drug} and ${event} form a disproportionate product–event pair. This card is an editorial frame — not a spreadsheet cell.`,
    patient_voice: `Across patient-voice threads, ${(event || '').toLowerCase()} recurs in proximity to ${drug}.`,
    drug,
    event,
    flags,
    href: sig.id != null ? `/signals/${sig.id}` : '/signals',
    provenance_note:
      'Stats from live unstructured pipeline DMA. Comparative FAERS/MAUDE cells elsewhere use local surrogates — not live VigiBase or Sentinel.',
    focus_drug: focusDrug || null,
  };
}

export function buildFallbackHomepage({ stats = {}, signals = [], focusDrug } = {}) {
  const posts = stats.total_posts || 0;
  const ae = stats.ae_posts || 0;
  const signalCount = stats.signal_count || (signals || []).length || 0;
  const spot = spotlightNode(pickSpotlight(signals, focusDrug), focusDrug);

  return {
    schema_version: 'vigilai.biotech_homepage.v1',
    generated_at: new Date().toISOString(),
    focus_drug: focusDrug || null,
    meta: {
      fallback: true,
      note: 'Composed client-side from /api/dashboard/stats + /api/signals (biotech route pending API redeploy).',
      spatial: {
        nav: 'top-editorial',
        hero: 'manifesto-cinematic',
        pillars: 'four-gate-blocks',
        swimlane: 'pipeline-horizontal',
        spotlight: 'prose-editorial',
      },
    },
    navigation: {
      brand: 'VigilAI',
      wordmark_sub: 'Computational pharmacovigilance',
      env_tags: ['OFFLINE-FIRST', 'SURROGATE BENCHMARKS', 'WORLDWIDE'],
      items: [
        { id: 'mission', label: 'Mission', href: '/#manifesto' },
        { id: 'tech', label: 'Technology', href: '/#pillars' },
        { id: 'signal', label: 'Spotlight', href: '/#spotlight' },
        { id: 'platform', label: 'Login', href: '/login', emphasis: true },
      ],
    },
    hero_manifesto: {
      eyebrow: 'Post-market safety · patient voice at computational scale',
      title: 'See the signal before the spreadsheet.',
      lede:
        'VigilAI is a life-sciences listening engine — unstructured patient narratives become disproportionality stories with honest provenance.',
      body:
        'We fuse a 4-gate adverse-event detector, offline-first NLP, and Bayesian screens (PRR · EB05 · IC025) into an editorial workspace. Comparative registry math runs on local reference surrogates — never a fake live pipe into VigiBase or Sentinel.',
      env_tags: ['LIVE LOCAL STREAM', 'OPENFDA SURROGATE CACHE', 'PHARMACOVIGILANCE'],
      throughput: [
        { label: 'Stream throughput', value: String(posts), unit: 'docs', provenance: 'live_unstructured_pipeline' },
        { label: 'AE-gated yield', value: String(ae), unit: 'posts', provenance: 'live_unstructured_pipeline' },
        { label: 'Active pairs', value: String(signalCount), unit: 'signals', provenance: 'live_unstructured_pipeline' },
      ],
      primary_cta: { label: 'Login', href: '/login' },
      secondary_cta: undefined,
    },
    technology_pillars: [
      {
        id: 'gate1',
        gate: 'GATE 01',
        title: 'Product entity lock',
        narrative:
          'Normalize drugs and devices to generic / GMDN-style codes before any AE claim is admitted — brand noise never opens the gate alone.',
        accent: 'mint',
      },
      {
        id: 'gate2',
        gate: 'GATE 02',
        title: 'Symptom · malfunction map',
        narrative:
          'Lay language collapses onto MedDRA-style Preferred Terms (open surrogate coding) so patient slang and device failures share one ontology.',
        accent: 'sky',
      },
      {
        id: 'gate3',
        gate: 'GATE 03',
        title: 'Negative sentiment pressure',
        narrative:
          'Only negatively oriented narratives continue — praise and neutral chatter never inflate the disproportionality table.',
        accent: 'mint',
      },
      {
        id: 'gate4',
        gate: 'GATE 04',
        title: 'Non-negated clinical claim',
        narrative:
          'Negation and speculation are stripped. Surviving text enters DMA with full gate traces — explainable, offline-capable, key-optional.',
        accent: 'sky',
      },
    ],
    pipeline_swimlane: [
      { id: 'ingest', label: 'Ingest', detail: 'Social · RSS · forge streams', state: posts ? 'active' : 'idle' },
      { id: 'sanitize', label: 'Sanitize', detail: 'PII scrub · locale fold', state: posts ? 'active' : 'ready' },
      { id: 'gates', label: '4-Gate AE', detail: 'Entity · symptom · sentiment · negation', state: ae ? 'active' : 'ready' },
      { id: 'dma', label: 'DMA', detail: 'PRR · ROR · EB05 · IC025', state: signalCount ? 'active' : 'ready' },
      { id: 'narrative', label: 'Narrative', detail: 'Spotlight · workflow · E2B demo', state: spot.drug !== '—' ? 'active' : 'idle' },
    ],
    signal_spotlight: spot,
    honesty: {
      title: 'Data integrity',
      live_pipeline:
        'Unstructured patient content is ingested and scored inside your workspace. Throughput numbers above reflect that live local pipeline.',
      surrogate_benchmarks:
        'Comparative historical lookups use local reference surrogate copies. They are benchmarks — not direct live queries to closed global registries.',
      never_claim: [
        'Live WHO VigiBase / VigiLyze pipe',
        'Live FDA Sentinel multi-center feed',
        'Licensed MedDRA subscription sync',
      ],
    },
    cta_strip: {
      title: 'From manifesto to workbench',
      body: 'Keep the editorial stage for storytelling. Enter the platform for detection, lenses, and evidence.',
      buttons: [
        { label: 'Dashboard', href: '/dashboard' },
        { label: 'Safety Signals', href: '/signals' },
        { label: 'Analytic Lenses', href: '/lenses' },
      ],
    },
    actions: [
      { id: 'forge_tick', label: 'Forge simulation pulse', kind: 'forge_sim', payload: { n: 5 } },
      { id: 'recompute', label: 'Recompute pairs', kind: 'recompute', payload: {} },
    ],
    disclaimer: '',
  };
}
