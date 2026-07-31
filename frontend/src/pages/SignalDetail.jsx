import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { api } from '../api';
import { Badge, Button, Card, CardHeader, Spinner } from '../components/ui';
import SourceTraceability from '../components/ui/SourceTraceability';
import SeverityAuditPopover from '../components/SeverityAuditPopover';

// vigiGrade-style completeness dimensions (labels mirror app/analytics/completeness.py).
const COMPLETENESS_DIMS = [
  ['entities_present', 'Drug + event identifiable'],
  ['indication', 'Indication / condition'],
  ['time_to_onset', 'Time-to-onset cue'],
  ['outcome_seriousness', 'Outcome / seriousness'],
  ['dechallenge', 'Dechallenge cue'],
  ['rechallenge', 'Rechallenge cue'],
  ['patient_descriptors', 'Patient descriptors (age/sex)'],
  ['dose', 'Dose / regimen'],
  ['free_text', 'Sufficient free text'],
  ['country_known', 'Country known'],
  ['sentiment_severity', 'Sentiment / severity signal'],
];

function Metric({ label, value, hint, accent = 'text-slate-100', ci }) {
  return (
    <Card className="p-3" >
      <div className="flex items-center gap-1 text-xs text-slate-400" title={hint}>
        {label}
        {hint && <span className="text-slate-600 cursor-help">ⓘ</span>}
      </div>
      <div className={`text-2xl font-bold font-mono ${accent}`}>{value}</div>
      {ci && <div className="text-[10px] text-slate-500 mt-0.5">95% CI {ci}</div>}
    </Card>
  );
}

