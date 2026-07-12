/**
 * Signal workflow board — plain-language stages that map to GVP Module IX under the hood.
 */
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useRefresh } from '../App';
import { Card, CardHeader, Spinner } from '../components/ui';

const STATES = [
  {
    key: 'new',
    label: 'Inbox',
    doNext: 'Pick one up — start looking into it',
    color: 'border-slate-600/40 bg-slate-800/20',
  },
  {
    key: 'under_evaluation',
    label: 'Looking into it',
    doNext: 'Decide: looks real, or not a concern',
    color: 'border-sky-600/40 bg-sky-900/10',
  },
  {
    key: 'validated',
    label: 'Looks real',
    doNext: 'Raise priority if it needs faster attention',
    color: 'border-teal-600/40 bg-teal-900/10',
  },
  {
    key: 'prioritized',
    label: 'High priority',
    doNext: 'Write up findings (assessment / narrative)',
    color: 'border-amber-600/40 bg-amber-900/10',
  },
  {
    key: 'assessed',
    label: 'Written up',
    doNext: 'Mark done when the team is finished',
    color: 'border-violet-600/40 bg-violet-900/10',
  },
  {
    key: 'closed',
    label: 'Done',
    doNext: null,
    color: 'border-slate-700/40 bg-slate-900/20',
  },
];

const REJECTED = {
  key: 'rejected',
  label: 'Not a concern',
  doNext: null,
  color: 'border-rose-700/40 bg-rose-900/10',
};

const LABEL_BY_KEY = Object.fromEntries(
  [...STATES, REJECTED].map((s) => [s.key, s.label]),
);

const VALID_TRANSITIONS = {
  new: ['under_evaluation', 'rejected'],
  under_evaluation: ['validated', 'rejected'],
  validated: ['prioritized', 'rejected'],
  prioritized: ['assessed', 'rejected'],
  assessed: ['closed', 'rejected'],
  closed: [],
  rejected: [],
};

function priorityColor(score) {
  if (score >= 70) return 'text-rose-400';
  if (score >= 40) return 'text-amber-400';
  return 'text-emerald-400';
}

function priorityBg(score) {
  if (score >= 70) return 'bg-rose-500/20 border-rose-500/30';
  if (score >= 40) return 'bg-amber-500/20 border-amber-500/30';
  return 'bg-emerald-500/20 border-emerald-500/30';
}

function strengthColor(s) {
  return s === 'STRONG' ? 'text-rose-300' : s === 'MODERATE' ? 'text-amber-300' : 'text-slate-400';
}

function noveltyBadge(n) {
  if (n === 'novel') {
    return (
      <span className="text-[10px] bg-violet-500/20 text-violet-300 border border-violet-500/30 rounded px-1" title="Not listed on the product label (labeling-gap surrogate)">
        new vs label
      </span>
    );
  }
  if (n === 'boxed') {
    return (
      <span className="text-[10px] bg-amber-500/20 text-amber-300 border border-amber-500/30 rounded px-1" title="Matches a known boxed / black-box warning topic">
        boxed warning
      </span>
    );
  }
  if (n === 'in_label') {
    return (
      <span className="text-[10px] bg-teal-500/20 text-teal-300 border border-teal-500/30 rounded px-1" title="Already listed in labeled adverse reactions">
        known on label
      </span>
    );
  }
  if (n === 'not_applicable') {
    return (
      <span className="text-[10px] bg-slate-700/40 text-slate-400 border border-slate-600/30 rounded px-1" title="Devices are not scored against drug labels">
        device (no label)
      </span>
    );
  }
  return null;
}

