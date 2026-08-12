import { Badge } from '../../components/ui';

/**
 * Debug UI — traces verbatim consumer text through SapBERT embedding,
 * cosine / FAISS scoring, and final MedDRA Preferred Term resolution.
 */
export default function ConceptMappingTrace({ trace }) {
  if (!trace) return null;
  const clinical = trace.clinical || {};
  const emb = clinical.embedding || {};
  const steps = trace.pipeline_steps || [];
  const topK = clinical.top_k || [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge
          value={clinical.matched ? 'linked' : 'unmatched'}
          className={clinical.matched
            ? 'bg-emerald-500/15 text-emerald-200 border-emerald-500/30 text-[10px]'
            : 'bg-slate-600/25 text-slate-300 border-slate-600/40 text-[10px]'}
        />
        {clinical.match_method && (
          <Badge value={clinical.match_method} className="bg-slate-700/40 text-slate-300 border-slate-600/40 text-[10px]" />
        )}
        {emb.encoder_backend && (
          <Badge value={emb.encoder_backend} className="bg-cyan-500/10 text-cyan-200 border-cyan-500/30 text-[10px]" />
        )}
        {trace.audit?.faiss_enabled && (
          <Badge value="FAISS" className="bg-violet-500/15 text-violet-200 border-violet-500/30 text-[10px]" />
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-3 text-sm">
        <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
          <div className="text-[10px] uppercase tracking-wide text-slate-500">Verbatim</div>
          <div className="mt-1 text-slate-100">«{clinical.verbatim || '—'}»</div>
        </div>
        <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
          <div className="text-[10px] uppercase tracking-wide text-slate-500">UMLS CUI</div>
          <div className="mt-1 font-mono text-cyan-200">{clinical.cui || '—'}</div>
          <div className="mt-1 text-xs text-slate-400">{clinical.preferred || ''}</div>
        </div>
        <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
          <div className="text-[10px] uppercase tracking-wide text-slate-500">MedDRA PT · SNOMED</div>
          <div className="mt-1 text-emerald-200">{clinical.meddra_pt || '—'}</div>
          <div className="mt-1 font-mono text-[11px] text-slate-400">{clinical.snomed_ct || '—'}</div>
        </div>
      </div>

      {emb.vector_preview?.length > 0 && (
        <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <div className="text-[10px] uppercase tracking-wide text-slate-500">
              Dense vector preview ({emb.vector_dim}-d · L2={emb.l2_norm ?? '—'})
            </div>
            <div className="font-mono text-[11px] text-slate-400">
              cosine={clinical.cosine ?? '—'}
            </div>
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5 font-mono text-[10px] text-slate-400">
            {emb.vector_preview.map((v, i) => (
              <span key={i} className="rounded bg-slate-900 px-1.5 py-0.5 border border-slate-800">
                {Number(v).toFixed(3)}
              </span>
            ))}
            <span className="text-slate-600">…</span>
          </div>
        </div>
      )}

      {steps.length > 0 && (
        <ol className="space-y-2">
          {steps.map((s) => (
            <li key={s.step} className="flex gap-3 text-sm">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-800 text-[11px] text-slate-300">
                {s.step}
              </span>
              <div>
                <div className="font-medium text-slate-200">{s.name}</div>
                <div className="text-xs text-slate-400">{s.detail}</div>
              </div>
            </li>
          ))}
        </ol>
      )}

      {topK.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-slate-500">
              <tr className="text-left">
                <th className="py-1.5 pr-3">#</th>
                <th className="py-1.5 pr-3">Surface</th>
                <th className="py-1.5 pr-3">CUI</th>
                <th className="py-1.5 pr-3">MedDRA PT</th>
                <th className="py-1.5 pr-3 text-right">Cosine</th>
              </tr>
            </thead>
            <tbody>
              {topK.map((h) => (
                <tr key={`${h.rank}-${h.cui}`} className="border-t border-slate-800/70">
                  <td className="py-1.5 pr-3 text-slate-500">{h.rank}</td>
                  <td className="py-1.5 pr-3 text-slate-300">{h.matched_surface}</td>
                  <td className="py-1.5 pr-3 font-mono text-cyan-300/90">{h.cui}</td>
                  <td className="py-1.5 pr-3 text-slate-200">{h.meddra_pt}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums text-slate-300">{Number(h.cosine).toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
