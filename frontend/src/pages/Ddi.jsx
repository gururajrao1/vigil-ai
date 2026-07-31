import { useEffect, useState } from 'react';
import { api } from '../api';
import { useRefresh } from '../App';
import { Badge, Card, CardHeader, Spinner } from '../components/ui';

/** Drug–drug interaction co-mention mining (Ω + plausibility gate). */
export default function Ddi({ embedded = false }) {
  const { tick } = useRefresh();
  const [data, setData] = useState(null);
  const [plausibleOnly, setPlausibleOnly] = useState(false);

  useEffect(() => {
    api.ddi({ plausible_only: plausibleOnly, min_count: 2 })
      .then(setData)
      .catch(() => setData({ pairs: [], n_posts: 0 }));
  }, [tick, plausibleOnly]);

  if (!data) return <Spinner label="Mining DDI co-mentions…" />;
  const pairs = data.pairs || [];

  return (
    <div className="space-y-5">
      {!embedded && (
        <div>
          <h2 className="text-xl font-bold text-slate-100">Drug–drug interaction signals</h2>
          <p className="text-sm text-slate-400 mt-1">
            Co-mention disproportionality (Ω) on multi-product AE posts, gated by mechanistic
            plausibility / curated DDI patterns. Hypothesis generator only.
          </p>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span className="text-slate-400">
          {data.n_multi_drug ?? 0} multi-drug posts · {pairs.length} pair–event rows
        </span>
        <label className="flex items-center gap-2 text-slate-300 cursor-pointer">
          <input
            type="checkbox"
            checked={plausibleOnly}
            onChange={(e) => setPlausibleOnly(e.target.checked)}
          />
          Plausible only
        </label>
      </div>

      {pairs.length === 0 ? (
        <Card className="p-4 text-sm text-slate-400">
          No co-mention DDI candidates yet. Ingest FAERS bulk (polypharmacy) or multi-drug social posts, then recompute.
        </Card>
      ) : (
        <div className="space-y-2">
          {pairs.map((p) => (
            <Card key={`${p.drug_a}|${p.drug_b}|${p.event}`} className="p-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <div className="text-sm text-slate-100 font-medium capitalize">
                    {p.drug_a} + {p.drug_b}
                    <span className="text-slate-500 font-normal"> → </span>
                    {p.event}
                  </div>
                  <div className="mt-1 text-[11px] text-slate-500">
                    n={p.count} · E≈{p.expected} · Ω={p.omega} (Ω025={p.omega025})
                    {p.interaction_ror != null ? ` · interaction-ROR≈${p.interaction_ror}` : ''}
                  </div>
                  {p.plausibility?.known_pattern && (
                    <div className="mt-1 text-[11px] text-amber-300/90">
                      {p.plausibility.known_pattern.note}
                    </div>
                  )}
                </div>
                <div className="flex flex-wrap gap-1.5">
                  <Badge
                    value={p.strength}
                    className={
                      p.strength === 'STRONG'
                        ? 'bg-rose-500/15 text-rose-300 border-rose-500/30'
                        : p.strength === 'MODERATE'
                          ? 'bg-amber-500/15 text-amber-300 border-amber-500/30'
                          : 'bg-slate-600/20 text-slate-400 border-slate-600/30'
                    }
                  />
                  {p.sdr_flag && (
                    <Badge value="Ω SDR" className="bg-rose-500/15 text-rose-300 border-rose-500/30" />
                  )}
                  <Badge
                    value={p.plausibility?.plausible ? 'plausible' : 'review'}
                    className={
                      p.plausibility?.plausible
                        ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
                        : 'bg-slate-600/20 text-slate-400 border-slate-600/30'
                    }
                  />
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {data.disclaimer && (
        <p className="text-[10px] text-slate-500 leading-relaxed">{data.disclaimer}</p>
      )}
    </div>
  );
}
