import { Badge } from '../components/ui';

/**
 * High-contrast PGx actionable badge for Signal Detail / Detect tables.
 * Accepts either legacy `pgx` object or engine `profile` payload.
 */
export default function PGxBiomarkerBadge({ pgx, profile, compact = false }) {
  const hit = profile?.pgx || pgx;
  const actionable = Boolean(profile?.is_pgx_actionable || pgx || hit);
  if (!actionable && !hit) return null;

  const gene = hit?.gene || profile?.associations?.[0]?.gene;
  const allele = hit?.allele || profile?.associations?.[0]?.allele;
  const phenotype = hit?.phenotype || profile?.associations?.[0]?.phenotype;
  const level = hit?.level || profile?.associations?.[0]?.level || 'PharmGKB Level-A';
  const badge = profile?.level_badge || hit?.level_badge || `PGx ACTIONABLE: ${level}`;

  if (compact) {
    return (
      <Badge
        value={`🧬 ${badge}`}
        className="bg-emerald-500/15 text-emerald-200 border-emerald-500/40"
        title={[gene, allele, phenotype].filter(Boolean).join(' · ')}
      />
    );
  }

  return (
    <div className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <Badge value={badge} className="bg-emerald-600/30 text-emerald-100 border-emerald-400/50 text-[10px]" />
        {gene && <span className="text-sm font-semibold text-emerald-100">{gene}</span>}
        {allele && <span className="text-xs font-mono text-emerald-200/90">{allele}</span>}
      </div>
      {phenotype && (
        <p className="mt-1 text-xs text-emerald-100/90">
          [PGx WARNING: {gene} {phenotype}]
        </p>
      )}
      {(hit?.recommendation || profile?.associations?.[0]?.recommendation) && (
        <p className="mt-1 text-[11px] text-slate-300 leading-relaxed">
          {hit?.recommendation || profile?.associations?.[0]?.recommendation}
        </p>
      )}
    </div>
  );
}
