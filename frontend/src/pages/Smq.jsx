import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useRefresh } from '../App';
import { Badge, Card, CardHeader, Spinner } from '../components/ui';

const VIEWS = [
  { id: 'active', label: 'Active in corpus' },
  { id: 'catalog', label: 'Full catalog' },
];

// Syndrome-level (Standardised MedDRA Query) disproportionality. Pools related
// Preferred Terms so a drug that is weak on any single PT can surface as a signal
// at the syndrome level (how real safety teams review).
export default function Smq({ embedded = false }) {
  const { tick } = useRefresh();
  const nav = useNavigate();
  const [data, setData] = useState(null);
  const [view, setView] = useState('active');
  const [expanded, setExpanded] = useState({});

  useEffect(() => { api.smq().then(setData).catch(() => setData({ groups: [], definitions: [] })); }, [tick]);

  if (!data) return <Spinner label="Aggregating syndromes…" />;
  const groups = data.groups || [];
  const definitions = data.definitions || [];
  const activeByKey = Object.fromEntries(groups.map((g) => [g.smq, g]));

  const toggleExpanded = (key) => setExpanded((prev) => ({ ...prev, [key]: !prev[key] }));

  return (
    <div className="space-y-5">
{!embedded && (
      <div>
        <h2 className="text-xl font-bold text-slate-100">SMQ · Syndrome-level signals</h2>
        <p className="text-sm text-slate-400 mt-1">
          Standardised MedDRA Query grouping pools related Preferred Terms into clinical
          syndromes (DILI, SCAR, rhabdomyolysis, haemorrhage…), then runs the same
          disproportionality math at the group level — surfacing drugs whose risk is
          spread thinly across several individual terms.
          <span className="text-slate-600"> Open MedDRA-style surrogate ({definitions.length} bundled).</span>
        </p>
      </div>

)}
      <div className="flex flex-wrap items-center gap-2">
        {VIEWS.map((v) => (
          <button key={v.id} type="button" onClick={() => setView(v.id)}
                  className={`text-xs rounded-lg px-3 py-1.5 border transition-colors ${
                    view === v.id
                      ? 'bg-cyan-600/20 border-cyan-500/40 text-cyan-200'
                      : 'bg-slate-900/60 border-slate-700 text-slate-400 hover:text-slate-200'
                  }`}>
            {v.label}
            <span className="ml-1.5 text-slate-500">
              ({v.id === 'active' ? groups.length : definitions.length})
            </span>
          </button>
        ))}
        <span className="text-[11px] text-slate-600 ml-1">
          Active = syndromes with reports in your data · Catalog = all bundled SMQ definitions
        </span>
      </div>

      {view === 'active' && groups.length === 0 && (
        <Card className="p-8 text-center text-slate-500">
          No syndrome-level signals yet. Load the demo corpus, or switch to <strong>Full catalog</strong> to browse all {definitions.length || 13} bundled syndromes.
        </Card>
      )}

      {view === 'active' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          {groups.map((g) => (
            <SmqActiveCard
              key={g.smq}
              g={g}
              expanded={expanded[g.smq]}
              onToggle={() => toggleExpanded(g.smq)}
              onDrugClick={(drug) =>
                nav(`/signals?smq=${encodeURIComponent(g.smq)}&pin=${encodeURIComponent(drug)}`)
              }
            />
          ))}
        </div>
      )}

      {view === 'catalog' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
          {definitions.map((def) => {
            const active = activeByKey[def.key];
            const isOpen = expanded[def.key];
            return (
              <Card key={def.key} className={`p-4 ${active ? 'border-cyan-900/50' : 'border-slate-800'}`}>
                <CardHeader
                  title={<span className="flex items-center gap-2 text-sm">◈ {def.name}</span>}
                  subtitle={def.note}
                  right={active
                    ? (active.sdr_count > 0
                      ? <Badge value={`${active.sdr_count} SDR`} className="bg-rose-500/15 text-rose-300 border-rose-500/30" />
                      : <Badge value="active" className="bg-cyan-600/20 text-cyan-300 border-cyan-600/30" />)
                    : <Badge value="no data" className="bg-slate-700/30 text-slate-500 border-slate-600/30" />}
                />
                <div className="mt-1 text-[11px] text-slate-500">
                  <span className="font-mono text-slate-400">{def.key}</span> · {def.soc}
                  {active && <> · {active.total_reports} pooled reports</>}
                </div>
                <div className="mt-2">
                  <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1">Narrow PTs</div>
                  <div className="flex flex-wrap gap-1">
                    {(isOpen ? def.narrow : def.narrow.slice(0, 4)).map((pt) => (
                      <span key={pt} className="text-[10px] px-1.5 py-0.5 rounded bg-rose-950/40 border border-rose-900/30 text-rose-200/80">{pt}</span>
                    ))}
                  </div>
                </div>
                <div className="mt-2">
                  <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1">Broad PTs</div>
                  <div className="flex flex-wrap gap-1">
                    {(isOpen ? def.broad : def.broad.slice(0, 4)).map((pt) => (
                      <span key={pt} className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-400">{pt}</span>
                    ))}
                  </div>
                </div>
                <div className="mt-2 flex items-center gap-3">
                  {(def.narrow.length + def.broad.length) > 8 && (
                    <button type="button" onClick={() => toggleExpanded(def.key)}
                            className="text-[11px] text-cyan-400 hover:text-cyan-300">
                      {isOpen ? 'Show fewer PTs' : `Show all ${def.narrow.length + def.broad.length} member PTs`}
                    </button>
                  )}
                  {active && (
                    <button type="button" onClick={() => nav(`/signals?smq=${def.key}`)}
                            className="text-[11px] text-slate-400 hover:text-slate-200">
                      View signals →
                    </button>
                  )}
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}

function SmqActiveCard({ g, expanded, onToggle, onDrugClick }) {
  const drugs = expanded ? g.drugs : g.drugs.slice(0, 12);
  return (
    <Card className="p-4">
      <CardHeader
        title={<span className="flex items-center gap-2">◈ {g.name}</span>}
        subtitle={g.note}
        right={g.sdr_count > 0
          ? <Badge value={`${g.sdr_count} SDR`} className="bg-rose-500/15 text-rose-300 border-rose-500/30" />
          : <Badge value="watch" className="bg-slate-600/20 text-slate-400 border-slate-600/30" />}
      />
      <div className="mt-1 text-[11px] text-slate-500">
        <span className="font-mono text-slate-400">{g.smq}</span> · {g.soc} · {g.total_reports} pooled member-PT reports
      </div>
      <div className="app-table-scroll mt-3">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-[10px] uppercase tracking-wide text-slate-500 border-b border-slate-800">
            <th className="py-2">Drug</th>
            <th className="py-2" title="Group-level MGPS EB05 (≥2 = signal)">EB05</th>
            <th className="py-2" title="Group-level BCPNN IC025 (>0 = signal)">IC025</th>
            <th className="py-2">PRR</th>
            <th className="py-2">Reports</th>
            <th className="py-2"></th>
          </tr>
        </thead>
        <tbody>
          {drugs.map((d) => (
            <tr key={d.drug} className="border-b border-slate-800/40 hover:bg-slate-800/30 cursor-pointer"
                onClick={() => onDrugClick(d.drug)}
                title={`Open ${d.drug} within this SMQ · Member PTs: ${d.member_pts.map(([pt, n]) => `${pt} (${n})`).join(', ')}`}>
              <td className="py-2 capitalize text-sky-300 hover:text-sky-200">
                {d.drug}
                <div className="text-[10px] text-slate-500 normal-case">
                  {d.member_pts.slice(0, 3).map(([pt]) => pt).join(', ')}
                </div>
              </td>
              <td className={`py-2 font-mono ${d.eb05 >= 2 ? 'text-rose-300' : 'text-slate-400'}`}>{d.eb05?.toFixed(2)}</td>
              <td className={`py-2 font-mono ${d.ic025 > 0 ? 'text-rose-300' : 'text-slate-400'}`}>{d.ic025?.toFixed(2)}</td>
              <td className="py-2 font-mono text-slate-300">{d.prr?.toFixed(1)}</td>
              <td className="py-2 text-slate-300">{d.count}</td>
              <td className="py-2">{d.sdr_flag && <Badge value="SDR" className="bg-rose-500/15 text-rose-300 border-rose-500/30" />}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      {g.drugs.length > 12 && (
        <button type="button" onClick={onToggle} className="mt-2 text-xs text-cyan-400 hover:text-cyan-300">
          {expanded ? 'Show fewer drugs' : `Show all ${g.drugs.length} drugs`}
        </button>
      )}
    </Card>
  );
}
