import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useRefresh } from '../App';
import { Badge, Card, CardHeader, Spinner } from '../components/ui';
import GeographicResolutionTag from '../modules/normalization/GeographicResolutionTag';

// Spatial (geographic) cluster detection — a Kulldorff-style Poisson scan statistic.
// City aliases (MCN) are for SEARCH expansion, not for renaming country hotspots.
export default function Spatial({ embedded = false }) {
  const { tick } = useRefresh();
  const nav = useNavigate();
  const [data, setData] = useState(null);
  const [aliasDemo, setAliasDemo] = useState(null);

  useEffect(() => { api.spatial().then(setData).catch(() => setData({ clusters: [] })); }, [tick]);

  useEffect(() => {
    // Teach the Pattabhi geo pattern without pretending country names are cities.
    api.normalizationExpand('Chennai')
      .then(setAliasDemo)
      .catch(() => setAliasDemo(null));
  }, []);

  if (!data) return <Spinner label="Scanning geography…" />;
  const clusters = data.clusters || [];
  const geoMatch = aliasDemo?.geo?.matches?.[0];

  return (
    <div className="space-y-5">
{!embedded && (
      <div>
        <h2 className="text-xl font-bold text-slate-100">Geographic clusters · spatial scan</h2>
        <p className="text-sm text-slate-400 mt-1">
          A <strong>Kulldorff-style Poisson scan statistic</strong> tests whether a signal's
          reports concentrate in a particular <strong>country or region</strong> beyond the share
          expected from the corpus-wide geographic distribution of all reports.
          <span className="text-slate-600"> Geolocation is post-level and coarse.</span>
        </p>
      </div>

)}
      <Card className="p-4 border-cyan-700/30">
        <CardHeader
          title="City aliases ≠ country clusters"
          subtitle="MCN geo is for Omni-Search / Detect retrieval (Chennai≡Madras). Spatial scan below uses country/region columns."
        />
        <div className="mt-3 flex flex-wrap items-center gap-3">
          {geoMatch ? (
            <GeographicResolutionTag resolution={geoMatch.resolution} />
          ) : (
            <span className="text-sm text-slate-400">Chennai ↔ Madras</span>
          )}
          <span className="text-xs text-slate-400 max-w-xl">
            {geoMatch?.why
              || 'Searching Chennai expands to Madras so historical-name narratives are not missed.'}
          </span>
          <Link to="/signals" className="text-xs text-cyan-400 hover:text-cyan-300">
            Try in Omni-Search (Detect) →
          </Link>
          <Link to="/terminology?tab=mcn" className="text-xs text-cyan-400 hover:text-cyan-300">
            MCN playground →
          </Link>
        </div>
        {geoMatch?.aliases?.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {geoMatch.aliases.map((a) => (
              <Badge key={a} value={a} className="bg-emerald-500/10 text-emerald-200 border-emerald-500/30 text-[10px]" />
            ))}
          </div>
        )}
      </Card>

      {clusters.length === 0 && (
        <Card className="p-8 text-center text-slate-500">
          No geographic clusters detected. Load the demo corpus.
        </Card>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {clusters.map((c) => {
          const areas = (c.by_area || []).filter((a) => a.observed > 0)
            .sort((a, b) => (b.rr || 0) - (a.rr || 0)).slice(0, 6);
          const maxRr = Math.max(1, ...areas.map((a) => a.rr || 0));
          return (
            <Card key={`${c.drug}:${c.event}`} className="p-4 border-emerald-600/30">
              <CardHeader
                title={<span className="flex items-center gap-2 capitalize">📍 {c.drug} <span className="text-slate-600">→</span> {c.event}</span>}
                subtitle={<span>Hotspot: <strong className="text-emerald-300">{c.hotspot}</strong> · {c.level}-level concentration</span>}
                right={<Badge value={`RR ${c.rr?.toFixed(1)}×`} className="bg-emerald-500/15 text-emerald-300 border-emerald-500/30" />}
              />
              <div className="mt-1 text-[11px] text-slate-500">
                {c.total_observed} total reports · {c.observed} in {c.hotspot} vs {c.expected?.toFixed(1)} expected
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-3 text-center">
                <Metric label="Observed" value={c.observed} hot />
                <Metric label="Expected" value={c.expected?.toFixed(1)} />
                <Metric label="RR" value={`${c.rr?.toFixed(1)}×`} hot={c.rr >= 2} />
                <Metric label="LLR" value={c.llr?.toFixed(1)} hot={c.llr >= 3.84} />
              </div>
              <div className="mt-3">
                <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1.5">
                  Per-area relative risk ({c.level})
                </div>
                <div className="space-y-1.5">
                  {areas.map((a) => (
                    <div key={a.area} className="flex items-center gap-2 text-xs">
                      <span className={`w-28 truncate ${a.area === c.hotspot ? 'text-emerald-300 font-medium' : 'text-slate-300'}`}
                            title={a.area}>{a.area}</span>
                      <div className="flex-1 h-3 rounded bg-slate-800 overflow-hidden">
                        <div className={`h-full ${a.area === c.hotspot ? 'bg-emerald-500/70' : 'bg-slate-600/70'}`}
                             style={{ width: `${Math.max(4, ((a.rr || 0) / maxRr) * 100)}%` }} />
                      </div>
                      <span className="w-20 text-right font-mono text-slate-400">
                        {a.observed} · {a.rr?.toFixed(1)}×
                      </span>
                    </div>
                  ))}
                </div>
              </div>
              <button onClick={() => nav('/signals?spatial=1')}
                      className="mt-3 text-xs text-emerald-400 hover:text-emerald-300">
                View geo-cluster signals →
              </button>
            </Card>
          );
        })}
      </div>

      {clusters.length > 0 && (
        <p className="text-[11px] text-slate-600">
          Caveat: geolocation is inferred at the post level and is coarse (country / region);
          clusters are hypotheses for follow-up, not confirmed batch defects. Expected counts derive
          from the corpus-wide geographic distribution of all adverse-event reports.
        </p>
      )}
    </div>
  );
}

function Metric({ label, value, hot }) {
  return (
    <div className="rounded-lg bg-slate-900/60 border border-slate-800 py-2">
      <div className={`font-mono text-sm ${hot ? 'text-emerald-300' : 'text-slate-200'}`}>{value ?? '—'}</div>
      <div className="text-[9px] uppercase tracking-wide text-slate-500">{label}</div>
    </div>
  );
}
