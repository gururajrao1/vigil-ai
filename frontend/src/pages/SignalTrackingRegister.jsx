import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, getToken } from '../api';
import { Button, Card, PaginationBar, Spinner } from '../components/ui';
import LabelComparisonBadge from '../components/LabelComparisonBadge';

const BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '');
const PAGE_SIZE = 25;

// Plain-language lifecycle names (mirrors STATE_LABELS in app/analytics/lifecycle.py).
const LC_STATE_LABELS = {
  new: 'Inbox',
  under_evaluation: 'Looking into it',
  validated: 'Looks real',
  prioritized: 'High priority',
  assessed: 'Written up',
  closed: 'Done',
  rejected: 'Not a concern',
};

const stateLabel = (s) => LC_STATE_LABELS[s] || String(s || '').replace(/_/g, ' ');

/** GVP Module IX Signal Tracking Register. */
export default function SignalTrackingRegister({ embedded = false }) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [acting, setActing] = useState(null);
  const [page, setPage] = useState(1);

  const load = (nextPage = page) => {
    setBusy(true);
    setErr(null);
    const offset = (Math.max(1, nextPage) - 1) * PAGE_SIZE;
    api.gvpRegister({ limit: PAGE_SIZE, offset })
      .then((d) => {
        setData(d);
        setPage(d.page || nextPage);
      })
      .catch((e) => setErr(e?.message || 'Register failed'))
      .finally(() => setBusy(false));
  };

  useEffect(() => { load(1); }, []);

  const goPage = (p) => {
    setPage(p);
    load(p);
  };

  const advance = async (id, status) => {
    setActing(id);
    try {
      await api.updateLifecycle(id, { status });
      await load(page);
    } catch (e) {
      setErr(e?.message || String(e));
    }
    setActing(null);
  };

  const download = (path, filename) => {
    const headers = {};
    const t = getToken?.();
    if (t) headers.Authorization = `Bearer ${t}`;
    fetch(`${BASE}${path}`, { headers })
      .then((r) => r.blob())
      .then((b) => {
        const url = URL.createObjectURL(b);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
      })
      .catch((e) => setErr(e?.message || 'Export failed'));
  };

  if (busy && !data) return <Spinner label="Loading GVP register…" />;

  const rows = data?.rows || [];
  const total = data?.total ?? rows.length;

  return (
    <div className="space-y-4">
      {!embedded && (
        <div>
          <h2 className="text-xl font-bold text-slate-100">Signal Tracking Register</h2>
          <p className="text-sm text-slate-400 mt-1">
            GVP Module IX–shaped register with lifecycle actions and one-click SAR / PBRER drafts.
          </p>
        </div>
      )}

      <Card className="p-3 border-slate-800">
        <div className="text-[11px] uppercase tracking-wide text-slate-500">How this works</div>
        <p className="mt-1 text-sm text-slate-300 leading-relaxed">
          Detect finds product → event signals. The register is the queue that tracks each one
          while a reviewer works it: label status, triangulation, and priority are snapshots, and
          the action buttons move a signal one step along the governed workflow. Open a row to do
          the full assessment on Signal Detail.
        </p>
        <p className="mt-2 text-[11px] font-mono text-slate-500">
          Inbox → Looking into it → Looks real → High priority → Written up → Done
          <span className="text-slate-600"> (or Not a concern at any stage)</span>
        </p>
      </Card>

      <div className="flex flex-wrap gap-2">
        <Button variant="primary" disabled={busy} onClick={() => load(page)}>
          {busy ? 'Refreshing…' : 'Refresh'}
        </Button>
        <Button
          onClick={() => download('/api/gvp/pbrer.pdf', 'vigilai_pbrer_draft.pdf')}
        >
          Export PBRER (PDF)
        </Button>
        <Button
          onClick={() => download('/api/gvp/pbrer.docx', 'vigilai_pbrer_draft.docx')}
        >
          Export PBRER (DOCX)
        </Button>
      </div>

      {err && <p className="text-sm text-rose-300">{err}</p>}

      <PaginationBar
        page={page}
        pageSize={PAGE_SIZE}
        total={total}
        onPageChange={goPage}
        label="signals"
      />

      <Card className="overflow-hidden">
        <div className="overflow-x-auto max-h-[32rem]">
          <table className="min-w-full text-xs">
            <thead className="bg-slate-950 text-slate-400 sticky top-0">
              <tr>
                <th className="text-left p-2">Product → Event</th>
                <th className="text-left p-2">Strength</th>
                <th className="text-left p-2">Label</th>
                <th className="text-left p-2">Triangulation</th>
                <th className="text-left p-2">Lifecycle</th>
                <th className="text-right p-2">Priority</th>
                <th className="text-left p-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {busy && (
                <tr>
                  <td colSpan={7} className="p-3 text-slate-500">Loading page…</td>
                </tr>
              )}
              {!busy && rows.length === 0 ? (
                <tr>
                  <td colSpan={7} className="p-4 text-slate-500">
                    No signals in register — run Detect / Load PV demo.
                  </td>
                </tr>
              ) : (
                rows.map((r) => (
                  <tr key={r.id} className="border-t border-slate-800 text-slate-300">
                    <td className="p-2">
                      <Link to={`/signals/${r.id}`} className="text-sky-300 hover:underline capitalize">
                        {r.product} → {r.event}
                      </Link>
                    </td>
                    <td className="p-2">{r.strength}</td>
                    <td className="p-2">
                      <LabelComparisonBadge
                        labelFilter={{
                          tag: r.label_tag,
                          weber: { weber_adjusted: r.weber_adjusted },
                        }}
                        novelty={r.label_novelty}
                      />
                    </td>
                    <td className="p-2 font-mono text-[10px]">
                      {r.triangulation_tier || '—'}
                      {r.triangulated_risk_score != null && (
                        <span className="text-slate-500"> · {r.triangulated_risk_score}</span>
                      )}
                    </td>
                    <td className="p-2">
                      <div className="text-slate-200">{stateLabel(r.lifecycle_status)}</div>
                      <div className="text-[10px] text-slate-500">
                        GVP {r.gvp_alias || '—'}
                      </div>
                    </td>
                    <td className="p-2 text-right tabular-nums">{r.priority_score}</td>
                    <td className="p-2">
                      <div className="flex flex-wrap gap-1">
                        {(r.next_states || []).map((st) => (
                          <button
                            key={st}
                            type="button"
                            disabled={acting === r.id}
                            onClick={() => advance(r.id, st)}
                            title={`Move to ${stateLabel(st)} (${st})`}
                            className="text-[10px] border border-slate-700 px-1.5 py-0.5 text-slate-300 hover:border-sky-500/40 hover:text-sky-200"
                            style={{ borderRadius: 4 }}
                          >
                            → {stateLabel(st)}
                          </button>
                        ))}
                        <button
                          type="button"
                          onClick={() => download(`/api/signals/${r.id}/sar.pdf`, `signal_${r.id}_sar.pdf`)}
                          className="text-[10px] border border-teal-700/50 px-1.5 py-0.5 text-teal-200"
                          style={{ borderRadius: 4 }}
                        >
                          SAR PDF
                        </button>
                        <button
                          type="button"
                          onClick={() => download(`/api/signals/${r.id}/pbrer.pdf`, `signal_${r.id}_pbrer.pdf`)}
                          className="text-[10px] border border-teal-700/50 px-1.5 py-0.5 text-teal-200"
                          style={{ borderRadius: 4 }}
                        >
                          PBRER
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Card>

      <PaginationBar
        page={page}
        pageSize={PAGE_SIZE}
        total={total}
        onPageChange={goPage}
        label="signals"
      />

      {data?.disclaimer && (
        <p className="text-[10px] text-slate-500">{data.disclaimer}</p>
      )}
    </div>
  );
}
