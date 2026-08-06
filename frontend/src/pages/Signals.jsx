import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { useRefresh } from '../App';
import { useProject } from '../projectContext';
import { Badge, Card, Spinner } from '../components/ui';
import SeverityAuditPopover from '../components/SeverityAuditPopover';
import BidirectionalProfilePanel from '../components/views/BidirectionalProfilePanel';

const FILTERS = ['ALL', 'STRONG', 'MODERATE', 'WEAK'];
const REGIONS = ['Global', 'North America', 'Europe', 'Asia', 'South America', 'Africa', 'Oceania'];
const PRODUCTS = ['ALL', 'drug', 'device', 'combination'];
const SORTS = { prr: 'PRR', eb05: 'EB05 (MGPS)', ic025: 'IC025 (BCPNN)', post_count: 'Reports', priority_score: 'Priority Score' };
const NOVELTY_OPTIONS = [
  { value: 'ALL', label: 'All novelty' },
  { value: 'novel', label: '🆕 Novel (not in label)' },
  { value: 'in_label', label: '✓ In label' },
  { value: 'boxed', label: '⬛ Boxed' },
  { value: 'unknown', label: '? Unknown' },
];

export default function Signals({ embedded = false }) {
  const { tick } = useRefresh();
  const { project } = useProject();
  const nav = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [signals, setSignals] = useState(null);
  const [loadError, setLoadError] = useState('');
  const [filter, setFilter] = useState(searchParams.get('strength') || 'ALL');
  const [region, setRegion] = useState(searchParams.get('region') || 'Global');
  const [product, setProduct] = useState('ALL');
  const [drugQ, setDrugQ] = useState(searchParams.get('drug') || '');
  const [symptomQ, setSymptomQ] = useState(searchParams.get('symptom') || '');
  const [socQ, setSocQ] = useState(searchParams.get('soc') || '');
  // Free-text jump box (drug / vaccine / device / event) — debounced into `q`
  const initialQ = searchParams.get('q') || searchParams.get('drug') || '';
  const [searchDraft, setSearchDraft] = useState(initialQ);
  const [textQ, setTextQ] = useState(initialQ);
  const [eventDraft, setEventDraft] = useState(searchParams.get('symptom') || '');
  const [spikingOnly, setSpikingOnly] = useState(false);
  const [sdrOnly, setSdrOnly] = useState(false);
  const [pgxOnly, setPgxOnly] = useState(false);
  const [boxedOnly, setBoxedOnly] = useState(false);
  const [mechanismOnly, setMechanismOnly] = useState(false);
  const [classEffectOnly, setClassEffectOnly] = useState(false);
  const [acOnly, setAcOnly] = useState(false);
  const [calibratedOnly, setCalibratedOnly] = useState(false);
  const [vaccineOnly, setVaccineOnly] = useState(false);
  const [spatialOnly, setSpatialOnly] = useState(false);
  const [wellDocOnly, setWellDocOnly] = useState(false);
  const [hrElevatedOnly, setHrElevatedOnly] = useState(false);
  const [maxsprtOnly, setMaxsprtOnly] = useState(false);
  const [smq, setSmq] = useState(searchParams.get('smq') || 'ALL');
  const [noveltyFilter, setNoveltyFilter] = useState('ALL');
  const [sortBy, setSortBy] = useState('prr');
  const [profile, setProfile] = useState(null); // { mode: 'drug'|'event', query: string }
  // Pin a drug to the top when deep-linking from SMQ (keep full SMQ set visible)
  const [pinDrug, setPinDrug] = useState(searchParams.get('pin') || '');

  // Sync deep-link tokens from Dashboard / SMQ / chart clicks
  useEffect(() => {
    const d = searchParams.get('drug');
    const qParam = searchParams.get('q');
    const pin = searchParams.get('pin');
    const searchEvent = searchParams.get('searchEvent');
    const s = searchParams.get('symptom') || searchEvent;
    const st = searchParams.get('strength');
    const r = searchParams.get('region');
    const soc = searchParams.get('soc');
    const smqParam = searchParams.get('smq');
    const classEffect = searchParams.get('class_effect');
    if (d != null) {
      setDrugQ(d);
      if (!qParam) {
        setSearchDraft(d);
        setTextQ(d);
      }
    }
    if (qParam != null) {
      setSearchDraft(qParam);
      setTextQ(qParam);
    }
    if (pin != null) setPinDrug(pin);
    if (s != null) {
      setSymptomQ(s);
      setEventDraft(s);
    }
    if (st) setFilter(st);
    if (r) setRegion(r);
    if (soc != null) setSocQ(soc);
    if (smqParam) setSmq(smqParam);
    if (classEffect === '1' || classEffect === 'true') setClassEffectOnly(true);
  }, [searchParams]);

  // Debounce free-text jump box → API `q` (and clear dedicated drug filter when using q)
  useEffect(() => {
    const t = setTimeout(() => {
      const next = searchDraft.trim();
      setTextQ(next);
      if (next) setDrugQ(''); // prefer unified q search when typing in the jump box
    }, 280);
    return () => clearTimeout(t);
  }, [searchDraft]);

  useEffect(() => {
    const t = setTimeout(() => setSymptomQ(eventDraft.trim()), 280);
    return () => clearTimeout(t);
  }, [eventDraft]);

  useEffect(() => {
    const params = {};
    if (filter !== 'ALL') params.strength = filter;
    if (region !== 'Global') params.region = region;
    if (spikingOnly) params.spiking = true;
    if (noveltyFilter !== 'ALL') params.label_novelty = noveltyFilter;
    if (textQ) params.q = textQ;
    else if (drugQ) params.drug = drugQ;
    if (symptomQ) params.symptom = symptomQ;
    if (socQ) params.soc = socQ;
    setSignals(null);
    setLoadError('');
    let cancelled = false;
    const load = (attempt = 1) => {
      api.signals(params)
        .then((d) => {
          if (!cancelled) setSignals(d.signals || []);
        })
        .catch((err) => {
          const msg = err?.message || 'Failed to load signals';
          // Neon SSL drops / brief recompute races — one automatic retry.
          if (attempt < 2 && /500|SSL|timeout|gateway/i.test(msg)) {
            setTimeout(() => load(attempt + 1), 1200);
            return;
          }
          if (!cancelled) {
            setSignals([]);
            setLoadError(msg);
          }
        });
    };
    load();
    return () => { cancelled = true; };
  }, [tick, project?.id, filter, region, spikingOnly, noveltyFilter, drugQ, symptomQ, socQ, textQ]);

  const clearStoryContext = () => {
    setDrugQ('');
    setSymptomQ('');
    setSocQ('');
    setPinDrug('');
    setSmq('ALL');
    setClassEffectOnly(false);
    setFilter('ALL');
    setRegion('Global');
    setSearchDraft('');
    setTextQ('');
    setEventDraft('');
    setSearchParams({}, { replace: true });
  };

  // SMQ options derived from the loaded signals' memberships.
  const smqOptions = Object.values(
    (signals || []).reduce((acc, s) => {
      (s.smq || []).forEach((m) => { acc[m.smq] = m.name; });
      return acc;
    }, {})
  );
  const smqKeyByName = (signals || []).reduce((acc, s) => {
    (s.smq || []).forEach((m) => { acc[m.name] = m.smq; });
    return acc;
  }, {});
  const smqLabel = smq !== 'ALL'
    ? (Object.entries(smqKeyByName).find(([, k]) => k === smq)?.[0] || smq)
    : null;

  const pinNorm = (pinDrug || '').trim().toLowerCase();

  // product-type + SDR + SMQ filtering and Bayesian sort are applied client-side.
  const rows = (signals || [])
    .filter((s) => product === 'ALL' || (s.product_type || 'drug') === product)
    .filter((s) => !sdrOnly || s.sdr_flag)
    .filter((s) => !pgxOnly || s.pgx_actionable)
    .filter((s) => !boxedOnly || s.boxed_warning)
    .filter((s) => !mechanismOnly || s.mechanism_plausible)
    .filter((s) => !classEffectOnly || s.class_effect)
    .filter((s) => !acOnly || s.stands_out_in_class)
    .filter((s) => !calibratedOnly || s.calibrated_signal)
    .filter((s) => !vaccineOnly || (s.is_vaccine && s.aesi))
    .filter((s) => !spatialOnly || s.spatial_cluster)
    .filter((s) => !wellDocOnly || s.well_documented)
    .filter((s) => !hrElevatedOnly || s.hr_elevated)
    .filter((s) => !maxsprtOnly || s.maxsprt_crossed)
    .filter((s) => smq === 'ALL' || (s.smq || []).some((m) => m.smq === smq))
    .sort((a, b) => {
      // SMQ deep-link: pinned drug first, then remaining members of the syndrome
      if (pinNorm) {
        const aPin = (a.drug || '').toLowerCase() === pinNorm ? 0 : 1;
        const bPin = (b.drug || '').toLowerCase() === pinNorm ? 0 : 1;
        if (aPin !== bPin) return aPin - bPin;
      }
      // When novelty filter is active, float novel signals to top
      if (noveltyFilter === 'novel') {
        const aNovel = (a.label_novelty === 'novel') ? 0 : 1;
        const bNovel = (b.label_novelty === 'novel') ? 0 : 1;
        if (aNovel !== bNovel) return aNovel - bNovel;
      }
      return (b[sortBy] || 0) - (a[sortBy] || 0);
    });

  return (
    <div className="space-y-4">
      {(drugQ || textQ || symptomQ || socQ || (smq !== 'ALL') || pinDrug) && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-teal-500/30 bg-teal-500/10 px-3 py-2 text-xs text-teal-100">
          <span className="font-medium">Filtered</span>
          {smq !== 'ALL' && (
            <span className="rounded bg-cyan-500/20 px-2 py-0.5">SMQ: {smqLabel || smq}</span>
          )}
          {pinDrug && (
            <span className="rounded bg-amber-500/20 px-2 py-0.5 text-amber-100">pinned: {pinDrug}</span>
          )}
          {textQ && <span className="rounded bg-sky-500/20 px-2 py-0.5">search: {textQ}</span>}
          {!textQ && drugQ && <span className="rounded bg-sky-500/20 px-2 py-0.5">drug: {drugQ}</span>}
          {symptomQ && <span className="rounded bg-rose-500/20 px-2 py-0.5">AE: {symptomQ}</span>}
          {socQ && <span className="rounded bg-violet-500/20 px-2 py-0.5">SOC: {socQ}</span>}
          <button type="button" onClick={clearStoryContext} className="ml-auto text-teal-300 hover:underline">
            Clear
          </button>
        </div>
      )}

      <div className="flex flex-col sm:flex-row gap-2">
        <div className="relative flex-1">
          <input
            type="search"
            value={searchDraft}
            onChange={(e) => setSearchDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                setTextQ(searchDraft.trim());
                if (searchDraft.trim()) setDrugQ('');
              }
            }}
            placeholder="Jump to drug, vaccine, or device… e.g. catheter, lithium, MMR"
            className="w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2.5 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-1 focus:ring-sky-500/60"
            aria-label="Search products"
          />
          {searchDraft && (
            <button
              type="button"
              onClick={() => { setSearchDraft(''); setTextQ(''); setDrugQ(''); }}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-slate-400 hover:text-slate-200 px-1.5 py-0.5"
            >
              Clear
            </button>
          )}
        </div>
        <input
          type="search"
          value={eventDraft}
          onChange={(e) => setEventDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              setSymptomQ(eventDraft.trim());
            }
          }}
          placeholder="Optional: filter by event / AE…"
          className="sm:w-56 rounded-lg bg-slate-900 border border-slate-700 px-3 py-2.5 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-1 focus:ring-sky-500/60"
          aria-label="Search adverse events"
        />
      </div>

      <div className="app-filter-bar justify-between">
        <div className="flex gap-2 flex-wrap">
          {FILTERS.map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                filter === f ? 'bg-sky-600 text-white' : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
              }`}
            >
              {f}
            </button>
          ))}
        </div>
        <div className="app-filter-bar">
          <select value={product} onChange={(e) => setProduct(e.target.value)}
                  className="rounded-lg bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs text-slate-200" title="Product type">
            {PRODUCTS.map((p) => <option key={p} value={p}>{p === 'ALL' ? 'All products' : p}</option>)}
          </select>
          <select value={region} onChange={(e) => setRegion(e.target.value)}
                  className="rounded-lg bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs text-slate-200">
            {REGIONS.map((r) => <option key={r}>{r}</option>)}
          </select>
          <select value={smq} onChange={(e) => setSmq(e.target.value)}
                  className="rounded-lg bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs text-slate-200" title="Standardised MedDRA Query (syndrome)">
            <option value="ALL">All syndromes (SMQ)</option>
            {smqOptions.map((name) => <option key={name} value={smqKeyByName[name]}>{name}</option>)}
          </select>
          <select value={noveltyFilter} onChange={(e) => setNoveltyFilter(e.target.value)}
                  className={`rounded-lg border px-2 py-1.5 text-xs ${noveltyFilter === 'novel' ? 'bg-amber-900/40 border-amber-600/50 text-amber-200' : 'bg-slate-800 border-slate-700 text-slate-200'}`}
                  title="Labeling-gap novelty tier">
            {NOVELTY_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          <select value={sortBy} onChange={(e) => setSortBy(e.target.value)}
                  className="rounded-lg bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs text-slate-200" title="Sort by">
            {Object.entries(SORTS).map(([k, v]) => <option key={k} value={k}>Sort: {v}</option>)}
          </select>
          <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
            <input type="checkbox" checked={sdrOnly} onChange={(e) => setSdrOnly(e.target.checked)}
                   className="accent-rose-500" />
            SDR only
          </label>
          <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
            <input type="checkbox" checked={spikingOnly} onChange={(e) => setSpikingOnly(e.target.checked)}
                   className="accent-violet-500" />
            Spiking only
          </label>
          <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer" title="Genomically-explainable (CPIC/PharmGKB) signals only">
            <input type="checkbox" checked={pgxOnly} onChange={(e) => setPgxOnly(e.target.checked)}
                   className="accent-emerald-500" />
            🧬 PGx-actionable
          </label>
          <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer" title="Drugs carrying an FDA boxed (black-box) warning only">
            <input type="checkbox" checked={boxedOnly} onChange={(e) => setBoxedOnly(e.target.checked)}
                   className="accent-amber-500" />
            ⬛ Boxed-warning
          </label>
          <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer" title="Signals where the drug's mechanism of action plausibly explains the event">
            <input type="checkbox" checked={mechanismOnly} onChange={(e) => setMechanismOnly(e.target.checked)}
                   className="accent-cyan-500" />
            ⚛ Mechanistically plausible
          </label>
          <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer" title="Signals where 2+ drugs in the same ATC class report this event (class effect)">
            <input type="checkbox" checked={classEffectOnly} onChange={(e) => setClassEffectOnly(e.target.checked)}
                   className="accent-teal-500" />
            ⚗ Class effect
          </label>
          <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer" title="Drugs still disproportionate versus other drugs in their own ATC class (active-comparator ROR CI lower bound > 1)">
            <input type="checkbox" checked={acOnly} onChange={(e) => setAcOnly(e.target.checked)}
                   className="accent-fuchsia-500" />
            ◎ Stands out in class
          </label>
          <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer" title="Signals that survive empirical-null calibration against negative controls">
            <input type="checkbox" checked={calibratedOnly} onChange={(e) => setCalibratedOnly(e.target.checked)}
                   className="accent-indigo-500" />
            ✓ Calibrated
          </label>
          <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer" title="Vaccine signals matching an Adverse Event of Special Interest (AESI)">
            <input type="checkbox" checked={vaccineOnly} onChange={(e) => setVaccineOnly(e.target.checked)}
                   className="accent-pink-500" />
            💉 Vaccine AESI
          </label>
          <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer" title="Signals geographically concentrated in a country/region beyond their expected share (spatial cluster)">
            <input type="checkbox" checked={spatialOnly} onChange={(e) => setSpatialOnly(e.target.checked)}
                   className="accent-emerald-500" />
            📍 Geo cluster
          </label>
          <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer" title="Signals whose supporting posts are well-documented (vigiGrade-style completeness ≥ 0.5)">
            <input type="checkbox" checked={wellDocOnly} onChange={(e) => setWellDocOnly(e.target.checked)}
                   className="accent-lime-500" />
            ▤ Well-documented
          </label>
          <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer" title="Signals with an elevated surrogate hazard ratio (Cox PH 95% CI lower bound > 1) — illustrative social-listening surrogate">
            <input type="checkbox" checked={hrElevatedOnly} onChange={(e) => setHrElevatedOnly(e.target.checked)}
                   className="accent-orange-500" />
            ⏱ HR elevated
          </label>
          <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer" title="Signals where the MaxSPRT sequential boundary has been crossed — type-I-error-controlled signal detection over repeated surveillance looks (Kulldorff 2011)">
            <input type="checkbox" checked={maxsprtOnly} onChange={(e) => setMaxsprtOnly(e.target.checked)}
                   className="accent-violet-500" />
            🔔 MaxSPRT crossed
          </label>
        </div>
      </div>

      {!signals ? <Spinner /> : (
        <Card className="overflow-hidden">
          <div className="app-table-scroll">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-slate-400 border-b border-slate-800">
                <th className="px-4 py-3">Product → Event</th>
                <th className="px-4 py-3">PRR</th>
                <th className="px-4 py-3">χ²</th>
                <th className="px-4 py-3" title="MGPS Empirical-Bayes 5% lower bound (≥2 = signal)">EB05</th>
                <th className="px-4 py-3" title="BCPNN Information Component 2.5% lower bound (>0 = signal)">IC025</th>
                <th className="px-4 py-3">Reports</th>
                <th className="px-4 py-3">Strength</th>
                <th className="px-4 py-3">Causality</th>
                <th className="px-4 py-3">Severity</th>
                <th className="px-4 py-3" title="Workflow stage (GVP Module IX under the hood)">Workflow</th>
                <th className="px-4 py-3" title="Composite priority score 0-100 (strength × severity × novelty × velocity × MaxSPRT)">Priority</th>
                <th className="px-4 py-3">Trend</th>
                <th className="px-4 py-3">Profiles</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr>
                  <td colSpan={13} className="px-4 py-8 text-center text-slate-500">
                    {loadError
                      ? `Could not load signals: ${loadError}`
                      : 'No signals for this project. Load the demo corpus or switch workspace.'}
                  </td>
                </tr>
              )}
              {rows.map((s) => {
                const isPinned = pinNorm && (s.drug || '').toLowerCase() === pinNorm;
                return (
                <tr
                  key={s.id}
                  onClick={() => nav(`/signals/${s.id}`)}
                  className={`border-b border-slate-800/50 hover:bg-slate-800/40 cursor-pointer transition ${
                    isPinned ? 'bg-amber-500/5 border-l-2 border-l-amber-400/60' : ''
                  }`}
                >
                  <td className="px-4 py-3">
                    <div className="font-medium text-slate-100 capitalize flex items-center gap-2">
                      {isPinned && (
                        <Badge value="pinned" className="bg-amber-500/15 text-amber-200 border-amber-500/30" />
                      )}
                      {s.spike_flag && <span className="h-2 w-2 rounded-full bg-rose-500 pulse-dot" title="Spiking" />}
                      <span title={(s.product_type || 'drug')}>{(s.product_type === 'device') ? '🩺' : '💊'}</span>
                      {s.drug} <span className="text-slate-500">→</span> {s.meddra?.pt || s.symptom}
                      {s.sdr_flag && <Badge value="SDR" className="bg-rose-500/15 text-rose-300 border-rose-500/30" />}
                      {s.trust_label === 'low' && <Badge value="⚠ Low trust" className="bg-amber-500/15 text-amber-300 border-amber-500/30" title={`Trust score ${s.trust_score?.toFixed(2)} — cohort shows some homogeneity`} />}
                      {s.trust_label === 'sybil' && <Badge value="🚨 Sybil" className="bg-rose-700/20 text-rose-200 border-rose-600/40" title={`Trust score ${s.trust_score?.toFixed(2)} — coordinated posting pattern detected`} />}
                      {s.pgx_actionable && <Badge value="🧬 PGx" className="bg-emerald-500/15 text-emerald-300 border-emerald-500/30" title={s.pgx ? `${s.pgx.gene} ${s.pgx.allele}` : 'Pharmacogenomically actionable'} />}
                      {s.boxed_warning && <Badge value="⬛ Boxed" className="bg-amber-500/15 text-amber-300 border-amber-500/30" title={s.boxed ? `${(s.boxed.topics || []).join('; ')}${s.boxed.covers_event ? ' — covers this event' : ' — different event'}` : 'FDA boxed warning'} />}
                      {s.mechanism_plausible && <Badge value="⚛ Plausible" className="bg-cyan-500/15 text-cyan-200 border-cyan-500/30" title={s.mechanism ? s.mechanism.target_or_moa : 'Mechanistically plausible'} />}
                      {s.class_effect && <Badge value="⚗ Class" className="bg-teal-500/15 text-teal-200 border-teal-500/30" title={s.class_info ? `${s.class_info.class_name}: ${(s.class_info.member_drugs || []).length} drugs` : 'Class effect'} />}
                      {s.stands_out_in_class && <Badge value="◎ In-class" className="bg-fuchsia-500/15 text-fuchsia-200 border-fuchsia-500/30" title={s.active_comparator ? `Active-comparator ROR ${s.active_comparator.ac_ror} (CI ${s.active_comparator.ac_ror_ci?.[0]}–${s.active_comparator.ac_ror_ci?.[1]}) vs other ${s.active_comparator.comparator_class} drugs` : 'Disproportionate even versus same-class comparators'} />}
                      {s.calibrated_signal && <Badge value="✓ Cal" className="bg-indigo-500/15 text-indigo-200 border-indigo-500/30" title={`Survives empirical calibration · E-value ${s.e_value?.toFixed(1) ?? '—'}`} />}
                      {s.spatial_cluster && <Badge value={s.spatial ? `📍 ${s.spatial.hotspot}` : '📍 Geo'} className="bg-emerald-500/15 text-emerald-200 border-emerald-500/30" title={s.spatial ? `Geographic cluster · ${s.spatial.observed} in ${s.spatial.hotspot} vs ${s.spatial.expected?.toFixed(1)} expected · RR ${s.spatial.rr?.toFixed(1)}×` : 'Geographic cluster'} />}
                      {s.is_vaccine && <Badge value={s.aesi ? `💉 ${s.aesi.split(' (')[0]}` : '💉 Vaccine'} className="bg-pink-500/15 text-pink-200 border-pink-500/30" title={s.vaccine ? `${s.vaccine.vaccine_name || 'Vaccine'}${s.vaccine.brighton_level ? ` · Brighton L${s.vaccine.brighton_level}` : ''}${s.vaccine.scri?.ri != null ? ` · SCRI RI ${s.vaccine.scri.ri}` : ''}` : 'Vaccine AESI'} />}
                      {s.completeness != null && (
                        <span className="inline-flex items-center gap-1 text-[10px] font-mono text-slate-400"
                              title={`Report completeness (vigiGrade-style): ${s.completeness.toFixed(2)} — ${s.well_documented ? 'well-documented' : 'poorly documented'}`}>
                          <span className={`h-2 w-2 rounded-full ${s.well_documented ? 'bg-lime-400' : 'bg-slate-600'}`} />
                          ▤ {s.completeness.toFixed(2)}
                        </span>
                      )}
                      {s.hr != null && (
                        <Badge
                          value={`⏱ HR ${s.hr.toFixed(2)}${s.hr_ci ? ` (${s.hr_ci[0].toFixed(2)}–${s.hr_ci[1].toFixed(2)})` : ''}`}
                          className={s.hr_elevated
                            ? 'bg-orange-500/15 text-orange-300 border-orange-500/30'
                            : 'bg-slate-600/20 text-slate-400 border-slate-600/30'}
                          title={`Cox PH surrogate hazard ratio — illustrative social-listening estimate. ${s.hr_elevated ? 'Elevated: 95% CI lower bound > 1.' : 'Not elevated.'}`}
                        />
                      )}
                      {s.maxsprt_crossed && (
                        <Badge
                          value={`🔔 MaxSPRT LLR=${s.maxsprt_llr?.toFixed(2)}`}
                          className="bg-violet-500/15 text-violet-200 border-violet-500/30"
                          title={s.maxsprt?.interpretation || 'MaxSPRT sequential boundary crossed'}
                        />
                      )}
                      {s.label_novelty === 'novel' && (
                        <Badge
                          value="🆕 Novel"
                          className="bg-amber-500/20 text-amber-200 border-amber-500/40"
                          title={s.label_gap?.note || 'Event not found in the current FDA label — warrants priority review'}
                        />
                      )}
                      {s.label_novelty === 'in_label' && (
                        <Badge
                          value="✓ In label"
                          className="bg-slate-600/20 text-slate-400 border-slate-600/30"
                          title={s.label_gap?.note || 'Event already listed in the adverse reactions section'}
                        />
                      )}
                    </div>
                    <div className="text-[10px] text-slate-500 mt-0.5 flex flex-wrap gap-x-2">
                      {s.product_type !== 'device' && s.drug_atc && <span>ATC {s.drug_atc}</span>}
                      {s.product_type === 'device' && s.device_gmdn && <span className="text-amber-400">GMDN/PC {s.device_gmdn}</span>}
                      {s.meddra?.soc && <span className="text-violet-400">{s.meddra.soc}</span>}
                      {s.primary_region && s.primary_region !== 'Global' && <span className="text-emerald-400">📍 {s.primary_region}</span>}
                      {(s.smq || []).slice(0, 2).map((m) => (
                        <span key={m.smq} className="text-cyan-400" title={`SMQ ${m.scope}`}>◈ {m.name.split(' (')[0]}</span>
                      ))}
                    </div>
                    {s.fda_evidence?.available && (
                      <div className="text-[10px] text-emerald-400 mt-0.5">
                        openFDA {String(s.fda_evidence.source || '').includes('maude') ? 'MAUDE' : 'FAERS'}: {s.fda_evidence.report_count.toLocaleString()} reports (+{s.fda_evidence.confidence_boost}%)
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 font-mono text-slate-200">{s.prr?.toFixed(1)}</td>
                  <td className="px-4 py-3 font-mono text-slate-400">{s.chi_square?.toFixed(1)}</td>
                  <td className={`px-4 py-3 font-mono ${s.eb05 >= 2 ? 'text-rose-300' : 'text-slate-400'}`}>{s.eb05?.toFixed(2) ?? '—'}</td>
                  <td className={`px-4 py-3 font-mono ${s.ic025 > 0 ? 'text-rose-300' : 'text-slate-400'}`}>{s.ic025?.toFixed(2) ?? '—'}</td>
                  <td className="px-4 py-3 text-slate-300">{s.post_count}</td>
                  <td className="px-4 py-3"><Badge kind="strength" value={s.strength} /></td>
                  <td className="px-4 py-3"><Badge kind="causality" value={s.who_umc} /></td>
                  <td className="px-4 py-3">
                    <SeverityAuditPopover signalId={s.id} severity={s.severity} />
                  </td>
                  <td className="px-4 py-3">
                    <span className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-medium border whitespace-nowrap ${
                      { new: 'bg-slate-700/40 text-slate-300 border-slate-600/40',
                        under_evaluation: 'bg-sky-500/15 text-sky-300 border-sky-500/30',
                        validated: 'bg-teal-500/15 text-teal-300 border-teal-500/30',
                        prioritized: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
                        assessed: 'bg-violet-500/15 text-violet-300 border-violet-500/30',
                        closed: 'bg-slate-800/40 text-slate-400 border-slate-700/40',
                        rejected: 'bg-rose-500/15 text-rose-300 border-rose-500/30' }[s.lifecycle_status || 'new'] || 'bg-slate-700/40 text-slate-300 border-slate-600/40'
                    }`}>
                      {{
                        new: 'Inbox',
                        under_evaluation: 'Looking into it',
                        validated: 'Looks real',
                        prioritized: 'High priority',
                        assessed: 'Written up',
                        closed: 'Done',
                        rejected: 'Not a concern',
                      }[s.lifecycle_status || 'new'] || (s.lifecycle_status || 'new')}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`font-mono font-bold text-sm tabular-nums ${
                      (s.priority_score || 0) >= 70 ? 'text-rose-400' : (s.priority_score || 0) >= 40 ? 'text-amber-400' : 'text-emerald-400'
                    }`}>{(s.priority_score || 0).toFixed(0)}</span>
                  </td>
                  <td className="px-4 py-3">
                    {s.spike_flag
                      ? <span className="text-rose-400 text-xs font-medium">▲ spike z={s.spike_z}</span>
                      : <span className="text-slate-500 text-xs">{s.trend_score > 0 ? '↗' : '→'} {s.trend_score}</span>}
                  </td>
                  <td className="px-3 py-3" onClick={(e) => e.stopPropagation()}>
                    <div className="flex flex-col gap-1 min-w-[7.5rem]">
                      <button
                        type="button"
                        className="text-[10px] rounded px-2 py-1 border border-sky-600/40 text-sky-300 hover:bg-sky-500/15 text-left"
                        title="Forward: all AEs for this product by severity tier"
                        onClick={() => setProfile({ mode: 'drug', query: s.drug })}
                      >
                        View drug profile
                      </button>
                      <button
                        type="button"
                        className="text-[10px] rounded px-2 py-1 border border-rose-600/40 text-rose-300 hover:bg-rose-500/15 text-left"
                        title="Inverse: all products reporting this event"
                        onClick={() => setProfile({
                          mode: 'event',
                          query: s.meddra?.pt || s.symptom,
                        })}
                      >
                        View event profile
                      </button>
                    </div>
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
          </div>
        </Card>
      )}

      {profile && (
        <BidirectionalProfilePanel
          mode={profile.mode}
          query={profile.query}
          onClose={() => setProfile(null)}
        />
      )}
    </div>
  );
}
