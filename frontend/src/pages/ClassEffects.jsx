import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useRefresh } from '../App';
import { Badge, Card, CardHeader, Spinner } from '../components/ui';

const VIEWS = [
  { id: 'class', label: 'Class effects (2+ drugs)' },
  { id: 'all', label: 'All roll-ups' },
  { id: 'catalog', label: 'ATC & analog catalog' },
];

// Class effect (ATC pharmacological-subgroup roll-up) + chemical read-across.
// Pools member-drug reports per (ATC class, event) so a class-wide effect surfaces
// even when each individual drug looks modest — the way a safety team reasons about
// "is this the drug, or the whole class?".
export default function ClassEffects({ embedded = false }) {
  const { tick } = useRefresh();
  const nav = useNavigate();
  const [data, setData] = useState(null);
  const [view, setView] = useState('class');

  useEffect(() => { api.classEffect().then(setData).catch(() => setData({ groups: [], reference: {} })); }, [tick]);

  if (!data) return <Spinner label="Rolling up ATC classes…" />;
  const allGroups = data.groups || [];
  const classGroups = allGroups.filter((g) => g.class_effect);
  const singletonGroups = allGroups.filter((g) => !g.class_effect);
  const ref = data.reference || {};
  const atcClasses = ref.atc_classes || [];
  const analogFamilies = ref.analog_families || [];
  const visibleGroups = view === 'all' ? allGroups : classGroups;

  return (
    <div className="space-y-5">
{!embedded && (
      <div>
        <h2 className="text-xl font-bold text-slate-100">Class effects & chemical read-across</h2>
        <p className="text-sm text-slate-400 mt-1">
          Signals rolled up to the WHO <strong>ATC pharmacological subgroup</strong>: for each
          (class, event) we pool member-drug reports and re-run the disproportionality math at
          the class level. A <strong>class effect</strong> (2+ drugs in the class reporting the
          same event) argues the risk belongs to the class, not one molecule — and
          <strong> read-across</strong> flags structural analogs reporting the same event.
          <span className="text-slate-600"> {atcClasses.length} ATC classes · {analogFamilies.length} analog families bundled.</span>
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
              ({v.id === 'class' ? classGroups.length : v.id === 'all' ? allGroups.length : atcClasses.length + analogFamilies.length})
            </span>
          </button>
        ))}
      </div>

      {view !== 'catalog' && visibleGroups.length === 0 && (
        <Card className="p-8 text-center text-slate-500">
          {view === 'class'
            ? <>No multi-drug class effects yet. Try <strong>All roll-ups</strong> ({singletonGroups.length} single-drug pairs) or <strong>ATC &amp; analog catalog</strong>.</>
            : <>No class roll-ups yet. Load the demo corpus.</>}
        </Card>
      )}

      {view !== 'catalog' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          {visibleGroups.map((g) => (
            <ClassGroupCard key={`${g.class_key}:${g.event}`} g={g} nav={nav} />
          ))}
        </div>
      )}

      {view === 'catalog' && (
        <div className="space-y-6">
          <section>
            <h3 className="text-sm font-semibold text-slate-200 mb-3">WHO ATC pharmacological subgroups ({atcClasses.length})</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
              {atcClasses.map((c) => {
                const active = allGroups.filter((g) => g.class_key === c.key);
                return (
                  <Card key={c.key} className={`p-3 ${active.length ? 'border-cyan-900/40' : 'border-slate-800'}`}>
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="text-sm text-slate-100">{c.name}</div>
                        <div className="text-[11px] font-mono text-slate-500 mt-0.5">{c.key}</div>
                      </div>
                      {active.length > 0
                        ? <Badge value={`${active.length} event${active.length !== 1 ? 's' : ''}`} className="bg-cyan-600/20 text-cyan-300 border-cyan-600/30 shrink-0" />
                        : <Badge value="no data" className="bg-slate-700/30 text-slate-500 border-slate-600/30 shrink-0" />}
                    </div>
                    {active.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {active.slice(0, 6).map((g) => (
                          <span key={g.event} className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-400">
                            {g.event}{g.class_effect ? '' : ' (1 drug)'}
                          </span>
                        ))}
                        {active.length > 6 && <span className="text-[10px] text-slate-600">+{active.length - 6} more</span>}
                      </div>
                    )}
                  </Card>
                );
              })}
            </div>
          </section>

          <section>
            <h3 className="text-sm font-semibold text-slate-200 mb-3">Chemical read-across families ({analogFamilies.length})</h3>
            <p className="text-xs text-slate-500 mb-3">Structural analog groups used on Signal Detail to flag when similar molecules report the same event.</p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {analogFamilies.map((fam, i) => (
                <Card key={i} className="p-3">
                  <div className="text-[11px] text-slate-500 mb-2">Tanimoto surrogate ≈ {fam.similarity}</div>
                  <div className="flex flex-wrap gap-1.5">
                    {fam.members.map((m) => (
                      <span key={m} className="text-xs rounded-md px-2 py-0.5 bg-slate-800 border border-slate-700 text-slate-200 capitalize">{m}</span>
                    ))}
                  </div>
                </Card>
              ))}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

function ClassGroupCard({ g, nav }) {
  return (
    <Card className={`p-4 ${g.class_effect ? '' : 'opacity-80'}`}>
      <CardHeader
        title={<span className="flex items-center gap-2">⚗ {g.class_name}</span>}
        subtitle={<span>→ {g.event}{g.soc ? ` · ${g.soc}` : ''}</span>}
        right={g.sdr_flag
          ? <Badge value="SDR" className="bg-rose-500/15 text-rose-300 border-rose-500/30" />
          : g.class_effect
            ? <Badge value={`${g.n_drugs} drugs`} className="bg-cyan-600/20 text-cyan-300 border-cyan-600/30" />
            : <Badge value="1 drug" className="bg-slate-600/20 text-slate-400 border-slate-600/30" />}
      />
      <div className="mt-1 text-[11px] text-slate-500">
        {g.n_drugs} class member{g.n_drugs !== 1 ? 's' : ''} · {g.total_reports} pooled reports · ATC {g.class_key}
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-3 text-center">
        <Metric label="PRR" value={g.prr?.toFixed(1)} />
        <Metric label="EB05" value={g.eb05?.toFixed(2)} hot={g.eb05 >= 2} />
        <Metric label="IC025" value={g.ic025?.toFixed(2)} hot={g.ic025 > 0} />
        <Metric label="χ²" value={g.chi_square?.toFixed(1)} />
      </div>
      <div className="mt-3">
        <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1">Member drugs</div>
        <div className="flex flex-wrap gap-1.5">
          {g.drugs.map((d) => (
            <span key={d.drug}
                  className="text-xs rounded-md px-2 py-0.5 bg-slate-800 border border-slate-700 text-slate-200 capitalize">
              {d.drug} <span className="text-slate-500">×{d.count}</span>
            </span>
          ))}
        </div>
      </div>
      {g.class_effect && (
        <button type="button" onClick={() => nav('/signals?class_effect=1')}
                className="mt-3 text-xs text-cyan-400 hover:text-cyan-300">
          View class-effect signals →
        </button>
      )}
    </Card>
  );
}

function Metric({ label, value, hot }) {
  return (
    <div className="rounded-lg bg-slate-900/60 border border-slate-800 py-2">
      <div className={`font-mono text-sm ${hot ? 'text-rose-300' : 'text-slate-200'}`}>{value ?? '—'}</div>
      <div className="text-[9px] uppercase tracking-wide text-slate-500">{label}</div>
    </div>
  );
}
