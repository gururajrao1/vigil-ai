import { Badge, Button, Card, CardHeader } from '../../components/ui';

const num = (v, d = 2) => (v == null ? '—' : Number(v).toFixed(d));

/**
 * Universe (generic chemical) vs Subset (manufacturer brand) filter + results.
 */
export default function UniverseVersusSubsetFilter({
  resolution,
  report,
  selected,
  onChangeSelected,
  onRerun,
}) {
  const brands = resolution?.subset_brands || [];
  const ingredients = (resolution?.ingredients || []).map((i) => i.generic);

  const toggle = (brand) => {
    const set = new Set(selected);
    if (set.has(brand)) set.delete(brand);
    else set.add(brand);
    onChangeSelected?.([...set]);
  };

  return (
    <Card className="p-4">
      <CardHeader
        title="Universe vs Subset"
        subtitle="Universe = chemical ingredient baseline. Subset = selected manufacturer brands for head-to-head disproportion."
        right={
          report?.totals && (
            <Badge
              value={`${report.totals.universe_reports || 0} universe · ${report.totals.subset_reports || 0} subset`}
              className="bg-sky-500/15 text-sky-200 border-sky-500/30 text-[10px]"
            />
          )
        }
      />

      <div className="mt-3 space-y-3">
        <div>
          <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1">Universe (ingredients)</div>
          <div className="flex flex-wrap gap-1.5">
            {ingredients.length ? ingredients.map((g) => (
              <Badge key={g} value={g} className="bg-emerald-500/15 text-emerald-200 border-emerald-500/30 text-[10px]" />
            )) : <span className="text-xs text-slate-500">Resolve a brand first</span>}
          </div>
        </div>

        <div>
          <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1">Subset brands</div>
          <div className="flex flex-wrap gap-2">
            {brands.length === 0 && (
              <span className="text-xs text-slate-500">No related brands in the RxE surrogate for this chemical.</span>
            )}
            {brands.map((b) => (
              <label key={b} className="inline-flex items-center gap-1.5 rounded border border-slate-800 bg-slate-950/50 px-2 py-1 text-xs text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={selected.includes(b)}
                  onChange={() => toggle(b)}
                />
                {b}
              </label>
            ))}
          </div>
          {brands.length > 0 && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="mt-2"
              onClick={() => onRerun?.(selected)}
            >
              Recompute Universe vs Subset →
            </Button>
          )}
        </div>

        {report?.verdict && (
          <p className="text-sm text-slate-200">{report.verdict}</p>
        )}

        {(report?.comparative || []).length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-slate-500 text-left">
                <tr>
                  <th className="py-1.5 pr-3">Event</th>
                  <th className="py-1.5 pr-3">Subset</th>
                  <th className="py-1.5 pr-3 text-right">Subset PRR</th>
                  <th className="py-1.5 pr-3 text-right">Universe PRR</th>
                  <th className="py-1.5 pr-3 text-right">Elevation</th>
                </tr>
              </thead>
              <tbody>
                {report.comparative.slice(0, 12).map((row) => (
                  <tr key={`${row.event}|${row.subset_product}`} className="border-t border-slate-800/70">
                    <td className="py-1.5 pr-3 text-slate-200">{row.event}</td>
                    <td className="py-1.5 pr-3 text-slate-300">{row.subset_product}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{num(row.subset_prr)}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{num(row.universe_prr)}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums text-amber-200">{num(row.prr_elevation)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {report?.how_to_read && (
          <p className="text-[11px] text-slate-500">{report.how_to_read}</p>
        )}
      </div>
    </Card>
  );
}
