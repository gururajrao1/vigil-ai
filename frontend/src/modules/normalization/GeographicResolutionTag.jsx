/**
 * Site-prioritization badge — shows the standardized city while hover
 * reveals the original verbatim municipal alias (e.g. Madras → Chennai).
 */
export default function GeographicResolutionTag({
  resolution,
  verbatim,
  canonical,
  className = '',
}) {
  const raw = resolution?.verbatim ?? verbatim ?? '';
  const std = resolution?.canonical ?? canonical ?? raw;
  const matched = resolution ? !!resolution.matched : !!(canonical && canonical !== raw);
  const coords =
    resolution?.lat != null && resolution?.lon != null
      ? `${Number(resolution.lat).toFixed(2)}, ${Number(resolution.lon).toFixed(2)}`
      : null;
  const tip = matched && raw && std && raw !== std
    ? `Verbatim alias: «${raw}» → ${std}${coords ? ` (${coords})` : ''}`
    : coords
      ? `${std} (${coords})`
      : std || raw || '—';

  return (
    <span
      title={tip}
      className={
        `inline-flex max-w-full items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs ` +
        (matched
          ? 'border-emerald-500/35 bg-emerald-500/10 text-emerald-200 '
          : 'border-slate-700 bg-slate-900/60 text-slate-300 ') +
        className
      }
    >
      <span className="truncate font-medium">{std || '—'}</span>
      {matched && raw && raw !== std && (
        <span className="truncate text-[10px] text-emerald-200/60">← {raw}</span>
      )}
    </span>
  );
}
