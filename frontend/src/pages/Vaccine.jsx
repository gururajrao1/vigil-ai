import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useRefresh } from '../App';
import { Badge, Card, CardHeader, Spinner } from '../components/ui';

// Vaccine pharmacovigilance is a distinct discipline: biologicals given to healthy
// people are reviewed around a curated AESI list, graded against Brighton diagnostic
// case-definition levels, and quantified with self-controlled designs (SCRI). This
// page shows the AESI reference plus the detected vaccine -> AESI signals with their
// Brighton level and SCRI relative incidence (clearly-labelled social-listening
// surrogates — no true per-patient vaccination dates are available).
function brightonClass(level) {
  if (level === 1) return 'bg-rose-500/15 text-rose-300 border-rose-500/30';
  if (level === 2) return 'bg-amber-500/15 text-amber-300 border-amber-500/30';
  return 'bg-slate-600/20 text-slate-300 border-slate-600/30';
}

export default function Vaccine({ embedded = false }) {
  const { tick } = useRefresh();
  const nav = useNavigate();
  const [data, setData] = useState(null);

  useEffect(() => { api.vaccine().then(setData).catch(() => setData({ groups: [], reference: {} })); }, [tick]);

  if (!data) return <Spinner label="Assessing vaccine safety…" />;
  const groups = data.groups || [];
  const ref = data.reference || {};

  return (
    <div className="space-y-5">
{!embedded && (
      <div>
        <h2 className="text-xl font-bold text-slate-100 flex items-center gap-2">💉 Vaccine safety surveillance</h2>
        <p className="text-sm text-slate-400 mt-1">
          Vaccine pharmacovigilance is its own discipline. Signals for vaccines are reviewed
          against a curated list of <strong>Adverse Events of Special Interest (AESI)</strong>,
          graded with a <strong>Brighton Collaboration</strong> case-definition level, and
          quantified with a <strong>Self-Controlled Risk Interval (SCRI)</strong> relative
          incidence.
          <span className="text-amber-500/80"> Brighton levels &amp; SCRI here are social-listening
          surrogates — no true per-patient vaccination dates exist in social data.</span>
        </p>
      </div>

)}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="Vaccine signals" value={data.vaccine_signal_count ?? 0} />
        <Stat label="AESI matched" value={data.aesi_count ?? 0} />
        <Stat label="Registered vaccines" value={ref.vaccine_count ?? (ref.vaccines || []).length} />
        <Stat label="AESI defined" value={ref.aesi_count ?? (ref.aesi || []).length} />
      </div>

      {groups.length === 0 && (
        <Card className="p-8 text-center text-slate-500">
          No vaccine AESI signals yet. Load the demo corpus.
        </Card>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {groups.map((g) => (
          <Card key={g.aesi_key} className="p-4">
            <CardHeader
              title={<span className="flex items-center gap-2">💉 {g.aesi_name}</span>}
              subtitle={g.note}
              right={g.best_brighton_level
                ? <Badge value={`Brighton L${g.best_brighton_level}`} className={brightonClass(g.best_brighton_level)} />
                : <Badge value="watch" className="bg-slate-600/20 text-slate-400 border-slate-600/30" />}
            />
            <div className="mt-1 text-[11px] text-slate-500">
              {g.soc} · {g.n_vaccines} vaccine{g.n_vaccines === 1 ? '' : 's'} · {g.total_reports} reports
            </div>
            <div className="app-table-scroll mt-3">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-wide text-slate-500 border-b border-slate-800">
                  <th className="py-2">Vaccine → event</th>
                  <th className="py-2" title="Brighton case-definition level surrogate (1 = highest certainty)">Brighton</th>
                  <th className="py-2" title="SCRI relative incidence (risk vs control window; social-listening surrogate)">SCRI RI</th>
                  <th className="py-2">Reports</th>
                  <th className="py-2"></th>
                </tr>
              </thead>
              <tbody>
                {g.signals.map((r) => (
                  <tr key={r.signal_id}
                      className="border-b border-slate-800/40 hover:bg-slate-800/30 cursor-pointer"
                      onClick={() => nav(`/signals/${r.signal_id}`)}
                      title={r.vaccine_name || r.vaccine}>
                    <td className="py-2 text-slate-100 capitalize">
                      {r.vaccine} <span className="text-slate-500">→</span> {r.event}
                    </td>
                    <td className="py-2">
                      {r.brighton_level
                        ? <span className={`text-[11px] rounded px-1.5 py-0.5 border ${brightonClass(r.brighton_level)}`}>L{r.brighton_level}</span>
                        : <span className="text-slate-600">—</span>}
                    </td>
                    <td className={`py-2 font-mono ${r.scri_ci && r.scri_ci[0] > 1 ? 'text-rose-300' : 'text-slate-300'}`}>
                      {r.scri_ri != null ? r.scri_ri.toFixed(2) : '—'}
                      {r.scri_ci && r.scri_ci[0] != null && (
                        <span className="text-[10px] text-slate-500"> ({r.scri_ci[0]}–{r.scri_ci[1]})</span>
                      )}
                    </td>
                    <td className="py-2 text-slate-300">{r.post_count}</td>
                    <td className="py-2">{r.sdr_flag && <Badge value="SDR" className="bg-rose-500/15 text-rose-300 border-rose-500/30" />}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          </Card>
        ))}
      </div>

      {/* AESI reference */}
      {(ref.aesi || []).length > 0 && (
        <Card className="p-4">
          <CardHeader title="AESI reference"
                      subtitle="Adverse Events of Special Interest (Brighton / CEPI / SPEAC-aligned) monitored for vaccines" />
          <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3">
            {ref.aesi.map((a) => (
              <div key={a.key} className="rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2">
                <div className="flex items-center justify-between">
                  <div className="text-sm font-semibold text-slate-100">{a.name}</div>
                  <div className="text-[10px] text-violet-300">{a.soc}</div>
                </div>
                <div className="text-xs text-slate-400 mt-1">{a.note}</div>
                <div className="text-[10px] text-slate-500 mt-1">
                  PTs: {(a.narrow || []).slice(0, 4).join(', ')}
                </div>
              </div>
            ))}
          </div>
          <div className="mt-3 text-[11px] text-slate-600">{ref.note}</div>
        </Card>
      )}

      {/* vaccine registry */}
      {(ref.vaccines || []).length > 0 && (
        <Card className="p-4">
          <CardHeader title="Vaccine registry" subtitle="Curated vaccines recognised for vaccine-specific safety surveillance" />
          <div className="mt-3 flex flex-wrap gap-2">
            {ref.vaccines.map((v) => (
              <span key={v.generic}
                    className="text-xs rounded-md px-2 py-1 bg-slate-800 border border-slate-700 text-slate-200"
                    title={`Platform: ${v.platform} · e.g. ${(v.synonyms || []).slice(0, 3).join(', ')}`}>
                💉 {v.name} <span className="text-slate-500">· {v.platform}</span>
              </span>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div className="rounded-lg bg-slate-900/60 border border-slate-800 py-3 text-center">
      <div className="text-2xl font-bold font-mono text-slate-100">{value}</div>
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
    </div>
  );
}