function SignalCard({ sig, onAdvance, advancing }) {
  const nav = useNavigate();
  const nextStates = VALID_TRANSITIONS[sig.lifecycle_status] || [];
  const nextKey = nextStates.filter((s) => s !== 'rejected')[0];
  const canReject = nextStates.includes('rejected');

  return (
    <div className="rounded-lg border border-slate-700/50 bg-slate-900/60 p-3 space-y-2 text-xs">
      <div
        className="font-semibold text-slate-100 cursor-pointer hover:text-teal-300 transition-colors leading-tight"
        onClick={() => nav(`/signals/${sig.id}`)}
        title="Open full signal"
      >
        {sig.drug} <span className="text-slate-500">→</span> {sig.meddra?.pt || sig.symptom}
      </div>

      <div className="flex items-center gap-2">
        <div className="flex-1 bg-slate-800 rounded-full h-1.5">
          <div
            className={`h-1.5 rounded-full ${sig.priority_score >= 70 ? 'bg-rose-500' : sig.priority_score >= 40 ? 'bg-amber-500' : 'bg-emerald-500'}`}
            style={{ width: `${Math.min(100, sig.priority_score || 0)}%` }}
          />
        </div>
        <span className={`font-mono font-bold tabular-nums w-8 text-right ${priorityColor(sig.priority_score || 0)}`}>
          {(sig.priority_score || 0).toFixed(0)}
        </span>
      </div>

      <div className="flex flex-wrap gap-1 items-center">
        <span className={`font-medium ${strengthColor(sig.strength)}`}>{sig.strength}</span>
        <span className="text-slate-600">·</span>
        <span className="text-slate-400">{sig.severity}</span>
        {sig.label_novelty && noveltyBadge(sig.label_novelty)}
        {sig.spike_flag && <span className="text-rose-400" title="Recent spike in mentions">spike</span>}
        {sig.maxsprt_crossed && <span className="text-amber-400" title="Sequential monitoring boundary crossed">watch</span>}
      </div>

      {sig.lifecycle_owner && (
        <div className="text-slate-500 truncate" title={sig.lifecycle_owner}>
          Owner: {sig.lifecycle_owner}
        </div>
      )}

      {nextStates.length > 0 && (
        <div className="flex items-center gap-1 pt-1 border-t border-slate-800/60">
          {nextKey && (
            <button
              type="button"
              disabled={advancing === sig.id}
              onClick={() => onAdvance(sig, nextKey)}
              className="flex-1 rounded px-2 py-1 bg-teal-600/20 hover:bg-teal-600/30 text-teal-300 border border-teal-600/30 transition-colors disabled:opacity-50"
            >
              {advancing === sig.id ? '…' : `→ ${LABEL_BY_KEY[nextKey] || nextKey}`}
            </button>
          )}
          {canReject && (
            <button
              type="button"
              disabled={advancing === sig.id}
              onClick={() => onAdvance(sig, 'rejected')}
              className="rounded px-2 py-1 bg-rose-600/15 hover:bg-rose-600/25 text-rose-400 border border-rose-600/25 transition-colors disabled:opacity-50"
              title="Not a concern"
            >
              ✕
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export default function SignalLifecycle({ embedded = false }) {
  const { tick, bump } = useRefresh();
  const [summary, setSummary] = useState(null);
  const [signals, setSignals] = useState(null);
  const [advancing, setAdvancing] = useState(null);
  const [advanceModal, setAdvanceModal] = useState(null);
  const [owner, setOwner] = useState('');
  const [notes, setNotes] = useState('');
  const [err, setErr] = useState('');

  useEffect(() => {
    api.lifecycleSummary().then(setSummary).catch(() => setSummary(null));
    api.signals().then((d) => setSignals(d.signals)).catch(() => setSignals([]));
  }, [tick]);

  const signalsByStatus = STATES.reduce((acc, s) => {
    acc[s.key] = (signals || []).filter((sig) => (sig.lifecycle_status || 'new') === s.key);
    return acc;
  }, { rejected: (signals || []).filter((s) => (s.lifecycle_status || 'new') === 'rejected') });

  const openAdvance = (sig, toState) => {
    setAdvanceModal({ sig, toState });
    setOwner(sig.lifecycle_owner || '');
    setNotes('');
    setErr('');
  };

  const confirmAdvance = async () => {
    if (!advanceModal) return;
    setAdvancing(advanceModal.sig.id);
    setErr('');
    try {
      await api.updateLifecycle(advanceModal.sig.id, {
        status: advanceModal.toState,
        owner: owner || undefined,
        notes: notes || undefined,
      });
      bump();
      setAdvanceModal(null);
    } catch (e) {
      setErr(e.message || 'Could not move this signal');
    }
    setAdvancing(null);
  };

  if (!signals) return <Spinner label="Loading workflow…" />;

  return (
    <div className="space-y-6">
      {!embedded && (
        <div>
          <h2 className="text-2xl font-bold text-slate-100">Signal workflow</h2>
          <p className="text-sm text-slate-400 mt-1">
            Move each product–event pair from inbox to done. Alert Investigate drops pairs into “Looking into it”.
          </p>
        </div>
      )}

      <Card className="p-4 space-y-2">
        <div className="text-sm text-slate-200 font-medium">How to use this (no PV jargon required)</div>
        <ol className="text-xs text-slate-400 space-y-1.5 list-decimal pl-4">
          <li><span className="text-slate-300">Inbox</span> — new pairs waiting. Start with high priority scores or ones from the Alert inbox.</li>
          <li><span className="text-slate-300">Looking into it</span> — someone owns it; open the signal, check posts, confirm or dismiss in Ops if needed.</li>
          <li><span className="text-slate-300">Looks real → High priority → Written up → Done</span> — confidence grows, then document, then close.</li>
          <li><span className="text-slate-300">Not a concern</span> — noise, known label event you won’t escalate, or duplicate. Same outcome as Alert “False alarm”.</li>
        </ol>
        <p className="text-[11px] text-slate-600 pt-1">
          Under the hood this follows GVP Module IX stage names for audit exports — the board shows everyday labels.
        </p>
      </Card>

      {summary && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-7 gap-3">
          {[...STATES, REJECTED].map((s) => (
            <Card key={s.key} className={`p-3 border ${s.color}`}>
              <div className="text-xs text-slate-400 truncate" title={s.label}>{s.label}</div>
              <div className="text-2xl font-bold font-mono text-slate-100 mt-1">
                {summary.status_counts?.[s.key] ?? 0}
              </div>
            </Card>
          ))}
        </div>
      )}

      {summary && summary.top_by_priority?.length > 0 && (
        <Card className="p-4">
          <CardHeader title="Highest priority right now" subtitle="Start here if Inbox and Looking into it are busy" />
          <div className="mt-3 space-y-2">
            {summary.top_by_priority.map((s, i) => (
              <div key={s.id} className="app-priority-row text-xs">
                <span className="text-slate-600 w-4 text-right tabular-nums">{i + 1}.</span>
                <div className={`flex items-center gap-1.5 rounded px-2 py-0.5 border text-[11px] font-mono font-bold ${priorityBg(s.priority_score)}`}>
                  <span className={priorityColor(s.priority_score)}>{s.priority_score.toFixed(0)}</span>
                </div>
                <span className="text-slate-100 font-medium">{s.drug}</span>
                <span className="text-slate-500">→</span>
                <span className="text-slate-300">{s.event}</span>
                <span className={`text-[10px] ${strengthColor(s.strength)}`}>{s.strength}</span>
                <span className="text-slate-500">{s.severity}</span>
                <span className="sm:ml-auto text-slate-500">
                  {LABEL_BY_KEY[s.lifecycle_status] || s.lifecycle_status || 'Inbox'}
                </span>
              </div>
            ))}
          </div>
        </Card>
      )}

      <div className="app-kanban-scroll">
        <div className="flex gap-4 min-w-max">
          {STATES.map((state) => {
            const cols = signalsByStatus[state.key] || [];
            return (
              <div key={state.key} className={`w-64 rounded-xl border ${state.color} flex flex-col`}>
                <div className="px-3 py-2 border-b border-slate-700/50">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium text-slate-200">{state.label}</span>
                    <span className="text-xs bg-slate-800 text-slate-400 rounded-full px-2 py-0.5 shrink-0">{cols.length}</span>
                  </div>
                  {state.doNext && (
                    <div className="text-[10px] text-slate-500 mt-1 leading-snug">{state.doNext}</div>
                  )}
                </div>
                <div className="flex-1 p-2 space-y-2 overflow-y-auto max-h-[600px]">
                  {cols.length === 0 && (
                    <div className="text-center text-slate-600 text-xs py-4">Empty</div>
                  )}
                  {cols
                    .sort((a, b) => (b.priority_score || 0) - (a.priority_score || 0))
                    .map((sig) => (
                      <SignalCard
                        key={sig.id}
                        sig={sig}
                        onAdvance={openAdvance}
                        advancing={advancing}
                      />
                    ))}
                </div>
              </div>
            );
          })}

          {(signalsByStatus.rejected?.length > 0) && (
            <div className={`w-48 rounded-xl border ${REJECTED.color} flex flex-col`}>
              <div className="px-3 py-2 border-b border-slate-700/50">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-rose-300">{REJECTED.label}</span>
                  <span className="text-xs bg-slate-800 text-slate-400 rounded-full px-2 py-0.5">{signalsByStatus.rejected.length}</span>
                </div>
              </div>
              <div className="flex-1 p-2 space-y-2 overflow-y-auto max-h-[600px]">
                {signalsByStatus.rejected.map((sig) => (
                  <div key={sig.id} className="rounded-lg border border-rose-700/40 bg-slate-900/60 p-2 text-xs text-slate-400">
                    <div className="font-medium text-slate-300 leading-tight">{sig.drug} → {sig.meddra?.pt || sig.symptom}</div>
                    {sig.lifecycle_notes && <div className="mt-1 text-slate-500 line-clamp-2">{sig.lifecycle_notes}</div>}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {advanceModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-slate-900 border border-slate-700 rounded-xl p-6 w-full max-w-md shadow-2xl space-y-4">
            <div className="text-lg font-bold text-slate-100">
              {advanceModal.toState === 'rejected' ? 'Mark as not a concern' : 'Move forward'}
            </div>
            <div className="text-sm text-slate-400">
              <span className="text-slate-200 font-medium">
                {advanceModal.sig.drug} → {advanceModal.sig.meddra?.pt || advanceModal.sig.symptom}
              </span>
              <br />
              <span>{LABEL_BY_KEY[advanceModal.sig.lifecycle_status] || 'Inbox'}</span>
              {' → '}
              <span className={`font-medium ${advanceModal.toState === 'rejected' ? 'text-rose-300' : 'text-teal-300'}`}>
                {LABEL_BY_KEY[advanceModal.toState] || advanceModal.toState}
              </span>
            </div>

            <div className="space-y-3">
              <div>
                <label className="text-xs text-slate-400 block mb-1">Owner (who is handling this)</label>
                <input
                  type="text"
                  value={owner}
                  onChange={(e) => setOwner(e.target.value)}
                  placeholder="e.g. safety team / your name"
                  className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:outline-none focus:border-teal-600"
                />
              </div>
              <div>
                <label className="text-xs text-slate-400 block mb-1">Notes (optional)</label>
                <textarea
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  rows={3}
                  placeholder="Why you moved it / what you checked…"
                  className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:outline-none focus:border-teal-600 resize-none"
                />
              </div>
            </div>

            {err && <div className="text-rose-400 text-sm">{err}</div>}

            <div className="flex gap-3 justify-end">
              <button
                type="button"
                onClick={() => setAdvanceModal(null)}
                className="px-4 py-2 rounded-lg border border-slate-700 text-slate-300 hover:bg-slate-800 text-sm transition"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={!!advancing}
                onClick={confirmAdvance}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition disabled:opacity-50 ${
                  advanceModal.toState === 'rejected'
                    ? 'bg-rose-600/30 border border-rose-600/50 text-rose-200 hover:bg-rose-600/40'
                    : 'bg-teal-600/30 border border-teal-600/50 text-teal-200 hover:bg-teal-600/40'
                }`}
              >
                {advancing ? 'Saving…' : 'Confirm'}
              </button>
            </div>
          </div>
        </div>
      )}

      <p className="text-[10px] text-slate-600">
        Priority score 0–100: statistical strength × seriousness × label novelty × velocity × sequential watch.
        Every move is written to the audit trail.
      </p>
    </div>
  );
}
