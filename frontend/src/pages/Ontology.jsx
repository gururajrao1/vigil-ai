import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useRefresh } from '../App';
import { Badge, Button, Card, CardHeader, Spinner } from '../components/ui';
import OntologyHierarchyTree from '../hubs/OntologyHierarchyTree';
import ChemicalStructureCard from '../hubs/ChemicalStructureCard';
import DeviceTaxonomyBadge from '../hubs/DeviceTaxonomyBadge';

const num = (v, d = 2) => (v === null || v === undefined ? '—' : Number(v).toFixed(d));

function SocTable({ rows, onOpen }) {
  if (!rows.length) return null;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="text-slate-500">
          <tr className="text-left">
            <th className="py-1.5 pr-3">Product</th>
            <th className="py-1.5 pr-3">System Organ Class</th>
            <th className="py-1.5 pr-3 text-right">Reports</th>
            <th className="py-1.5 pr-3 text-right">PTs</th>
            <th className="py-1.5 pr-3 text-right">PRR</th>
            <th className="py-1.5 pr-3 text-right">EB05</th>
            <th className="py-1.5 pr-3 text-right">IC025</th>
            <th className="py-1.5 pr-3">Tier</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={`${r.product}|${r.soc}`}
              className="border-t border-slate-800/70 cursor-pointer hover:bg-slate-900/50"
              onClick={() => onOpen?.(r)}
            >
              <td className="py-1.5 pr-3 text-slate-200">{r.product}</td>
              <td className="py-1.5 pr-3 text-slate-300" title={(r.members || []).map((m) => m.pt).join(', ')}>{r.soc}</td>
              <td className="py-1.5 pr-3 text-right tabular-nums text-slate-300">{r.observed_reports}</td>
              <td className="py-1.5 pr-3 text-right tabular-nums text-slate-400">{r.n_member_pts}</td>
              <td className="py-1.5 pr-3 text-right tabular-nums text-slate-300">{num(r.prr)}</td>
              <td className="py-1.5 pr-3 text-right tabular-nums text-slate-300">{num(r.eb05)}</td>
              <td className="py-1.5 pr-3 text-right tabular-nums text-slate-300">{num(r.ic025)}</td>
              <td className="py-1.5 pr-3">
                <Badge
                  value={r.strength}
                  className={r.strength === 'STRONG'
                    ? 'bg-rose-500/15 text-rose-200 border-rose-500/30 text-[10px]'
                    : r.strength === 'MODERATE'
                      ? 'bg-amber-500/15 text-amber-200 border-amber-500/30 text-[10px]'
                      : 'bg-slate-600/25 text-slate-300 border-slate-600/40 text-[10px]'}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Ontology lens — organ-class disproportionality plus a terminology playground. */
export default function Ontology({ embedded = false }) {
  const { tick } = useRefresh();
  const nav = useNavigate();
  const [data, setData] = useState(null);
  const [status, setStatus] = useState(null);
  const [err, setErr] = useState(null);
  const [draft, setDraft] = useState('racing heart');
  const [term, setTerm] = useState('racing heart');

  useEffect(() => {
    let cancelled = false;
    setErr(null);
    api.ontologyEngineDisproportionality({ topN: 24 })
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => {
        if (cancelled) return;
        const msg = e.message || String(e);
        setErr(/404|Not Found/i.test(msg)
          ? 'Ontology engine API not on this backend yet — deploy the latest API, then refresh.'
          : msg);
      });
    api.ontologyEngineStatus()
      .then((s) => { if (!cancelled) setStatus(s); })
      .catch(() => { if (!cancelled) setStatus(null); });
    return () => { cancelled = true; };
  }, [tick]);

  const alerts = data?.soc_alerts || [];

  return (
    <div className="space-y-5">
      {!embedded && (
        <div>
          <h2 className="text-xl font-bold text-slate-100">Ontology</h2>
          <p className="text-sm text-slate-400 mt-1">
            Hauben 2007 / Trontell “prepared mind”: related PTs in one System Organ Class can strengthen a
            weak single-term signal. Click a SOC row to open that product in Detect.
          </p>
        </div>
      )}

      {err && <p className="text-sm text-rose-300">{err}</p>}

      <Card className="p-4">
        <CardHeader
          title="Organ-class (SOC) disproportionality"
          subtitle="Member Preferred Terms pooled into their System Organ Class before the 2×2 — catches diffuse class signals no single PT would raise."
          right={status && (
            <Badge
              value={`dictionaries v${status.ontology_version}`}
              className="bg-slate-700/40 text-slate-300 border-slate-600/40 text-[10px]"
            />
          )}
        />
        {!data && !err && <div className="mt-3"><Spinner label="Rolling up organ classes…" /></div>}
        {data && (
          <div className="mt-3 space-y-4">
            <p className="text-sm text-slate-200">{data.verdict}</p>

            {alerts.length > 0 && (
              <div className="space-y-2">
                {alerts.map((a) => (
                  <div key={`${a.product}|${a.soc}`} className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge value="SOC ALERT" className="bg-amber-600/30 text-amber-100 border-amber-400/50 text-[10px]" />
                      <span className="text-sm font-semibold text-amber-100">{a.product} · {a.soc}</span>
                      <span className="text-[11px] text-amber-200/80">
                        PRR {num(a.prr)} · EB05 {num(a.eb05)} · IC025 {num(a.ic025)}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-amber-100/90">{a.reason}</p>
                    <p className="mt-1 text-[11px] text-slate-300">{a.recommended_action}</p>
                    <p className="mt-1 text-[11px] text-slate-500">
                      Member PTs: {(a.member_pts || []).join(', ') || '—'}
                    </p>
                    <Link
                      to={`/signals?drug=${encodeURIComponent(a.product || '')}&soc=${encodeURIComponent(a.soc || '')}`}
                      className="mt-1 inline-block text-[11px] text-cyan-400 hover:text-cyan-300"
                    >
                      Review member PTs in Detect →
                    </Link>
                  </div>
                ))}
              </div>
            )}

            <SocTable
              rows={data.soc_table || []}
              onOpen={(r) => {
                const qs = new URLSearchParams();
                if (r.product) qs.set('drug', r.product);
                if (r.soc) qs.set('soc', r.soc);
                nav(`/signals?${qs.toString()}`);
              }}
            />

            <div className="flex flex-wrap gap-3 pt-2 border-t border-slate-800 text-[11px] text-slate-500">
              <span>{data.totals?.signals ?? 0} signals</span>
              <span>{data.totals?.pt_pairs ?? 0} PT pairs</span>
              <span>{data.totals?.soc_pairs ?? 0} SOC pairs</span>
              <span>{data.totals?.reports ?? 0} reports</span>
              <span>{data.totals?.unmatched_pts ?? 0} verbatims outside the surrogate</span>
            </div>
            <p className="text-[11px] text-slate-500">{data.how_to_read}</p>
            <p className="text-[11px] text-slate-600">{data.disclaimer}</p>
          </div>
        )}
      </Card>

      <Card className="p-4">
        <CardHeader
          title="Terminology playground"
          subtitle="Type patient wording, a brand, or a device — this is the same mapper the 4-gate AE detector and Omni-Search use (racing heart → Palpitations PT/SOC)."
        />
        <form
          className="mt-3 flex flex-wrap gap-2"
          onSubmit={(e) => { e.preventDefault(); setTerm(draft.trim()); }}
        >
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="racing heart · Ozempic · pacemaker · closed loop algorithm"
            className="flex-1 min-w-[220px] rounded-md border border-slate-800 bg-slate-950/60 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600"
          />
          <Button type="submit" variant="primary">Map term</Button>
        </form>

        {term && (
          <div className="mt-4 space-y-4">
            <DeviceTaxonomyBadge term={term} />
            <ChemicalStructureCard term={term} embedded />
            <OntologyHierarchyTree term={term} embedded />
          </div>
        )}
      </Card>

      {status && (
        <p className="text-[11px] text-slate-600">
          Loaded dictionaries: {(status.loaded_files || []).join(', ')} ·{' '}
          {status.counts?.meddra_chains ?? 0} MedDRA chains ·{' '}
          {status.counts?.chebi_ingredients ?? 0} chemical entries ·{' '}
          {status.counts?.devices ?? 0} device categories. {status.disclaimer}
        </p>
      )}
    </div>
  );
}