function GateTrace({ gates, explainability }) {
  const list = Array.isArray(gates)
    ? gates
    : (Array.isArray(gates?.ae_gates) ? gates.ae_gates : []);
  if (!list.length) {
    return <div className="text-xs text-slate-500">No gate trace recorded.</div>;
  }
  return (
    <div className="space-y-1.5">
      {list.map((g) => {
        const key = `gate_${g.gate}`;
        const exp = explainability?.[key];
        const count = g.count ?? exp?.count;
        const items = g.items ?? exp?.items;
        return (
          <div key={g.gate} className="text-xs">
            <div className="flex items-center gap-2 flex-wrap">
              <span className={`h-4 w-4 rounded flex items-center justify-center text-[10px] font-bold shrink-0 ${
                (g.status ?? g.passed) ? 'bg-emerald-500/20 text-emerald-300' : 'bg-rose-500/20 text-rose-300'
              }`}>{(g.status ?? g.passed) ? '✓' : '✕'}</span>
              <span className="text-slate-300 font-medium">Gate {g.gate}: {g.name}</span>
              {count != null && (
                <span className="text-slate-500 tabular-nums">· n={count}</span>
              )}
              <span className="text-slate-500">— {g.detail}</span>
            </div>
            {Array.isArray(items) && items.length > 0 && (
              <div className="pl-6 mt-0.5 text-[10px] text-slate-500 truncate" title={items.map((x) => (typeof x === 'string' ? x : JSON.stringify(x))).join(', ')}>
                {items.slice(0, 8).map((x) => (typeof x === 'string' ? x : x?.label || x?.concept || JSON.stringify(x))).join(' · ')}
                {items.length > 8 ? ` · +${items.length - 8}` : ''}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// Collapsible section helper used inside CopilotPanel
function AssessSection({ title, icon, children, accent = 'indigo', defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  const colours = {
    indigo: 'border-indigo-600/25 text-indigo-300 hover:bg-indigo-500/5',
    rose: 'border-rose-600/25 text-rose-300 hover:bg-rose-500/5',
    amber: 'border-amber-600/25 text-amber-300 hover:bg-amber-500/5',
    violet: 'border-violet-600/25 text-violet-300 hover:bg-violet-500/5',
    sky: 'border-sky-600/25 text-sky-300 hover:bg-sky-500/5',
    teal: 'border-teal-600/25 text-teal-300 hover:bg-teal-500/5',
    emerald: 'border-emerald-600/25 text-emerald-300 hover:bg-emerald-500/5',
  };
  const c = colours[accent] || colours.indigo;
  return (
    <div className={`rounded-lg border ${c.split(' ')[0]} bg-slate-950/30`}>
      <button
        onClick={() => setOpen((o) => !o)}
        className={`w-full flex items-center justify-between px-3 py-2 text-xs font-medium uppercase tracking-wide ${c.split(' ').slice(1).join(' ')} transition-colors`}
      >
        <span>{icon} {title}</span>
        <span className="text-slate-500 text-[10px]">{open ? '▲ collapse' : '▼ expand'}</span>
      </button>
      {open && (
        <div className="px-3 pb-3 pt-1 text-sm text-slate-200 leading-relaxed border-t border-slate-800/60">
          {children}
        </div>
      )}
    </div>
  );
}

function CopilotPanel({ sig, assessment, assessing, onDraft, recClass }) {
  // Bootstrap with any already-persisted assessment
  const displayAssessment = assessment || sig.copilot;
  const recLabel = { escalate: '🔴 Escalate', monitor: '🟡 Monitor', close: '⚪ Close' };

  return (
    <Card className="p-4 border-indigo-700/40 bg-indigo-500/[0.04]">
      <CardHeader
        title="🤖 Safety-Scientist Copilot"
        subtitle="RAG-based structured signal-assessment memo grounded exclusively in this signal's computed evidence. Draft for analyst review."
        right={
          <Button variant="ghost" disabled={assessing} onClick={onDraft}
                  className="text-indigo-300 border-indigo-600/40 hover:bg-indigo-500/10">
            {assessing
              ? <><Spinner className="inline h-3 w-3 mr-1" />Drafting…</>
              : (displayAssessment ? '↻ Re-draft' : '🤖 Draft Assessment')}
          </Button>
        }
      />

      {!displayAssessment && !assessing && (
        <p className="mt-3 text-sm text-slate-400">
          Click <strong className="text-indigo-300">Draft Assessment</strong> to generate a structured
          pharmacovigilance memo — Signal Summary, Statistical Evidence, Causality, Clinical Context,
          Regulatory Context, Benefit-Risk, and Recommendation — grounded strictly in the signal&apos;s
          own computed evidence. Uses the local Ollama LLM when available; falls back to a
          deterministic template offline.
        </p>
      )}

      {assessing && (
        <div className="mt-4 flex items-center gap-3 text-sm text-slate-400">
          <Spinner className="h-4 w-4" />
          <span>Retrieving context &amp; drafting structured memo… (may take 15–60 s with Ollama)</span>
        </div>
      )}

      {displayAssessment && !assessing && (
        <div className="mt-3 space-y-3">
          {/* Header badges */}
          <div className="flex flex-wrap items-center gap-2">
            <Badge
              value={recLabel[displayAssessment.recommendation] || displayAssessment.recommendation}
              className={recClass(displayAssessment.recommendation)}
            />
            <Badge
              value={`source: ${displayAssessment.source || sig.copilot_source || 'deterministic'}`}
              className="bg-slate-700/40 text-slate-300 border-slate-600/40 text-[10px]"
            />
          </div>

          {/* Recommendation rationale — always visible */}
          <div className="rounded-lg border border-indigo-600/25 bg-slate-950/40 px-3 py-2">
            <div className="text-[11px] uppercase tracking-wide text-indigo-300 mb-1">Recommendation rationale</div>
            <p className="text-sm text-slate-100 font-medium leading-relaxed">
              {displayAssessment.recommendation_rationale}
            </p>
          </div>

          {/* Collapsible memo sections */}
          <AssessSection title="Signal Summary" icon="📋" accent="indigo" defaultOpen>
            {displayAssessment.signal_summary}
          </AssessSection>

          <AssessSection title="Statistical Evidence" icon="📊" accent="sky">
            {displayAssessment.statistical_evidence}
          </AssessSection>

          <AssessSection title="Causality Assessment" icon="⚖️" accent="violet">
            {displayAssessment.causality_assessment}
          </AssessSection>

          <AssessSection title="Clinical Context (PGx / Mechanism / Class)" icon="🧬" accent="teal">
            {displayAssessment.clinical_context}
          </AssessSection>

          <AssessSection title="Regulatory Context (Label / FAERS / Recalls)" icon="📜" accent="amber">
            {displayAssessment.regulatory_context}
          </AssessSection>

          <AssessSection title="Benefit-Risk" icon="⚖" accent="rose">
            {displayAssessment.benefit_risk}
          </AssessSection>

          {/* Disclaimer */}
          <p className="text-[10px] text-slate-600 leading-snug pt-1 border-t border-slate-800/50">
            {displayAssessment.disclaimer}
          </p>
        </div>
      )}
    </Card>
  );
}

function highlight(text, entities) {
  // Delegates to SourceTraceability — cleans scrape spacing then remaps offsets
  return <SourceTraceability text={text} entities={entities} />;
}

const LIFECYCLE_VALID_NEXT = {
  new:              ['under_evaluation', 'rejected'],
  under_evaluation: ['validated', 'rejected'],
  validated:        ['prioritized', 'rejected'],
  prioritized:      ['assessed', 'rejected'],
  assessed:         ['closed', 'rejected'],
  closed:           [],
  rejected:         [],
};

const LC_STATE_LABELS = {
  new: 'Inbox',
  under_evaluation: 'Looking into it',
  validated: 'Looks real',
  prioritized: 'High priority',
  assessed: 'Written up',
  closed: 'Done',
  rejected: 'Not a concern',
};

const LC_STATE_COLORS = {
  new:              'bg-slate-700/40 text-slate-300 border-slate-600/40',
  under_evaluation: 'bg-sky-500/15 text-sky-300 border-sky-500/30',
  validated:        'bg-teal-500/15 text-teal-300 border-teal-500/30',
  prioritized:      'bg-amber-500/15 text-amber-300 border-amber-500/30',
  assessed:         'bg-violet-500/15 text-violet-300 border-violet-500/30',
  closed:           'bg-slate-800/40 text-slate-400 border-slate-700/40',
  rejected:         'bg-rose-500/15 text-rose-300 border-rose-500/30',
};

function LifecyclePanel({ sig, onUpdated }) {
  const [advancing, setAdvancing] = useState(false);
  const [toState, setToState] = useState('');
  const [owner, setOwner] = useState(sig.lifecycle_owner || '');
  const [notes, setNotes] = useState('');
  const [err, setErr] = useState('');
  const [showForm, setShowForm] = useState(false);

  const currentStatus = sig.lifecycle_status || 'new';
  const nextStates = LIFECYCLE_VALID_NEXT[currentStatus] || [];
  const score = sig.priority_score || 0;
  const scoreColor = score >= 70 ? 'text-rose-400' : score >= 40 ? 'text-amber-400' : 'text-emerald-400';
  const scoreBg   = score >= 70 ? 'bg-rose-500' : score >= 40 ? 'bg-amber-500' : 'bg-emerald-500';

  const advance = async () => {
    if (!toState) return;
    setAdvancing(true); setErr('');
    try {
      const updated = await api.updateLifecycle(sig.id, { status: toState, owner, notes: notes || undefined });
      onUpdated(updated);
      setShowForm(false); setNotes(''); setToState('');
    } catch (e) { setErr(e.message || 'Transition failed'); }
    setAdvancing(false);
  };

  return (
    <Card className="p-4 border-teal-700/40 bg-teal-500/[0.03]">
      <CardHeader title="Workflow status" subtitle="Same stages as the Workflow board · priority · owner · audit trail" />

      <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Status */}
        <div className="rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2">
          <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1.5">Status</div>
          <span className={`inline-block rounded-full px-3 py-1 text-xs font-medium border ${LC_STATE_COLORS[currentStatus] || 'bg-slate-700/40 text-slate-300 border-slate-600/40'}`}>
            {LC_STATE_LABELS[currentStatus] || currentStatus}
          </span>
          {sig.lifecycle_updated_at && (
            <div className="text-[10px] text-slate-600 mt-1">{sig.lifecycle_updated_at.slice(0, 16).replace('T', ' ')}</div>
          )}
        </div>

        {/* Priority score */}
        <div className="rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2">
          <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1.5">Priority Score</div>
          <div className={`text-3xl font-bold font-mono ${scoreColor}`}>{score.toFixed(0)}<span className="text-sm font-normal text-slate-500">/100</span></div>
          <div className="mt-1.5 bg-slate-800 rounded-full h-1.5">
            <div className={`h-1.5 rounded-full ${scoreBg}`} style={{ width: `${Math.min(100, score)}%` }} />
          </div>
        </div>

        {/* Owner */}
        <div className="rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2">
          <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1.5">Owner</div>
          {sig.lifecycle_owner
            ? <div className="text-sm text-slate-200 flex items-center gap-1.5">👤 {sig.lifecycle_owner}</div>
            : <div className="text-sm text-slate-500">Unassigned</div>}
        </div>
      </div>

      {/* Notes */}
      {sig.lifecycle_notes && (
        <div className="mt-3 rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2">
          <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1">Notes</div>
          <div className="text-sm text-slate-300 leading-relaxed">{sig.lifecycle_notes}</div>
        </div>
      )}

      {/* Advance / Reject buttons */}
      {nextStates.length > 0 && (
        <div className="mt-4">
          {!showForm ? (
            <div className="flex items-center gap-2 flex-wrap">
              {nextStates.filter((s) => s !== 'rejected').map((s) => (
                <button key={s} onClick={() => { setToState(s); setShowForm(true); }}
                  className="rounded-lg px-3 py-1.5 text-xs font-medium bg-teal-600/20 hover:bg-teal-600/30 text-teal-300 border border-teal-600/30 transition-colors">
                  Move → {LC_STATE_LABELS[s] || s}
                </button>
              ))}
              {nextStates.includes('rejected') && (
                <button onClick={() => { setToState('rejected'); setShowForm(true); }}
                  className="rounded-lg px-3 py-1.5 text-xs font-medium bg-rose-600/15 hover:bg-rose-600/25 text-rose-300 border border-rose-600/25 transition-colors">
                  Not a concern
                </button>
              )}
            </div>
          ) : (
            <div className="rounded-lg border border-slate-700 bg-slate-900/60 p-3 space-y-3">
              <div className="text-sm text-slate-300">
                Move to <span className={`font-medium ${toState === 'rejected' ? 'text-rose-300' : 'text-teal-300'}`}>{LC_STATE_LABELS[toState] || toState}</span>
              </div>
              <input type="text" value={owner} onChange={(e) => setOwner(e.target.value)} placeholder="Owner (who is handling this)"
                className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm text-slate-100 placeholder:text-slate-600 focus:outline-none focus:border-teal-600" />
              <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} placeholder="Notes (optional)"
                className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm text-slate-100 placeholder:text-slate-600 focus:outline-none focus:border-teal-600 resize-none" />
              {err && <div className="text-rose-400 text-xs">{err}</div>}
              <div className="flex gap-2">
                <button onClick={() => { setShowForm(false); setErr(''); }} className="px-3 py-1 rounded-lg border border-slate-700 text-slate-400 hover:bg-slate-800 text-xs">Cancel</button>
                <button disabled={advancing} onClick={advance}
                  className={`px-3 py-1 rounded-lg text-xs font-medium transition disabled:opacity-50 ${toState === 'rejected' ? 'bg-rose-600/30 text-rose-200 border border-rose-600/40 hover:bg-rose-600/40' : 'bg-teal-600/30 text-teal-200 border border-teal-600/40 hover:bg-teal-600/40'}`}>
                  {advancing ? 'Saving…' : 'Confirm'}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

function AuditButton({ signalId }) {
  const [audit, setAudit] = useState(null);
  const [loading, setLoading] = useState(false);

  const verify = async () => {
    setLoading(true);
    try { setAudit(await api.signalAudit(signalId)); }
    catch { setAudit({ error: true }); }
    setLoading(false);
  };

  if (!audit) return (
    <button type="button" onClick={verify} disabled={loading}
      className="text-xs rounded-lg px-2.5 py-1.5 border border-slate-700 bg-slate-900/60 text-slate-400 hover:text-slate-200 hover:border-slate-600 transition-colors">
      {loading ? '🔐 Verifying…' : '🔐 Verify chain'}
    </button>
  );
  if (audit.error) return <span className="text-xs text-rose-400">✗ Audit failed</span>;
  const ok = audit.verification?.valid;
  return (
    <span title={`Ed25519 envelope · hash: ${audit.envelope?.content_hash?.slice(0,12)}…`}
      className={`text-xs rounded-lg px-2.5 py-1.5 border ${ok ? 'border-emerald-700/50 bg-emerald-900/20 text-emerald-300' : 'border-rose-700/50 bg-rose-900/20 text-rose-300'}`}>
      {ok ? '✓ Chain verified' : '✗ Chain broken'}
    </span>
  );
}

export default function SignalDetail() {
  const { id } = useParams();
  const [sig, setSig] = useState(null);
  const [regen, setRegen] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [assessment, setAssessment] = useState(null);
  const [assessing, setAssessing] = useState(false);
  const [ciomsDl, setCiomsDl] = useState(false);
  const [sarDl, setSarDl] = useState(false);
  const [masking, setMasking] = useState(null);
  const [unmask, setUnmask] = useState(null);
  const [unmasking, setUnmasking] = useState(false);
  const [unmaskErr, setUnmaskErr] = useState(null);
  const [casefile, setCasefile] = useState(null);
  const [ddi, setDdi] = useState(null);
  const [sarPreview, setSarPreview] = useState(null);
  const [selectedMaskers, setSelectedMaskers] = useState([]);
  const [pvDemoBusy, setPvDemoBusy] = useState(false);

  useEffect(() => {
    api.signal(id).then(setSig).catch(() => setSig(null));
    setAssessment(null);
    setUnmask(null);
    setUnmaskErr(null);
    setMasking(null);
    setCasefile(null);
    setDdi(null);
    setSarPreview(null);
    setSelectedMaskers([]);
    api.signalMasking(id).then((m) => {
      setMasking(m);
      setSelectedMaskers(m.suggested_exclude || (m.maskers || []).filter((x) => x.likely_masker).map((x) => x.drug));
    }).catch(() => setMasking(null));
    api.signalCasefile(id).then(setCasefile).catch(() => setCasefile(null));
    api.signalDdi(id).then(setDdi).catch(() => setDdi(null));
    api.signalSar(id).then(setSarPreview).catch(() => setSarPreview(null));
  }, [id]);

  if (!sig) return <Spinner label="Loading signal…" />;

  const fda = sig.fda_evidence || {};
  const label = sig.label_evidence || {};
  const recall = sig.recall || {};
  const lit = sig.literature || {};
  const dc = sig.device_classification || {};
  const pgx = sig.pgx_actionable ? sig.pgx : null;
  const boxed = sig.boxed_warning ? sig.boxed : null;
  const labelGap = sig.label_gap || null;
  const mechanism = sig.mechanism_plausible ? sig.mechanism : null;
  const classInfo = sig.class_effect ? sig.class_info : null;
  const ac = (sig.active_comparator && sig.active_comparator.comparator_class) ? sig.active_comparator : null;
  const readAcross = (sig.read_across || []).filter((r) => r.analog_has_same_event);
  const vaccine = sig.is_vaccine ? sig.vaccine : null;
  const brightonClass = (lvl) => (lvl === 1
    ? 'bg-rose-500/15 text-rose-300 border-rose-500/30'
    : lvl === 2
      ? 'bg-amber-500/15 text-amber-300 border-amber-500/30'
      : 'bg-slate-600/20 text-slate-300 border-slate-600/30');
  const calib = sig.calibration || null;
  const spatial = sig.spatial_cluster ? sig.spatial : null;
  const completeness = sig.completeness_detail || null;
  const hrDetail = sig.hr_detail || null;
  const maxsprt = sig.maxsprt || null;
  const md = sig.meddra || {};
  const regions = Object.entries(sig.regions || {}).sort((a, b) => b[1] - a[1]);
  const isDevice = (sig.product_type || 'drug') === 'device';
  const evidenceName = String(fda.source || '').includes('maude') ? 'MAUDE' : 'FAERS';
  const ci = (lo, hi) => (lo != null && hi != null ? `${lo.toFixed(2)}–${hi.toFixed(2)}` : null);
  const fmt = (v, d = 2) => (v === null || v === undefined ? '—' : v.toFixed(d));

  const review = async (state) => {
    setReviewing(true);
    try { await api.reviewSignal(sig.id, state); setSig({ ...sig, review_state: state }); }
    catch (e) { console.error(e); }
    setReviewing(false);
  };

  const regenerate = async () => {
    setRegen(true);
    try { const r = await api.regenerateNarrative(sig.id); setSig({ ...sig, narrative: r.narrative, narrative_source: r.source }); }
    catch (e) { console.error(e); }
    setRegen(false);
  };

  const runAssessment = async () => {
    setAssessing(true);
    try { setAssessment(await api.draftAssessment(sig.id)); }
    catch (e) { console.error(e); }
    setAssessing(false);
  };
  const recClass = (rec) => (
    rec === 'escalate' ? 'bg-rose-500/15 text-rose-300 border-rose-500/30'
      : rec === 'monitor' ? 'bg-amber-500/15 text-amber-300 border-amber-500/30'
      : rec === 'close' ? 'bg-slate-600/20 text-slate-300 border-slate-600/30'
      : 'bg-sky-500/15 text-sky-300 border-sky-500/30');

  return (
    <div className="space-y-6">
      <Link to="/signals" className="text-sm text-sky-400 hover:underline">← Back to signals</Link>

      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-2xl font-bold text-slate-100 capitalize flex items-center gap-3">
            {sig.spike_flag && <span className="h-3 w-3 rounded-full bg-rose-500 pulse-dot" />}
            {sig.drug} <span className="text-slate-600">→</span> {md.pt || sig.symptom}
          </h2>
          <div className="flex flex-wrap gap-2 mt-2">
            <Badge value={isDevice ? '🩺 Device' : '💊 Drug'}
                   className={isDevice ? 'bg-amber-500/15 text-amber-300 border-amber-500/30' : 'bg-sky-500/10 text-sky-300 border-sky-500/20'} />
            <Badge kind="strength" value={sig.strength} />
            {sig.sdr_flag && <Badge value="SDR" className="bg-rose-500/15 text-rose-300 border-rose-500/30" title="Signal of Disproportionate Reporting" />}
            <Badge kind="causality" value={`WHO-UMC: ${sig.who_umc}`} />
            <SeverityAuditPopover signalId={sig.id} severity={sig.severity} />
            {pgx && <Badge value={`🧬 PGx: ${pgx.gene}`} className="bg-emerald-500/15 text-emerald-300 border-emerald-500/30" title={`${pgx.allele} · ${pgx.level}`} />}
            {boxed && <Badge value="⬛ Boxed warning" className="bg-amber-500/15 text-amber-300 border-amber-500/30" title={(boxed.topics || []).join('; ')} />}
            {mechanism && <Badge value={`⚛ Plausible: ${mechanism.target_or_moa}`} className="bg-cyan-500/15 text-cyan-200 border-cyan-500/30" title={mechanism.mechanism_explanation} />}
            {classInfo && <Badge value={`⚗ Class effect: ${classInfo.class_name.split(' (')[0]}`} className="bg-teal-500/15 text-teal-200 border-teal-500/30" title={`${(classInfo.member_drugs || []).length} drugs in class`} />}
            {sig.stands_out_in_class && <Badge value="◎ Stands out in class" className="bg-fuchsia-500/15 text-fuchsia-200 border-fuchsia-500/30" title={ac ? `Active-comparator ROR ${ac.ac_ror} (CI ${ac.ac_ror_ci?.[0]}–${ac.ac_ror_ci?.[1]}) vs other ${ac.comparator_class} drugs` : 'Disproportionate even versus same-class comparators'} />}
            {sig.calibrated_signal && <Badge value="✓ Calibrated" className="bg-indigo-500/15 text-indigo-200 border-indigo-500/30" title="Survives empirical-null calibration against negative controls" />}
            {sig.completeness != null && <Badge value={`▤ ${sig.completeness.toFixed(2)}`}
              className={sig.well_documented ? 'bg-lime-500/15 text-lime-200 border-lime-500/30' : 'bg-slate-600/20 text-slate-300 border-slate-600/40'}
              title={`vigiGrade-style report completeness ${completeness?.grade ? `(${completeness.grade})` : ''} — documentation-quality surrogate`} />}
            {spatial && <Badge value={`📍 Geo cluster: ${spatial.hotspot}`} className="bg-emerald-500/15 text-emerald-200 border-emerald-500/30" title={`${spatial.observed} reports in ${spatial.hotspot} vs ${spatial.expected?.toFixed(1)} expected · RR ${spatial.rr?.toFixed(1)}×`} />}
            {vaccine && <Badge value={vaccine.aesi_name ? `💉 AESI: ${vaccine.aesi_name.split(' (')[0]}` : '💉 Vaccine'} className="bg-pink-500/15 text-pink-200 border-pink-500/30" title={`${vaccine.vaccine_name || 'Vaccine'}${vaccine.brighton_level ? ` · Brighton L${vaccine.brighton_level}` : ''}`} />}
            {sig.trust_label === 'high' && <Badge value={`🛡 Trust ${sig.trust_score?.toFixed(2)}`} className="bg-emerald-500/10 text-emerald-300 border-emerald-500/20" title="High-trust cohort — diverse authors, temporal spread, varied text" />}
            {sig.trust_label === 'medium' && <Badge value={`⚠ Trust ${sig.trust_score?.toFixed(2)}`} className="bg-amber-500/15 text-amber-300 border-amber-500/30" title="Medium trust — some cohort homogeneity detected" />}
            {sig.trust_label === 'low' && <Badge value={`⚠ Low trust ${sig.trust_score?.toFixed(2)}`} className="bg-orange-500/15 text-orange-300 border-orange-500/30" title="Low trust — suspicious posting pattern, analyst review recommended" />}
            {sig.trust_label === 'sybil' && <Badge value={`🚨 Sybil ${sig.trust_score?.toFixed(2)}`} className="bg-rose-700/20 text-rose-200 border-rose-600/40" title="Coordinated posting pattern detected — signal downweighted" />}
            {calib?.is_negative_control && <Badge value="Negative control" className="bg-slate-600/20 text-slate-400 border-slate-600/30" title="Used as a negative control to fit the empirical null" />}
            {sig.spike_flag && <Badge value={`▲ Spike z=${sig.spike_z}`} className="bg-rose-500/15 text-rose-300 border-rose-500/30" />}
            {sig.hr != null && (
              <Badge
                value={`⏱ HR ${sig.hr.toFixed(2)}`}
                className={sig.hr_elevated
                  ? 'bg-orange-500/15 text-orange-300 border-orange-500/30'
                  : 'bg-slate-600/20 text-slate-400 border-slate-600/30'}
                title={`Cox PH surrogate hazard ratio ${sig.hr.toFixed(2)} — illustrative social-listening estimate${sig.hr_elevated ? ' — elevated (CI lower bound > 1)' : ''}`}
              />
            )}
            {maxsprt && (
              <Badge
                value={sig.maxsprt_crossed
                  ? `🔔 MaxSPRT crossed LLR=${sig.maxsprt_llr?.toFixed(2)}`
                  : `MaxSPRT LLR=${sig.maxsprt_llr?.toFixed(2) ?? '—'}`}
                className={sig.maxsprt_crossed
                  ? 'bg-violet-500/15 text-violet-200 border-violet-500/30'
                  : 'bg-slate-600/20 text-slate-400 border-slate-600/30'}
                title={maxsprt.interpretation}
              />
            )}
            {md.soc && <Badge value={md.soc} className="bg-violet-500/15 text-violet-300 border-violet-500/30" />}
            {!isDevice && sig.drug_atc && <Badge value={`ATC ${sig.drug_atc}`} className="bg-sky-500/10 text-sky-300 border-sky-500/20" />}
            {isDevice && sig.device_gmdn && <Badge value={`🩺 ${sig.device_gmdn}`} className="bg-amber-500/10 text-amber-300 border-amber-500/20" title="GMDN / FDA product code" />}
            {isDevice && sig.imdrf_code && <Badge value={`IMDRF ${sig.imdrf_code}`} className="bg-amber-500/10 text-amber-300 border-amber-500/20" title={sig.imdrf_term || sig.imdrf_code} />}
          </div>
          <div className="mt-2 text-xs text-slate-500">
            {isDevice ? 'IMDRF failure: ' : 'MedDRA PT: '}
            <span className="text-slate-300">
              {isDevice ? (sig.imdrf_term || md.pt || '—') : (md.pt || '—')}
            </span>
            {isDevice && sig.imdrf_code && <span className="text-slate-500"> ({sig.imdrf_code})</span>}
            {regions.length > 0 && <> · Regions: {regions.map(([r, n]) => `${r} (${n})`).join(', ')}</>}
          </div>
          {(sig.smq || []).length > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <span className="text-[11px] text-slate-500">SMQ:</span>
              {sig.smq.map((m) => (
                <Link key={m.smq} to={`/smq?focus=${m.smq}`}
                      className="text-[10px] rounded bg-cyan-500/15 text-cyan-300 border border-cyan-500/30 px-2 py-0.5 hover:bg-cyan-500/25"
                      title={`Standardised MedDRA Query — ${m.scope} scope`}>
                  ◈ {m.name.split(' (')[0]} ({m.scope})
                </Link>
              ))}
            </div>
          )}
        </div>
        <div className="flex flex-col items-end gap-2">
          <div className="flex flex-wrap gap-2">
            <a href={api.e2bUrl(sig.id)} target="_blank" rel="noreferrer"><Button variant="ghost">⬇ E2B R3</Button></a>
            <a href={api.e2bR2Url(sig.id)} target="_blank" rel="noreferrer"><Button variant="ghost">⬇ E2B R2</Button></a>
            <Button variant="ghost" disabled={ciomsDl} onClick={() => {
              setCiomsDl(true);
              api.downloadCioms(sig.id, sig.drug, sig.symptom)
                .catch(() => {})
                .finally(() => setCiomsDl(false));
            }}>⬇ CIOMS I</Button>
            <Button variant="ghost" disabled={sarDl} onClick={() => {
              setSarDl(true);
              api.downloadSar(sig.id, sig.drug, sig.symptom, 'pdf')
                .catch(() => {})
                .finally(() => setSarDl(false));
            }}>⬇ SAR PDF</Button>
            <Button variant="ghost" disabled={sarDl} onClick={() => {
              setSarDl(true);
              api.downloadSar(sig.id, sig.drug, sig.symptom, 'md')
                .catch(() => {})
                .finally(() => setSarDl(false));
            }}>⬇ SAR MD</Button>
            <AuditButton signalId={sig.id} />
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-slate-500">Review:</span>
            <Button variant={sig.review_state === 'confirmed' ? 'primary' : 'ghost'} disabled={reviewing} onClick={() => review('confirmed')}>✓ Confirm</Button>
            <Button variant={sig.review_state === 'dismissed' ? 'danger' : 'ghost'} disabled={reviewing} onClick={() => review('dismissed')}>✕ Dismiss</Button>
          </div>
        </div>
      </div>

      {/* AI narrative */}
      <Card className="p-4 border-sky-700/40">
        <CardHeader
          title="AI signal narrative"
          subtitle={`Grounded in the computed evidence · source: ${sig.narrative_source || 'deterministic'}`}
          right={<Button variant="ghost" disabled={regen} onClick={regenerate}>{regen ? 'Generating…' : '↻ Regenerate'}</Button>}
        />
        <p className="mt-3 text-sm text-slate-200 leading-relaxed">
          {sig.narrative || 'No narrative generated yet — click Regenerate.'}
        </p>
        {sig.who_umc_factors?.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {sig.who_umc_factors.map((f) => (
              <span key={f} className="text-[10px] rounded bg-slate-800 border border-slate-700 px-2 py-0.5 text-slate-300">{f}</span>
            ))}
          </div>
        )}
      </Card>

      {/* 📋 GVP Module IX Signal Lifecycle */}
      <LifecyclePanel sig={sig} onUpdated={(updated) => setSig((prev) => ({ ...prev, ...updated }))} />

      {/* 🤖 Safety-Scientist Copilot — RAG structured assessment memo */}
      <CopilotPanel
        sig={sig}
        assessment={assessment}
        assessing={assessing}
        onDraft={runAssessment}
        recClass={recClass}
      />

      {/* disproportionality panel — frequentist + Bayesian */}
      <Card className="p-4">
        <CardHeader
          title="Disproportionality analysis"
          subtitle="Frequentist reporting ratios with 95% CIs, plus Bayesian shrinkage (MGPS/BCPNN) that is robust at small counts."
          right={sig.sdr_flag
            ? <Badge value="✓ Signal of Disproportionate Reporting" className="bg-rose-500/15 text-rose-300 border-rose-500/30" />
            : <Badge value="Below SDR threshold" className="bg-slate-600/20 text-slate-400 border-slate-600/30" />}
        />
        <div className="mt-3 grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          <Metric label="PRR" value={fmt(sig.prr)} ci={ci(sig.prr_ci?.[0], sig.prr_ci?.[1])}
                  hint="Proportional Reporting Ratio: how much more often this event is reported for this product vs all others. Signal when the CI lower bound ≥ 1." />
          <Metric label="ROR" value={fmt(sig.ror)} ci={ci(sig.ror_ci?.[0], sig.ror_ci?.[1])}
                  hint="Reporting Odds Ratio: odds-based analogue of PRR, less biased when the event is common." />
          <Metric label="χ²" value={fmt(sig.chi_square)}
                  hint="Yates-corrected chi-square on the 2×2 table. ≥ 4 (≈ p<0.05) supports a signal." />
          <Metric label="EB05" value={fmt(sig.eb05)} accent={sig.eb05 >= 2 ? 'text-rose-300' : 'text-slate-100'}
                  hint={`MGPS Empirical-Bayes Geometric Mean, 5% lower bound (EBGM=${fmt(sig.ebgm)}). FDA-style threshold: EB05 ≥ 2. Shrinks small-N noise toward the null.`} />
          <Metric label="IC025" value={fmt(sig.ic025)} accent={sig.ic025 > 0 ? 'text-rose-300' : 'text-slate-100'}
                  hint={`BCPNN Information Component, 2.5% lower bound (IC=${fmt(sig.ic)}). UMC/VigiBase threshold: IC025 > 0.`} />
          <Metric label="Reports" value={sig.post_count}
                  hint={`Observed co-reports (a-cell). Expected under independence ≈ ${fmt(sig.expected)}.`} />
        </div>
        <div className="mt-3 text-[11px] text-slate-500">
          Detection rule: SDR when IC025 &gt; 0, or EB05 ≥ 2, or PRR CI-lower ≥ 1 with χ² ≥ 4 and n ≥ 3. WHO-UMC confidence {(sig.who_umc_score * 100).toFixed(0)}%
          {sig.who_umc_factors?.length ? ` · factors: ${sig.who_umc_factors.join(', ')}` : ' · limited causality cues in social text (uncertainty noted)'}.
        </div>
      </Card>

      {/* Competition-bias masking / unmask remine */}
      <Card className="p-4 border-orange-700/40 bg-orange-500/[0.03]">
        <CardHeader
          title="Competition-bias masking"
          subtitle="See which other products dominate this event, then remine without them — does this signal strengthen?"
          right={
            masking ? (
              <Badge
                value={`risk: ${masking.masking_risk || 'none'}`}
                className={
                  masking.masking_risk === 'high'
                    ? 'bg-rose-500/15 text-rose-300 border-rose-500/30'
                    : masking.masking_risk === 'moderate'
                      ? 'bg-amber-500/15 text-amber-300 border-amber-500/30'
                      : 'bg-slate-600/20 text-slate-400 border-slate-600/30'
                }
              />
            ) : null
          }
        />
        {!masking ? (
          <div className="mt-3 text-sm text-slate-400">Loading masking analysis…</div>
        ) : (
          <>
            <p className="mt-2 text-sm text-slate-200 leading-relaxed">{masking.verdict}</p>
            <div className="mt-2 text-[11px] text-slate-500">
              Event reports={masking.event_total} · this product={masking.target_count}
              {' '}({((masking.target_share || 0) * 100).toFixed(0)}% of event)
            </div>
            {(masking.maskers || []).length > 0 ? (
              <div className="mt-3 space-y-1.5">
                <div className="text-[11px] uppercase tracking-wide text-slate-500">Competitors on this event — select to exclude</div>
                {masking.maskers.map((m) => (
                  <label key={m.drug} className="flex items-center gap-2 text-sm text-slate-300 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={selectedMaskers.includes(m.drug)}
                      onChange={(e) => {
                        setSelectedMaskers((prev) =>
                          e.target.checked ? [...prev, m.drug] : prev.filter((d) => d !== m.drug)
                        );
                      }}
                    />
                    <span className="capitalize">{m.drug}</span>
                    <span className="text-[11px] text-slate-500">
                      n={m.count} · {(m.event_share * 100).toFixed(0)}% of event · ×{m.vs_target_ratio} vs this product
                    </span>
                    {m.likely_masker && (
                      <Badge value="likely masker" className="bg-orange-500/15 text-orange-200 border-orange-500/30" />
                    )}
                  </label>
                ))}
              </div>
            ) : (
              <div className="mt-3 space-y-3">
                <p className="text-sm text-amber-200/90">
                  {masking.try_next || 'No competing products on this event — remine cannot change the 2×2 table.'}
                </p>
                {(masking.remineable_examples || []).length > 0 && (
                  <div>
                    <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1.5">
                      Open a signal where remine works
                    </div>
                    <div className="flex flex-col gap-1.5">
                      {masking.remineable_examples.map((ex) => (
                        <Link
                          key={ex.signal_id}
                          to={`/signals/${ex.signal_id}`}
                          className="text-sm text-sky-300 hover:underline capitalize"
                        >
                          {ex.drug} → {ex.event}
                          <span className="text-slate-500 normal-case"> — {ex.why}</span>
                        </Link>
                      ))}
                    </div>
                  </div>
                )}
                <Button
                  variant="primary"
                  disabled={pvDemoBusy}
                  onClick={async () => {
                    setPvDemoBusy(true);
                    setUnmaskErr(null);
                    try {
                      await api.ingestPvDemo({ recompute: true });
                      const m = await api.signalMasking(sig.id);
                      setMasking(m);
                      setSelectedMaskers(m.suggested_exclude || []);
                      setDdi(await api.signalDdi(sig.id));
                    } catch (e) {
                      setUnmaskErr(e?.message || String(e));
                    }
                    setPvDemoBusy(false);
                  }}
                >
                  {pvDemoBusy ? 'Loading demo pack…' : 'Load PV demo pack (then open a remineable signal)'}
                </Button>
              </div>
            )}
            <div className="mt-3 flex flex-wrap gap-2 items-center">
              <Button
                variant="primary"
                disabled={unmasking || !(masking.can_remine || selectedMaskers.length)}
                onClick={async () => {
                  setUnmasking(true);
                  setUnmaskErr(null);
                  try {
                    const picks = selectedMaskers.length
                      ? selectedMaskers
                      : (masking.suggested_exclude || []);
                    setUnmask(await api.signalUnmask(sig.id, picks));
                  } catch (e) {
                    setUnmaskErr(e?.message || String(e));
                  }
                  setUnmasking(false);
                }}
              >
                {unmasking ? 'Remining…' : 'Remine without selected products'}
              </Button>
              {(masking.suggested_exclude || []).length > 0 && (
                <Button
                  variant="ghost"
                  disabled={unmasking}
                  onClick={() => setSelectedMaskers(masking.suggested_exclude || [])}
                >
                  Select suggested
                </Button>
              )}
            </div>
            {unmaskErr && <div className="mt-2 text-sm text-rose-300">{unmaskErr}</div>}
            {unmask && (
              <div className="mt-3 rounded-lg border border-orange-600/30 bg-slate-950/50 p-3 space-y-3">
                <p className="text-sm text-slate-100 leading-relaxed">{unmask.interpretation}</p>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <Metric label="Before PRR" value={fmt(unmask.baseline?.prr)} />
                  <Metric
                    label="After PRR"
                    value={unmask.unmasked ? fmt(unmask.unmasked.prr) : '—'}
                    accent={unmask.signal_strengthened ? 'text-emerald-300' : unmask.signal_attenuated ? 'text-sky-300' : 'text-slate-100'}
                  />
                  <Metric label="Before IC025" value={fmt(unmask.baseline?.ic025)} />
                  <Metric label="After IC025" value={unmask.unmasked ? fmt(unmask.unmasked.ic025) : '—'} />
                </div>
                {unmask.delta && (
                  <div className="text-[11px] text-slate-400">
                    ΔPRR={unmask.delta.prr_delta} · ΔIC025={unmask.delta.ic025_delta} · ΔEB05={unmask.delta.eb05_delta}
                    {' · excluded: '}{(unmask.excluded_maskers || []).join(', ') || '—'}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </Card>

      {/* Longitudinal casefile */}
      <Card className="p-4 border-teal-700/40">
        <CardHeader
          title="Signal casefile (trajectory)"
          subtitle={casefile?.timeline_source === 'reconstructed_from_case_dates'
            ? 'Reconstructed from case dates until weekly snapshots accumulate'
            : 'Weekly DMA memory — new vs strengthening vs weakening'}
          right={
            casefile ? (
              <Badge
                value={casefile.trajectory || 'unknown'}
                className={
                  casefile.trajectory === 'strengthening'
                    ? 'bg-rose-500/15 text-rose-300 border-rose-500/30'
                    : casefile.trajectory === 'weakening'
                      ? 'bg-sky-500/15 text-sky-300 border-sky-500/30'
                      : casefile.trajectory === 'new'
                        ? 'bg-amber-500/15 text-amber-300 border-amber-500/30'
                        : 'bg-slate-600/20 text-slate-400 border-slate-600/30'
                }
              />
            ) : null
          }
        />
        {!casefile ? (
          <div className="mt-3 text-sm text-slate-400">Loading casefile…</div>
        ) : (
          <>
            <p className="mt-2 text-sm text-slate-200">{casefile.verdict}</p>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-xs text-left">
                <thead className="text-slate-500">
                  <tr>
                    <th className="py-1 pr-3">Week</th>
                    <th className="py-1 pr-3">n</th>
                    <th className="py-1 pr-3">PRR</th>
                    <th className="py-1 pr-3">IC025</th>
                    <th className="py-1 pr-3">EB05</th>
                    <th className="py-1">Strength</th>
                  </tr>
                </thead>
                <tbody>
                  {(casefile.timeline || []).map((t) => (
                    <tr key={t.week_start} className="border-t border-slate-800 text-slate-300">
                      <td className="py-1.5 pr-3">
                        {(t.week_start || '').slice(0, 10)}
                        {t.live ? ' (live)' : ''}
                        {t.reconstructed ? ' ≈' : ''}
                      </td>
                      <td className="py-1.5 pr-3">{t.post_count}</td>
                      <td className="py-1.5 pr-3">{t.prr ?? '—'}</td>
                      <td className="py-1.5 pr-3">{t.ic025 ?? '—'}</td>
                      <td className="py-1.5 pr-3">{t.eb05 ?? '—'}</td>
                      <td className="py-1.5">{t.strength || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {casefile.label_change_heuristic && (
              <div className="mt-3 text-[11px] text-slate-400">
                Label-change heuristic: <span className="text-slate-200">{casefile.label_change_heuristic.likelihood_band}</span>
                {' '}(score {casefile.label_change_heuristic.score})
                {(casefile.label_change_heuristic.reasons || []).length
                  ? ` — ${casefile.label_change_heuristic.reasons.join('; ')}`
                  : ''}
                <div className="text-[10px] text-slate-500 mt-1">{casefile.label_change_heuristic.disclaimer}</div>
              </div>
            )}
          </>
        )}
      </Card>

      {/* DDI pairs involving this product */}
      <Card className="p-4 border-violet-700/40">
        <CardHeader
          title="DDI co-mentions for this product"
          subtitle="Other products co-reported with this one on the same AE post"
        />
        {!ddi ? (
          <div className="mt-3 text-sm text-slate-400">Loading DDI…</div>
        ) : (
          <>
            <p className="mt-2 text-sm text-slate-200">{ddi.verdict}</p>
            {(ddi.pairs || []).length > 0 ? (
              <div className="mt-3 space-y-2">
                {ddi.pairs.slice(0, 8).map((p) => (
                  <div key={`${p.drug_a}|${p.drug_b}|${p.event}`} className="flex flex-wrap justify-between gap-2 text-sm text-slate-300">
                    <span className="capitalize">{p.drug_a} + {p.drug_b} → {p.event}</span>
                    <span className="text-[11px] text-slate-500">
                      Ω={p.omega} · n={p.count}
                      {p.plausibility?.plausible ? ' · plausible' : ' · review'}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="mt-3">
                <Button variant="ghost" disabled={pvDemoBusy} onClick={async () => {
                  setPvDemoBusy(true);
                  try {
                    await api.ingestPvDemo({ recompute: true });
                    setDdi(await api.signalDdi(sig.id));
                  } catch (e) { console.error(e); }
                  setPvDemoBusy(false);
                }}>
                  {pvDemoBusy ? 'Loading demo pack…' : 'Load PV demo pack (DDI + pregnancy)'}
                </Button>
              </div>
            )}
            {ddi.disclaimer && <p className="mt-2 text-[10px] text-slate-500">{ddi.disclaimer}</p>}
          </>
        )}
      </Card>

      {/* SAR preview */}
      {sarPreview && (
        <Card className="p-4 border-emerald-700/40">
          <CardHeader
            title="GVP IX Signal Assessment Report"
            subtitle="Structured assessment pack — download PDF/MD from the header buttons"
          />
          <p className="mt-2 text-sm text-slate-200">{sarPreview.recommended_action}</p>
          <div className="mt-2 text-[11px] text-slate-500">
            Lifecycle: {sarPreview.lifecycle?.status || '—'} · WHO-UMC: {sarPreview.causality?.who_umc || '—'}
            {' · '}SDR: {String(sarPreview.detection?.sdr_flag)} · strength: {sarPreview.detection?.strength}
          </div>
        </Card>
      )}

      {/* active-comparator (same-class) analysis */}
      {ac && (
        <Card className="p-4 border-fuchsia-700/40 bg-fuchsia-500/[0.04]">
          <CardHeader
            title="◎ Active-comparator analysis"
            subtitle={`vs same-class comparator (${ac.comparator_class}${ac.n_comparator_drugs ? `, ${ac.n_comparator_drugs} drug${ac.n_comparator_drugs === 1 ? '' : 's'}` : ''}) — reduces confounding-by-indication by contrasting the drug against its own ATC class instead of all other drugs.`}
            right={ac.n_comparator_drugs === 0
              ? <Badge value="No active comparator" className="bg-slate-600/20 text-slate-400 border-slate-600/30" />
              : (ac.stands_out_in_class
                  ? <Badge value="◎ Stands out in class" className="bg-fuchsia-500/15 text-fuchsia-200 border-fuchsia-500/30" />
                  : <Badge value="Attenuates within class" className="bg-slate-600/20 text-slate-400 border-slate-600/30" />)}
          />
          {ac.n_comparator_drugs === 0 ? (
            <div className="mt-3 text-sm text-slate-400">{ac.note}</div>
          ) : (
            <>
              <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-3">
                <Metric label="AC ROR" value={fmt(ac.ac_ror)} ci={ci(ac.ac_ror_ci?.[0], ac.ac_ror_ci?.[1])}
                        accent={ac.stands_out_in_class ? 'text-fuchsia-300' : 'text-slate-100'}
                        hint="Reporting Odds Ratio computed against the OTHER drugs in the same ATC class (the active comparator), not all other drugs. Stands out when the 95% CI lower bound > 1." />
                <Metric label="AC PRR" value={fmt(ac.ac_prr)} ci={ci(ac.ac_prr_ci?.[0], ac.ac_prr_ci?.[1])}
                        hint="Proportional Reporting Ratio within the same-class cohort — the class-restricted analogue of the standard PRR." />
                <Metric label="vs all-drugs ROR" value={fmt(sig.ror)} ci={ci(sig.ror_ci?.[0], sig.ror_ci?.[1])}
                        hint="The standard 'vs all other drugs' ROR already stored for this signal, shown for comparison." />
                <Metric label="Comparators" value={ac.n_comparator_drugs}
                        hint={`Other ${ac.comparator_class} drugs in the corpus forming the active-comparator cohort.`} />
              </div>
              <div className={`mt-3 rounded-lg border px-3 py-2 text-sm leading-relaxed ${ac.stands_out_in_class ? 'border-fuchsia-600/30 bg-fuchsia-500/[0.06] text-fuchsia-100' : 'border-slate-700 bg-slate-950/40 text-slate-300'}`}>
                {ac.note}
              </div>
              {ac.comparator_drugs?.length > 0 && (
                <div className="mt-3">
                  <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1">Active-comparator cohort ({ac.comparator_class})</div>
                  <div className="flex flex-wrap gap-1.5">
                    {ac.comparator_drugs.map((d) => (
                      <span key={d} className="text-xs rounded-md px-2 py-0.5 bg-slate-800 text-slate-300 border border-slate-700 capitalize">{d}</span>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </Card>
      )}

      {/* empirical calibration (negative-control null) + E-value */}
      <Card className="p-4 border-indigo-700/40">
        <CardHeader
          title="Empirical calibration & E-value"
          subtitle="Calibrated against the observed noise floor of negative controls (Schuemie/OHDSI), plus residual-confounding robustness (VanderWeele & Ding)."
          right={sig.calibrated_signal
            ? <Badge value="✓ Survives calibration" className="bg-indigo-500/15 text-indigo-200 border-indigo-500/30" />
            : <Badge value={calib?.is_negative_control ? 'Negative control' : 'Not calibrated-significant'} className="bg-slate-600/20 text-slate-400 border-slate-600/30" />}
        />
        <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-3">
          <Metric label="Calibrated p" value={sig.calibrated_p != null ? sig.calibrated_p.toFixed(4) : '—'}
                  accent={sig.calibrated_signal ? 'text-indigo-300' : 'text-slate-100'}
                  hint="p-value measured against the empirical null fitted from negative controls (not the theoretical null). Significant when < 0.05." />
          <Metric label="Calibrated 95% CI"
                  value={calib?.calibrated_ci && calib.calibrated_ci[0] != null ? `${calib.calibrated_ci[0].toFixed(2)}–${calib.calibrated_ci[1].toFixed(2)}` : '—'}
                  hint="ROR 95% CI re-centred on the empirical null estimated from negative controls." />
          <Metric label="E-value" value={sig.e_value != null ? sig.e_value.toFixed(2) : '—'}
                  accent={sig.e_value >= 2 ? 'text-emerald-300' : 'text-slate-100'}
                  hint="Minimum risk-ratio strength an unmeasured confounder would need with BOTH drug and event to fully explain the association away. Larger = more robust." />
          <Metric label="E-value (CI)" value={sig.e_value_ci != null ? sig.e_value_ci.toFixed(2) : '—'}
                  hint="E-value applied to the CI limit closest to the null — the confounding needed to shift the CI to include no effect (1.0 = CI already crosses the null)." />
        </div>
        <div className="mt-3 text-[11px] text-slate-500">
          {calib?.is_negative_control
            ? 'This pair is part of the negative-control panel used to fit the empirical null.'
            : (sig.calibrated_signal
                ? `Robust: an unmeasured confounder would need an RR of ≈ ${sig.e_value?.toFixed(1)} with both the drug and the event to explain this signal away.`
                : 'Does not clear the empirical-null threshold — likely within the observed noise floor.')}
          {calib && calib.n_controls != null && <> · Empirical null: μ={calib.null_mu ?? '—'}, σ={calib.null_sigma ?? '—'} (n={calib.n_controls}{calib.calibrated ? '' : ', theoretical fallback'}).</>}
        </div>
      </Card>

      {/* report completeness (UMC vigiGrade-style) */}
      {completeness && (
        <Card className="p-4 border-lime-700/40">
          <CardHeader
            title="▤ Report completeness (vigiGrade-style)"
            subtitle="How well-documented is this signal's evidence? A multiplicative-penalty documentation-quality score over the ICSR-style dimensions we can assess from social posts."
            right={<Badge value={completeness.well_documented ? 'Well-documented' : 'Poorly documented'}
                          className={completeness.well_documented
                            ? 'bg-lime-500/15 text-lime-200 border-lime-500/30'
                            : 'bg-amber-500/15 text-amber-300 border-amber-500/30'} />}
          />

          {/* mean completeness gauge */}
          <div className="mt-3">
            <div className="flex items-center justify-between text-xs mb-1">
              <span className="text-slate-400">Mean completeness ({completeness.grade})</span>
              <span className="font-mono text-lime-200">{(completeness.mean_completeness ?? 0).toFixed(2)} / 1.00</span>
            </div>
            <div className="h-3 rounded bg-slate-800 overflow-hidden relative">
              <div className={`h-full ${completeness.well_documented ? 'bg-lime-500/70' : 'bg-amber-500/70'}`}
                   style={{ width: `${Math.max(2, (completeness.mean_completeness ?? 0) * 100)}%` }} />
              {/* well-documented threshold marker (0.5) */}
              <div className="absolute top-0 bottom-0 border-l border-dashed border-slate-400/60" style={{ left: '50%' }}
                   title="Well-documented threshold (0.5)" />
            </div>
            <div className="mt-1 text-[10px] text-slate-500">
              Averaged over {completeness.n_posts} supporting post{completeness.n_posts === 1 ? '' : 's'} · dashed line = well-documented threshold (0.5)
            </div>
          </div>

          {/* best / worst supporting post */}
          <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3">
            {completeness.best && (
              <div className="rounded-lg border border-lime-600/20 bg-slate-950/40 px-3 py-2">
                <div className="text-[11px] uppercase tracking-wide text-slate-500">Best-documented post</div>
                <div className="text-sm font-mono text-lime-200 mt-0.5">
                  {completeness.best.score?.toFixed(2)}{completeness.best.post_id != null ? ` · #${completeness.best.post_id}` : ''}
                </div>
                <div className="text-[10px] text-slate-500 mt-0.5">
                  {(completeness.best.present || []).length} of {COMPLETENESS_DIMS.length} dimensions present
                </div>
              </div>
            )}
            {completeness.worst && (
              <div className="rounded-lg border border-amber-600/20 bg-slate-950/40 px-3 py-2">
                <div className="text-[11px] uppercase tracking-wide text-slate-500">Worst-documented post</div>
                <div className="text-sm font-mono text-amber-300 mt-0.5">
                  {completeness.worst.score?.toFixed(2)}{completeness.worst.post_id != null ? ` · #${completeness.worst.post_id}` : ''}
                </div>
                <div className="text-[10px] text-slate-500 mt-0.5">
                  {(completeness.worst.missing || []).length} of {COMPLETENESS_DIMS.length} dimensions missing
                </div>
              </div>
            )}
          </div>

          {/* dimension coverage checklist */}
          <div className="mt-3">
            <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1.5">
              Dimension coverage across supporting posts
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1.5">
              {COMPLETENESS_DIMS.map(([key, label]) => {
                const cov = (completeness.dimension_coverage || {})[key] ?? 0;
                const present = cov >= 0.5;
                return (
                  <div key={key} className="flex items-center gap-2 text-xs">
                    <span className={`h-4 w-4 rounded flex items-center justify-center text-[10px] font-bold ${
                      present ? 'bg-lime-500/20 text-lime-300' : 'bg-slate-700/40 text-slate-400'
                    }`}>{present ? '✓' : '—'}</span>
                    <span className={`flex-1 ${present ? 'text-slate-200' : 'text-slate-500'}`}>{label}</span>
                    <div className="w-16 h-1.5 rounded bg-slate-800 overflow-hidden">
                      <div className={`h-full ${present ? 'bg-lime-500/60' : 'bg-slate-600/60'}`}
                           style={{ width: `${Math.max(2, cov * 100)}%` }} />
                    </div>
                    <span className="w-9 text-right font-mono text-slate-500">{(cov * 100).toFixed(0)}%</span>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="mt-3 flex items-start gap-2 text-[11px] text-amber-400/80">
            <span>⚠</span>
            <span>
              Documentation-quality surrogate, adapted to social-listening fields. The true UMC vigiGrade
              scores structured ICSR data (reporter qualification, verified demographics, exact dose regimen,
              etc.) that patient posts do not carry — this score reflects only the dimensions assessable from
              the scrubbed text, and grades documentation completeness, not whether the association is real.
            </span>
          </div>
        </Card>
      )}

      {/* Cox PH time-to-event (hazard ratio) panel */}
      <Card className={`p-4 ${sig.hr_elevated ? 'border-orange-600/40 bg-orange-500/[0.04]' : 'border-slate-700/40'}`}>
        <CardHeader
          title="⏱ Time-to-event (HR) — Cox PH surrogate"
          subtitle="Days from the signal's earliest post to each supporting-post mention; Cox partial-likelihood vs unexposed-drug AE posts. Breslow approximation for ties."
          right={sig.hr != null
            ? (sig.hr_elevated
                ? <Badge value="HR elevated (CI lower > 1)" className="bg-orange-500/15 text-orange-300 border-orange-500/30" />
                : <Badge value="HR not elevated" className="bg-slate-600/20 text-slate-400 border-slate-600/30" />)
            : <Badge value="Insufficient data" className="bg-slate-600/20 text-slate-400 border-slate-600/30" />}
        />
        {sig.hr == null ? (
          <div className="mt-3 text-sm text-slate-400">
            {hrDetail?.note || 'Fewer than 3 events available — hazard ratio not computed.'}
          </div>
        ) : (
          <>
            <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-3">
              <Metric
                label="Hazard Ratio (HR)"
                value={sig.hr.toFixed(3)}
                accent={sig.hr_elevated ? 'text-orange-300' : 'text-slate-100'}
                hint="Cox PH exp(β̂): relative rate of AE mentions in exposed vs unexposed posts. HR > 1 = faster time-to-event in exposed. Surrogate only."
              />
              <Metric
                label="95% CI"
                value={sig.hr_ci ? `${sig.hr_ci[0].toFixed(3)}–${sig.hr_ci[1].toFixed(3)}` : '—'}
                accent={sig.hr_elevated ? 'text-orange-300' : 'text-slate-100'}
                hint="Inverse-information 95% confidence interval. Elevated when lower bound > 1."
              />
              <Metric
                label="Wald p"
                value={sig.hr_p != null ? sig.hr_p.toFixed(4) : '—'}
                accent={sig.hr_p != null && sig.hr_p < 0.05 ? 'text-orange-300' : 'text-slate-100'}
                hint="Wald p-value for β̂ ≠ 0 (z = β̂/SE). Interpret with caution — social-listening data lacks true denominators."
              />
              <Metric
                label="Log-rank p"
                value={hrDetail?.logrank_p != null ? hrDetail.logrank_p.toFixed(4) : '—'}
                hint="Score-test (log-rank) p-value at β=0. Used as a validity check, not a primary endpoint."
              />
            </div>
            {hrDetail && (
              <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
                <div className="rounded-lg border border-slate-700 bg-slate-950/40 px-3 py-1.5">
                  <span className="text-slate-500">Exposed (signal posts): </span>
                  <span className="text-slate-200 font-mono">{hrDetail.n_exposed ?? '—'}</span>
                </div>
                <div className="rounded-lg border border-slate-700 bg-slate-950/40 px-3 py-1.5">
                  <span className="text-slate-500">Unexposed (other-drug AE posts): </span>
                  <span className="text-slate-200 font-mono">{hrDetail.n_unexposed ?? '—'}</span>
                </div>
              </div>
            )}
          </>
        )}
        <div className="mt-3 flex items-start gap-2 text-[11px] text-amber-400/80">
          <span>⚠</span>
          <span>
            {hrDetail?.note || 'Illustrative social-listening surrogate — NOT a clinical hazard ratio.'}
            {' '}All times are days from the signal's earliest post; all posts are treated as observed events (no censoring).
            Unexposed comparator = AE posts from other drugs. This estimate has no clinical validity and is shown for exploratory purposes only.
          </span>
        </div>
      </Card>

      {/* MaxSPRT sequential surveillance panel */}
      {maxsprt && (
        <Card className={`p-4 ${sig.maxsprt_crossed ? 'border-violet-600/40 bg-violet-500/[0.04]' : 'border-slate-700/40'}`}>
          <CardHeader
            title="🔔 MaxSPRT sequential surveillance"
            subtitle="Maximized Sequential Probability Ratio Test (Kulldorff 2011) — detects emerging signals while controlling type-I error over repeated surveillance looks, unlike naive repeated p-value testing."
            right={sig.maxsprt_crossed
              ? <Badge value="Boundary crossed — flag for action" className="bg-violet-500/15 text-violet-200 border-violet-500/30" />
              : <Badge value="Boundary not yet crossed" className="bg-slate-600/20 text-slate-400 border-slate-600/30" />}
          />
          <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-3">
            <Metric
              label="Max LLR"
              value={sig.maxsprt_llr != null ? sig.maxsprt_llr.toFixed(3) : '—'}
              accent={sig.maxsprt_crossed ? 'text-violet-300' : 'text-slate-100'}
              hint="Running maximum of the Poisson log-likelihood ratio LLR(t) = c·ln(c/μ) − (c−μ) across all sequential looks. Flagged when max LLR ≥ critical value."
            />
            <Metric
              label="Critical boundary"
              value={maxsprt.critical_value != null ? maxsprt.critical_value.toFixed(3) : '—'}
              accent="text-slate-100"
              hint={`Pre-computed Poisson MaxSPRT boundary cv(alpha=${maxsprt.alpha}, N_max=${maxsprt.n_looks}) from Kulldorff 2011 Table 1 + interpolation. The signal is flagged when max LLR ≥ this value.`}
            />
            <Metric
              label="Looks (buckets)"
              value={maxsprt.n_looks ?? '—'}
              hint="Number of sequential surveillance looks = daily reporting-trend buckets observed. Type-I error is controlled across ALL these looks simultaneously."
            />
            <Metric
              label="Crossed at look"
              value={maxsprt.n_at_crossing ?? '—'}
              accent={sig.maxsprt_crossed ? 'text-violet-300' : 'text-slate-500'}
              hint="Sequential look (1-indexed) at which the boundary was first crossed. Null if not yet crossed."
            />
          </div>

          {/* LLR series mini-chart */}
          {(maxsprt.llr_series || []).length > 1 && (
            <div className="mt-3">
              <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1.5">
                LLR over sequential looks (boundary = {maxsprt.critical_value?.toFixed(2)})
              </div>
              <div className="flex items-end gap-0.5 h-16 overflow-hidden">
                {maxsprt.llr_series.map((v, i) => {
                  const maxV = Math.max(maxsprt.critical_value || 1, ...maxsprt.llr_series);
                  const pct = maxV > 0 ? Math.max(2, (v / maxV) * 100) : 2;
                  const crossed = v >= (maxsprt.critical_value || Infinity);
                  return (
                    <div
                      key={i}
                      className={`flex-1 rounded-t ${crossed ? 'bg-violet-400/80' : 'bg-slate-500/50'}`}
                      style={{ height: `${pct}%` }}
                      title={`Look ${i + 1}: LLR=${v.toFixed(3)}`}
                    />
                  );
                })}
              </div>
              {/* boundary line marker */}
              <div className="relative h-0">
                <div
                  className="absolute left-0 right-0 border-t border-dashed border-violet-400/60"
                  style={{ bottom: `${Math.min(95, ((maxsprt.critical_value || 0) / Math.max(maxsprt.critical_value || 1, ...maxsprt.llr_series)) * 64)}px` }}
                  title={`Critical boundary: ${maxsprt.critical_value?.toFixed(3)}`}
                />
              </div>
            </div>
          )}

          {/* Plain-language interpretation */}
          <div className={`mt-3 rounded-lg border px-3 py-2 text-sm leading-relaxed ${
            sig.maxsprt_crossed
              ? 'border-violet-600/30 bg-violet-500/[0.06] text-violet-100'
              : 'border-slate-700 bg-slate-950/40 text-slate-300'
          }`}>
            {maxsprt.interpretation}
          </div>

          <div className="mt-3 flex items-start gap-2 text-[11px] text-amber-400/80">
            <span>⚠</span>
            <span>
              Social-listening surrogate — counts are social-media mentions, not validated case reports. MaxSPRT
              is applied here as a sequential monitoring heuristic adapted to the trend-bucket series. Expected
              rate is derived from the signal's 2×2 independence baseline, not from a validated background
              incidence denominator. Interpret in conjunction with disproportionality and causality assessments.
              alpha = {maxsprt.alpha} (Kulldorff 2011 Poisson model, boundary table interpolated).
            </span>
          </div>
        </Card>
      )}

      {/* pharmacogenomic risk overlay */}
      {pgx && (        <Card className="p-4 border-emerald-600/40 bg-emerald-500/[0.04]">
          <CardHeader
            title="🧬 Pharmacogenomic risk (PGx)"
            subtitle="This drug–event pair matches a clinically actionable CPIC/PharmGKB association"
            right={<Badge value={pgx.level} className="bg-emerald-500/15 text-emerald-300 border-emerald-500/30" />}
          />
          <div className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-3">
            <div className="rounded-lg border border-emerald-600/20 bg-slate-950/40 px-3 py-2">
              <div className="text-[11px] uppercase tracking-wide text-slate-500">Gene</div>
              <div className="text-lg font-semibold text-emerald-200">{pgx.gene}</div>
            </div>
            <div className="rounded-lg border border-emerald-600/20 bg-slate-950/40 px-3 py-2">
              <div className="text-[11px] uppercase tracking-wide text-slate-500">Risk allele</div>
              <div className="text-sm font-mono text-emerald-200 mt-1">{pgx.allele}</div>
            </div>
            <div className="rounded-lg border border-emerald-600/20 bg-slate-950/40 px-3 py-2">
              <div className="text-[11px] uppercase tracking-wide text-slate-500">At-risk phenotype</div>
              <div className="text-sm text-slate-200 mt-1">{pgx.phenotype}</div>
            </div>
          </div>
          <div className="mt-3 rounded-lg border border-emerald-600/20 bg-slate-950/40 px-3 py-2">
            <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1">CPIC guidance</div>
            <p className="text-sm text-slate-200 leading-relaxed">{pgx.recommendation}</p>
          </div>
          <div className="mt-3 flex items-center gap-2 text-xs text-emerald-300">
            <span className="font-medium">Genomically explainable</span>
            <span className="text-slate-500">— consider pre-emptive genotyping for at-risk patients · {pgx.source}</span>
          </div>
        </Card>
      )}

      {/* FDA boxed (black-box) warning overlay */}
      {boxed && (
        <Card className="p-4 border-amber-600/40 bg-amber-500/[0.04]">
          <CardHeader
            title="⬛ FDA boxed (black-box) warning"
            subtitle="This drug carries the FDA's strongest labelling caution"
            right={<Badge value={boxed.covers_event ? 'Covers this event' : 'Different event'}
                          className={boxed.covers_event
                            ? 'bg-amber-500/15 text-amber-300 border-amber-500/30'
                            : 'bg-sky-500/15 text-sky-300 border-sky-500/30'} />}
          />
          <div className="mt-3 rounded-lg border border-amber-600/20 bg-slate-950/40 px-3 py-2">
            <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1">Boxed warning(s)</div>
            <ul className="text-sm text-amber-100 leading-relaxed list-disc list-inside">
              {(boxed.topics || []).map((t) => <li key={t}>{t}</li>)}
            </ul>
          </div>
          <div className="mt-3 flex items-start gap-2 text-xs">
            <span className={`font-semibold ${boxed.covers_event ? 'text-amber-300' : 'text-sky-300'}`}>
              {boxed.novelty === 'known-serious (boxed)' ? 'Known-serious (already boxed)' : 'Boxed drug — different event'}
            </span>
            <span className="text-slate-500">
              {boxed.covers_event
                ? '— this signal re-confirms an existing boxed warning.'
                : '— the drug is boxed for another harm, so this drug–event pairing is comparatively novel and may warrant closer review.'}
              {' · '}{boxed.source}
            </span>
          </div>
        </Card>
      )}

      {/* 📋 Labeling status panel — DailyMed adverse-reaction gap detection */}
      {!isDevice && (() => {
        const tier = sig.label_novelty || 'unknown';
        const tierConfig = {
          novel: {
            border: 'border-amber-600/40',
            bg: 'bg-amber-500/[0.04]',
            badge: '🆕 Novel',
            badgeCls: 'bg-amber-500/20 text-amber-200 border-amber-500/40',
            textCls: 'text-amber-200',
          },
          in_label: {
            border: 'border-slate-700/40',
            bg: '',
            badge: '✓ In label',
            badgeCls: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
            textCls: 'text-emerald-300',
          },
          boxed: {
            border: 'border-amber-600/40',
            bg: 'bg-amber-500/[0.04]',
            badge: '⬛ Boxed',
            badgeCls: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
            textCls: 'text-amber-300',
          },
          unknown: {
            border: 'border-slate-700/40',
            bg: '',
            badge: '? Unknown',
            badgeCls: 'bg-slate-600/20 text-slate-400 border-slate-600/30',
            textCls: 'text-slate-400',
          },
        };
        const cfg = tierConfig[tier] || tierConfig.unknown;
        const sectionLabel = labelGap?.label_section
          ? labelGap.label_section.replace(/_/g, ' ')
          : null;
        return (
          <Card className={`p-4 ${cfg.border} ${cfg.bg}`}>
            <CardHeader
              title="📋 Labeling status"
              subtitle="Is this event already listed in the drug's current FDA label adverse-reactions section? (DailyMed SPL — live or offline surrogate)"
              right={<Badge value={cfg.badge} className={cfg.badgeCls} />}
            />
            <div className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-3">
              <div className="rounded-lg border border-slate-700 bg-slate-950/40 px-3 py-2">
                <div className="text-[11px] uppercase tracking-wide text-slate-500">Novelty tier</div>
                <div className={`text-sm font-semibold mt-0.5 ${cfg.textCls}`}>{cfg.badge}</div>
              </div>
              <div className="rounded-lg border border-slate-700 bg-slate-950/40 px-3 py-2">
                <div className="text-[11px] uppercase tracking-wide text-slate-500">Label section matched</div>
                <div className="text-sm text-slate-200 mt-0.5 capitalize">{sectionLabel || '—'}</div>
              </div>
              <div className="rounded-lg border border-slate-700 bg-slate-950/40 px-3 py-2">
                <div className="text-[11px] uppercase tracking-wide text-slate-500">Confidence</div>
                <div className="text-sm text-slate-200 mt-0.5 capitalize">{labelGap?.confidence || '—'}</div>
              </div>
            </div>
            <div className={`mt-3 rounded-lg border px-3 py-2 text-sm leading-relaxed ${
              tier === 'novel'
                ? 'border-amber-600/30 bg-amber-500/[0.06] text-amber-100'
                : tier === 'in_label'
                  ? 'border-emerald-600/25 bg-slate-950/40 text-slate-200'
                  : 'border-slate-700 bg-slate-950/40 text-slate-300'
            }`}>
              {labelGap?.note || (
                tier === 'novel'
                  ? 'This event does not appear in the current FDA label — warrants priority review.'
                  : tier === 'in_label'
                    ? 'Already listed in the adverse reactions section.'
                    : 'Labeling status unavailable (offline or device).'
              )}
            </div>
            <div className="mt-3 flex items-start gap-2 text-[11px] text-amber-400/80">
              <span>⚠</span>
              <span>
                Label-gap classification uses DailyMed SPL adverse-reaction text (live API when network
                available, curated offline surrogate otherwise). This is an investigational heuristic —
                not a regulatory determination. Novel signals warrant clinical review against the current
                approved label and FAERS data.
              </span>
            </div>
          </Card>
        );
      })()}

      {/* mechanistic plausibility (Bradford Hill biological plausibility) */}
      {mechanism && (
        <Card className="p-4 border-cyan-600/40 bg-cyan-500/[0.04]">
          <CardHeader
            title="⚛ Mechanistic plausibility"
            subtitle="Does the drug's mechanism of action biologically explain this event? (Bradford Hill)"
            right={<Badge value={`${mechanism.confidence} confidence`} className="bg-cyan-500/15 text-cyan-200 border-cyan-500/30" />}
          />
          <div className="mt-3 rounded-lg border border-cyan-600/20 bg-slate-950/40 px-3 py-2">
            <div className="text-[11px] uppercase tracking-wide text-slate-500">Target / mechanism of action</div>
            <div className="text-sm font-semibold text-cyan-200 mt-1">{mechanism.target_or_moa}</div>
          </div>
          <div className="mt-3 rounded-lg border border-cyan-600/20 bg-slate-950/40 px-3 py-2">
            <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1">Why it's plausible</div>
            <p className="text-sm text-slate-200 leading-relaxed">{mechanism.mechanism_explanation}</p>
          </div>
          <div className="mt-3 flex items-center gap-2 text-xs text-cyan-300">
            <span className="font-medium">Biologically plausible</span>
            <span className="text-slate-500">— the pharmacology supports causality (Bradford Hill) · {mechanism.source}</span>
          </div>
        </Card>
      )}

      {/* class effect (ATC roll-up) + chemical read-across */}
      {(classInfo || readAcross.length > 0) && (
        <Card className="p-4 border-teal-600/40 bg-teal-500/[0.04]">
          <CardHeader
            title="⚗ Class effect & chemical read-across"
            subtitle="Is this the molecule, or the whole pharmacological class? (ATC roll-up + structural analogs)"
            right={classInfo?.sdr_flag
              ? <Badge value="Class-level SDR" className="bg-rose-500/15 text-rose-300 border-rose-500/30" />
              : (classInfo && <Badge value={`${(classInfo.member_drugs || []).length} class members`} className="bg-teal-500/15 text-teal-200 border-teal-500/30" />)}
          />
          {classInfo && (
            <>
              <div className="mt-3 rounded-lg border border-teal-600/20 bg-slate-950/40 px-3 py-2">
                <div className="text-[11px] uppercase tracking-wide text-slate-500">ATC class ({classInfo.class_key})</div>
                <div className="text-sm font-semibold text-teal-200 mt-0.5">{classInfo.class_name} → {classInfo.event}</div>
              </div>
              <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-2 text-center">
                <div className="rounded-lg border border-teal-600/20 bg-slate-950/40 py-2">
                  <div className={`font-mono text-sm ${classInfo.eb05 >= 2 ? 'text-rose-300' : 'text-slate-200'}`}>{fmt(classInfo.eb05)}</div>
                  <div className="text-[9px] uppercase tracking-wide text-slate-500">Class EB05</div>
                </div>
                <div className="rounded-lg border border-teal-600/20 bg-slate-950/40 py-2">
                  <div className={`font-mono text-sm ${classInfo.ic025 > 0 ? 'text-rose-300' : 'text-slate-200'}`}>{fmt(classInfo.ic025)}</div>
                  <div className="text-[9px] uppercase tracking-wide text-slate-500">Class IC025</div>
                </div>
                <div className="rounded-lg border border-teal-600/20 bg-slate-950/40 py-2">
                  <div className="font-mono text-sm text-slate-200">{fmt(classInfo.prr, 1)}</div>
                  <div className="text-[9px] uppercase tracking-wide text-slate-500">Class PRR</div>
                </div>
                <div className="rounded-lg border border-teal-600/20 bg-slate-950/40 py-2">
                  <div className="font-mono text-sm text-slate-200">{classInfo.total_reports}</div>
                  <div className="text-[9px] uppercase tracking-wide text-slate-500">Pooled</div>
                </div>
              </div>
              <div className="mt-3">
                <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1">Class members reporting this event</div>
                <div className="flex flex-wrap gap-1.5">
                  {(classInfo.member_drugs || []).map((d) => (
                    <span key={d} className={`text-xs rounded-md px-2 py-0.5 border capitalize ${d === sig.drug ? 'bg-teal-500/20 text-teal-100 border-teal-500/40' : 'bg-slate-800 text-slate-300 border-slate-700'}`}>{d}</span>
                  ))}
                </div>
              </div>
            </>
          )}
          {readAcross.length > 0 && (
            <div className="mt-3 rounded-lg border border-teal-600/20 bg-slate-950/40 px-3 py-2">
              <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1">
                Read-across — structural analogs also reporting {md.pt || sig.symptom}
              </div>
              <div className="flex flex-wrap gap-1.5">
                {readAcross.map((r) => (
                  <span key={r.analog} className="text-xs rounded-md px-2 py-0.5 bg-teal-500/10 text-teal-200 border border-teal-500/25 capitalize"
                        title={`Tanimoto-style similarity ≈ ${r.similarity}`}>
                    {r.analog} <span className="text-teal-400/70">~{r.similarity}</span>
                  </span>
                ))}
              </div>
              <div className="mt-2 text-[11px] text-slate-500">
                Analogs reporting the same event strengthen a class-wide safety concern (chemical read-across).
              </div>
            </div>
          )}
        </Card>
      )}

      {/* vaccine safety (AESI / Brighton / SCRI) */}
      {vaccine && (
        <Card className="p-4 border-pink-600/40 bg-pink-500/[0.04]">
          <CardHeader
            title="💉 Vaccine safety (AESI / Brighton / SCRI)"
            subtitle="Vaccine-specific surveillance: Adverse Event of Special Interest, Brighton case-definition level, and a self-controlled risk interval"
            right={vaccine.aesi_name
              ? <Badge value={`AESI: ${vaccine.aesi_name.split(' (')[0]}`} className="bg-pink-500/15 text-pink-200 border-pink-500/30" />
              : <Badge value="No AESI match" className="bg-slate-600/20 text-slate-400 border-slate-600/30" />}
          />
          <div className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-3">
            <div className="rounded-lg border border-pink-600/20 bg-slate-950/40 px-3 py-2">
              <div className="text-[11px] uppercase tracking-wide text-slate-500">Vaccine</div>
              <div className="text-sm font-semibold text-pink-100 mt-0.5">{vaccine.vaccine_name || sig.drug}</div>
              {vaccine.platform && <div className="text-[11px] text-slate-500 mt-0.5">{vaccine.platform}</div>}
            </div>
            <div className="rounded-lg border border-pink-600/20 bg-slate-950/40 px-3 py-2">
              <div className="text-[11px] uppercase tracking-wide text-slate-500">AESI</div>
              <div className="text-sm text-slate-200 mt-0.5">{vaccine.aesi_name || 'None matched'}</div>
              {vaccine.aesi_soc && <div className="text-[11px] text-violet-300 mt-0.5">{vaccine.aesi_soc}</div>}
            </div>
            <div className="rounded-lg border border-pink-600/20 bg-slate-950/40 px-3 py-2">
              <div className="text-[11px] uppercase tracking-wide text-slate-500">Brighton level (surrogate)</div>
              {vaccine.brighton_level
                ? <span className={`inline-block mt-1 text-xs rounded px-2 py-0.5 border ${brightonClass(vaccine.brighton_level)}`}>{vaccine.brighton_label || `Level ${vaccine.brighton_level}`}</span>
                : <div className="text-sm text-slate-500 mt-0.5">—</div>}
            </div>
          </div>

          {vaccine.brighton_rationale && (
            <div className="mt-3 rounded-lg border border-pink-600/20 bg-slate-950/40 px-3 py-2">
              <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1">Brighton certainty rationale</div>
              <p className="text-sm text-slate-200 leading-relaxed">{vaccine.brighton_rationale}</p>
            </div>
          )}

          {vaccine.scri && (
            <div className="mt-3">
              <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1">
                SCRI — Self-Controlled Risk Interval (relative incidence)
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-center">
                <div className="rounded-lg border border-pink-600/20 bg-slate-950/40 py-2">
                  <div className={`font-mono text-sm ${vaccine.scri.ci && vaccine.scri.ci[0] > 1 ? 'text-rose-300' : 'text-slate-200'}`}>
                    {vaccine.scri.ri != null ? vaccine.scri.ri.toFixed(2) : '—'}
                  </div>
                  <div className="text-[9px] uppercase tracking-wide text-slate-500">Relative incidence</div>
                </div>
                <div className="rounded-lg border border-pink-600/20 bg-slate-950/40 py-2">
                  <div className="font-mono text-sm text-slate-200">
                    {vaccine.scri.ci && vaccine.scri.ci[0] != null ? `${vaccine.scri.ci[0]}–${vaccine.scri.ci[1]}` : '—'}
                  </div>
                  <div className="text-[9px] uppercase tracking-wide text-slate-500">95% CI</div>
                </div>
                <div className="rounded-lg border border-pink-600/20 bg-slate-950/40 py-2">
                  <div className="font-mono text-sm text-slate-200">
                    {vaccine.scri.risk_n ?? '—'}{vaccine.scri.risk_days != null ? ` / ${vaccine.scri.risk_days}d` : ''}
                  </div>
                  <div className="text-[9px] uppercase tracking-wide text-slate-500">Risk window (n / days)</div>
                </div>
                <div className="rounded-lg border border-pink-600/20 bg-slate-950/40 py-2">
                  <div className="font-mono text-sm text-slate-200">
                    {vaccine.scri.control_n ?? '—'}{vaccine.scri.control_days != null ? ` / ${vaccine.scri.control_days}d` : ''}
                  </div>
                  <div className="text-[9px] uppercase tracking-wide text-slate-500">Control window (n / days)</div>
                </div>
              </div>
            </div>
          )}

          <div className="mt-3 flex items-start gap-2 text-[11px] text-amber-400/80">
            <span>⚠</span>
            <span>
              Social-listening SCRI surrogate — anchored at the earliest reported onset because social data has
              no true per-patient vaccination dates. Brighton level is a diagnostic-certainty surrogate, not a
              clinically adjudicated case-definition level.
            </span>
          </div>
        </Card>
      )}

      {/* spatial (geographic) cluster detection — Kulldorff-style scan */}
      {spatial && (
        <Card className="p-4 border-emerald-600/40 bg-emerald-500/[0.04]">
          <CardHeader
            title="📍 Geographic clustering"
            subtitle="Are this signal's reports concentrated in one country/region beyond expectation? (Kulldorff-style Poisson spatial scan)"
            right={<Badge value={`RR ${spatial.rr?.toFixed(1)}×`} className="bg-emerald-500/15 text-emerald-300 border-emerald-500/30" />}
          />
          <div className="mt-3 rounded-lg border border-emerald-600/20 bg-slate-950/40 px-3 py-2">
            <div className="text-[11px] uppercase tracking-wide text-slate-500">Hotspot ({spatial.level})</div>
            <div className="text-sm font-semibold text-emerald-200 mt-0.5">{spatial.hotspot}</div>
          </div>
          <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-2 text-center">
            <div className="rounded-lg border border-emerald-600/20 bg-slate-950/40 py-2">
              <div className="font-mono text-sm text-emerald-300">{spatial.observed}</div>
              <div className="text-[9px] uppercase tracking-wide text-slate-500">Observed</div>
            </div>
            <div className="rounded-lg border border-emerald-600/20 bg-slate-950/40 py-2">
              <div className="font-mono text-sm text-slate-200">{fmt(spatial.expected, 1)}</div>
              <div className="text-[9px] uppercase tracking-wide text-slate-500">Expected</div>
            </div>
            <div className="rounded-lg border border-emerald-600/20 bg-slate-950/40 py-2">
              <div className={`font-mono text-sm ${spatial.rr >= 2 ? 'text-emerald-300' : 'text-slate-200'}`}>{fmt(spatial.rr, 1)}×</div>
              <div className="text-[9px] uppercase tracking-wide text-slate-500">Relative risk</div>
            </div>
            <div className="rounded-lg border border-emerald-600/20 bg-slate-950/40 py-2">
              <div className={`font-mono text-sm ${spatial.llr >= 3.84 ? 'text-emerald-300' : 'text-slate-200'}`}>{fmt(spatial.llr, 1)}</div>
              <div className="text-[9px] uppercase tracking-wide text-slate-500">LLR (scan)</div>
            </div>
          </div>
          {(() => {
            const areas = (spatial.by_area || []).filter((a) => a.observed > 0)
              .sort((a, b) => (b.rr || 0) - (a.rr || 0)).slice(0, 8);
            const maxRr = Math.max(1, ...areas.map((a) => a.rr || 0));
            return (
              <div className="mt-3">
                <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1.5">
                  Per-area relative risk ({spatial.level})
                </div>
                <div className="space-y-1.5">
                  {areas.map((a) => (
                    <div key={a.area} className="flex items-center gap-2 text-xs">
                      <span className={`w-32 truncate ${a.area === spatial.hotspot ? 'text-emerald-300 font-medium' : 'text-slate-300'}`}
                            title={a.area}>{a.area}</span>
                      <div className="flex-1 h-3 rounded bg-slate-800 overflow-hidden">
                        <div className={`h-full ${a.area === spatial.hotspot ? 'bg-emerald-500/70' : 'bg-slate-600/70'}`}
                             style={{ width: `${Math.max(4, ((a.rr || 0) / maxRr) * 100)}%` }} />
                      </div>
                      <span className="w-24 text-right font-mono text-slate-400">
                        {a.observed} obs · {a.rr?.toFixed(1)}×
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            );
          })()}
          <div className="mt-3 flex items-start gap-2 text-[11px] text-amber-400/80">
            <span>⚠</span>
            <span>
              Geolocation is inferred at the post level and is coarse (country / region). A cluster is a
              hypothesis for follow-up — a possible bad batch, counterfeit/substandard product in a market,
              or regional practice/reporting effect — not a confirmed defect. Expected counts derive from the
              corpus-wide geographic distribution of all adverse-event reports.
            </span>
          </div>
        </Card>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card className="lg:col-span-2 p-2">
          <CardHeader title="Reporting trend" subtitle="Daily supporting-report volume (spike detection via z-score)" />
          <div className="h-56 mt-2">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={sig.trend_series || []}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#64748b' }} tickFormatter={(d) => d?.slice(5)} />
                <YAxis tick={{ fontSize: 10, fill: '#64748b' }} allowDecimals={false} />
                <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }} />
                <Bar dataKey="count" fill={sig.spike_flag ? '#f43f5e' : '#38bdf8'} radius={[3, 3, 0, 0]} name="Reports" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card className="p-4">
          <CardHeader title="External evidence"
                      subtitle="Cross-corroboration across keyless regulatory + literature sources" />
          <div className="mt-3 space-y-3 text-sm">
            {/* openFDA FAERS / MAUDE */}
            <div className="rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2">
              <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1">openFDA {evidenceName} (US)</div>
              {fda.available ? (
                <div className="text-slate-200">
                  {(fda.report_count || 0).toLocaleString()} {evidenceName} reports
                  <span className="text-emerald-300 text-xs"> · +{fda.confidence_boost}% confidence</span>
                </div>
              ) : (
                <div className="text-slate-500 text-xs">No {evidenceName} corroboration found.</div>
              )}
            </div>

            {/* Real FDA device classification (devices only) */}
            {isDevice && dc.available && (
              <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2">
                <div className="text-[11px] uppercase tracking-wide text-amber-400/80 mb-1">FDA device classification (live)</div>
                <div className="text-slate-200 text-xs">
                  Product code <span className="font-mono text-amber-200">{dc.product_code || '—'}</span>
                  {dc.device_class && <> · Class <span className="text-amber-200">{dc.device_class}</span></>}
                </div>
                {dc.regulation_number && <div className="text-slate-400 text-xs">21 CFR {dc.regulation_number}{dc.medical_specialty ? ` · ${dc.medical_specialty}` : ''}</div>}
              </div>
            )}
            {/* EUDAMED EU registry (devices only) */}
            {isDevice && dc.eudamed?.available && (
              <div className="rounded-lg border border-blue-500/20 bg-blue-500/5 px-3 py-2">
                <div className="text-[11px] uppercase tracking-wide text-blue-400/80 mb-1">🇪🇺 EUDAMED EU registry (live)</div>
                <div className="text-slate-200 text-xs space-y-0.5">
                  {dc.eudamed.device_name && <div>{dc.eudamed.device_name}</div>}
                  {dc.eudamed.manufacturer && <div className="text-slate-400">Manufacturer: {dc.eudamed.manufacturer}{dc.eudamed.country ? ` · ${dc.eudamed.country}` : ''}</div>}
                  <div className="flex flex-wrap gap-2 mt-1">
                    {dc.eudamed.risk_class && <span className="rounded px-1.5 py-0.5 bg-blue-900/30 border border-blue-700/30 text-blue-200 text-[10px]">Class {dc.eudamed.risk_class}</span>}
                    {dc.eudamed.basic_udi && <span className="rounded px-1.5 py-0.5 bg-slate-800 border border-slate-700 text-slate-300 text-[10px] font-mono">UDI {dc.eudamed.basic_udi?.slice(0,16)}…</span>}
                    {dc.eudamed.gmdn_term && <span className="rounded px-1.5 py-0.5 bg-slate-800 border border-slate-700 text-slate-300 text-[10px]">GMDN: {dc.eudamed.gmdn_term?.slice(0,40)}</span>}
                  </div>
                </div>
              </div>
            )}

            {/* DailyMed label (drugs) */}
            {!isDevice && (
              <div className="rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2">
                <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1">DailyMed label</div>
                {label.available ? (
                  <div className="text-slate-200 text-xs">
                    {label.url
                      ? <a href={label.url} target="_blank" rel="noreferrer" className="text-sky-400 hover:underline">{label.title || 'Approved SPL on file'}</a>
                      : (label.title || 'Approved label on file')}
                    <span className="text-emerald-400"> · label-listed product</span>
                  </div>
                ) : (
                  <div className="text-slate-500 text-xs">No matching SPL found.</div>
                )}
              </div>
            )}

            {/* Recall / enforcement */}
            <div className={`rounded-lg border px-3 py-2 ${recall.available ? 'border-rose-500/25 bg-rose-500/5' : 'border-slate-800 bg-slate-950/40'}`}>
              <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1">FDA recalls / enforcement</div>
              {recall.available ? (
                <div className="text-slate-200 text-xs">
                  <span className="text-rose-300 font-medium">{(recall.count || 0).toLocaleString()} recall record(s)</span>
                  {recall.latest?.classification && <> · <span className="text-rose-200">{recall.latest.classification}</span></>}
                  {recall.latest?.date && <span className="text-slate-400"> · {recall.latest.date}</span>}
                  {recall.latest?.reason && <div className="text-slate-400 mt-1 line-clamp-2">{recall.latest.reason}</div>}
                </div>
              ) : (
                <div className="text-slate-500 text-xs">No recalls on record.</div>
              )}
            </div>

            {/* PubMed literature */}
            <div className="rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2">
              <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1">Literature (PubMed)</div>
              {lit.available ? (
                <div className="text-slate-200 text-xs">
                  <span className="text-violet-300 font-medium">{(lit.count || 0).toLocaleString()} articles</span>
                  {lit.top?.url && (
                    <div className="mt-1">
                      <a href={lit.top.url} target="_blank" rel="noreferrer" className="text-sky-400 hover:underline line-clamp-2">
                        {lit.top.title || `PMID ${lit.top.pmid}`}
                      </a>
                    </div>
                  )}
                </div>
              ) : (
                <div className="text-slate-500 text-xs">No indexed literature for this pair.</div>
              )}
            </div>
          </div>
        </Card>
      </div>

      {/* Thread corroboration (RAG traffic light) */}
      {sig.thread_score && (
        <Card className="p-4">
          <CardHeader
            title="Thread / cohort corroboration"
            subtitle="Algo-Pharma-style multi-post confidence — not a single post in isolation"
            right={
              <Badge
                value={`${sig.thread_score.rag} · ${(sig.thread_score.confidence * 100).toFixed(0)}%`}
                className={
                  sig.thread_score.rag === 'Red'
                    ? 'bg-rose-500/15 text-rose-300 border-rose-500/30'
                    : sig.thread_score.rag === 'Amber'
                      ? 'bg-amber-500/15 text-amber-300 border-amber-500/30'
                      : 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
                }
              />
            }
          />
          <p className="mt-2 text-sm text-slate-300">{sig.thread_score.rationale}</p>
          <div className="mt-3 flex flex-wrap gap-3 text-xs text-slate-500">
            <span>corroborating: <span className="text-slate-200">{sig.thread_score.corroborating}</span></span>
            <span>contradicting: <span className="text-slate-200">{sig.thread_score.contradicting}</span></span>
            <span>AE-flagged: <span className="text-slate-200">{sig.thread_score.ae_flagged}</span></span>
            <span>n: <span className="text-slate-200">{sig.thread_score.n_posts}</span></span>
          </div>
        </Card>
      )}

      {/* supporting posts with explainability */}
      <Card className="p-4">
        <CardHeader title="Source traceability" subtitle={`${sig.supporting_posts?.length || 0} supporting posts with per-gate reasoning`} />
        <div className="mt-4 space-y-4">
          {(sig.supporting_posts || []).map((p) => (
            <div key={p.id} className="rounded-lg border border-slate-800 bg-slate-950/40 p-4">
              <div className="flex items-center justify-between text-xs text-slate-400 mb-2 flex-wrap gap-1">
                <span className="uppercase tracking-wide">
                  {p.platform} · {p.posted_at?.slice(0, 10)}
                  {p.country && <span className="text-emerald-400 normal-case"> · {p.country}</span>}
                </span>
                <div className="flex items-center gap-2 flex-wrap">
                  {p.translated && <Badge value={`translated from ${p.lang_name}`} className="bg-cyan-500/15 text-cyan-300 border-cyan-500/30" />}
                  {p.pii_found?.length > 0 && <Badge value={`PII scrubbed: ${p.pii_found.join(', ')}`} className="bg-slate-700/40 text-slate-300 border-slate-600/40" />}
                  <Badge value={`${p.sentiment.label} ${p.sentiment.score}`} className={p.sentiment.label === 'NEGATIVE' ? 'bg-rose-500/15 text-rose-300 border-rose-500/30' : 'bg-slate-600/20 text-slate-300 border-slate-600/30'} />
                  {p.ae_flag && <Badge value={`AE ${(p.ae_confidence * 100).toFixed(0)}%`} className="bg-emerald-500/15 text-emerald-300 border-emerald-500/30" />}
                </div>
              </div>
              <p className="text-sm text-slate-200 leading-relaxed">{highlight(p.text, p.entities)}</p>
              {p.translated && p.text_original && (
                <p className="mt-1.5 text-xs text-slate-500 italic border-l-2 border-slate-700 pl-2">Original ({p.lang_name}): {p.text_original}</p>
              )}
              <div className="mt-3 pt-3 border-t border-slate-800">
                <div className="text-[11px] text-slate-500 mb-2">Explainability — 4-gate adverse-event decision:</div>
                <GateTrace gates={p.gate_trace} explainability={p.explainability} />
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
