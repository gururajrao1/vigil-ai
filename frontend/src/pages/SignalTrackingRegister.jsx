import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, getToken } from '../api';
import { Button, Card, Spinner } from '../components/ui';

const BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '');

/** GVP Module IX Signal Tracking Register. */
export default function SignalTrackingRegister({ embedded = false }) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [acting, setActing] = useState(null);

  const load = () => {
    setBusy(true);
    setErr(null);
    api.gvpRegister()
      .then(setData)
      .catch((e) => setErr(e?.message || 'Register failed'))
      .finally(() => setBusy(false));
  };

  useEffect(() => { load(); }, []);

  const advance = async (id, status) => {
    setActing(id);
    try {
      await api.updateLifecycle(id, { status });
      await load();
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

      <div className="flex flex-wrap gap-2">
        <Button variant="primary" disabled={busy} onClick={load}>
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
              {rows.length === 0 ? (
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
                    <td className="p-2 font-mono text-[10px]">{r.label_tag || '—'}</td>
                    <td className="p-2 font-mono text-[10px]">
                      {r.triangulation_tier || '—'}
                      {r.triangulated_risk_score != null && (
                        <span className="text-slate-500"> · {r.triangulated_risk_score}</span>
                      )}
                    </td>
                    <td className="p-2">
                      <div className="text-slate-200">{r.gvp_alias || r.lifecycle_status}</div>
                      <div className="text-[10px] text-slate-500">{r.lifecycle_status}</div>
                    </td>
                    <td className="p-2 text-right tabular-nums">{r.priority_score}</td>
                    <td className="p-2">
                      <div className="flex flex-wrap gap-1">
                        {(r.next_states || []).slice(0, 3).map((st) => (
                          <button
                            key={st}
                            type="button"
                            disabled={acting === r.id}
                            onClick={() => advance(r.id, st)}
                            className="text-[10px] border border-slate-700 px-1.5 py-0.5 text-slate-300 hover:border-sky-500/40 hover:text-sky-200"
                            style={{ borderRadius: 4 }}
                          >
                            → {st}
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

      {data?.disclaimer && (
        <p className="text-[10px] text-slate-500">{data.disclaimer}</p>
      )}
    </div>
  );
}
