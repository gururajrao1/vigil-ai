import { useEffect, useState } from 'react';
import { api } from '../api';
import { Badge } from '../components/ui';

const CLASS_TONE = {
  III: 'bg-rose-500/15 text-rose-200 border-rose-500/30',
  IIb: 'bg-amber-500/15 text-amber-200 border-amber-500/30',
  II: 'bg-amber-500/15 text-amber-200 border-amber-500/30',
  IIa: 'bg-sky-500/15 text-sky-200 border-sky-500/30',
  I: 'bg-slate-600/25 text-slate-300 border-slate-600/40',
};

/**
 * GMDN / EMDN / risk-class / SaMD taxonomy for a device signal.
 * `compact` renders a single badge row for headers and tables.
 */
export default function DeviceTaxonomyBadge({ term = '', failureMode = '', compact = false }) {
  const [data, setData] = useState(null);

  useEffect(() => {
    if (!term) return undefined;
    let cancelled = false;
    api.ontologyEngineDevice(term, { failureMode })
      .then((d) => { if (!cancelled) setData(d); })
      .catch(() => { if (!cancelled) setData(null); });
    return () => { cancelled = true; };
  }, [term, failureMode]);

  if (!data?.matched) return null;

  const fdaTone = CLASS_TONE[data.fda_class] || CLASS_TONE.I;
  const euTone = CLASS_TONE[data.eu_mdr_class] || CLASS_TONE.I;

  if (compact) {
    return (
      <Badge
        value={`⌬ ${data.gmdn_code || 'GMDN'} · Class ${data.fda_class || '—'}${data.is_samd ? ' · SaMD' : ''}`}
        className={fdaTone}
        title={[data.gmdn_term, data.emdn_term].filter(Boolean).join(' · ')}
      />
    );
  }

  return (
    <div className="rounded-md border border-slate-800 bg-slate-950/50 px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold text-slate-100">{data.canonical_device}</span>
        <Badge value={`FDA Class ${data.fda_class || '—'}`} className={`${fdaTone} text-[10px]`} />
        <Badge value={`EU MDR ${data.eu_mdr_class || '—'}`} className={`${euTone} text-[10px]`} />
        {data.implantable && (
          <Badge value="implantable" className="bg-rose-500/10 text-rose-200 border-rose-500/25 text-[10px]" />
        )}
        {data.is_samd && (
          <Badge value="SaMD (software)" className="bg-cyan-500/15 text-cyan-200 border-cyan-500/30 text-[10px]" />
        )}
      </div>

      <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-1 text-[11px] text-slate-500">
        {data.gmdn_code && (
          <span>GMDN: <span className="font-mono text-slate-300">{data.gmdn_code}</span> {data.gmdn_term}</span>
        )}
        {data.emdn_code && (
          <span>EMDN: <span className="font-mono text-slate-300">{data.emdn_code}</span> {data.emdn_term}</span>
        )}
        {data.fda_product_code && (
          <span>FDA product code: <span className="font-mono text-slate-300">{data.fda_product_code}</span></span>
        )}
        {data.imdrf_code && (
          <span>IMDRF: <span className="font-mono text-slate-300">{data.imdrf_code}</span> {data.imdrf_term}</span>
        )}
      </div>

      <p className="mt-2 text-[11px] text-slate-600">
        GMDN / EMDN codes and risk classes are open surrogates for demonstration — verify
        against the registered device record before any regulatory use.
      </p>
    </div>
  );
}
