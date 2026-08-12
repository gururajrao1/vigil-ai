import { Badge, Card, CardHeader } from '../../components/ui';

/**
 * Visual ATC ladder for resolved ingredients (RxClass / WHO ATC).
 */
export default function ATCClassExplorer({ resolution }) {
  const detail = resolution?.atc_detail || [];
  if (!resolution?.matched) return null;

  return (
    <Card className="p-4 border-teal-800/40">
      <CardHeader
        title="ATC class explorer"
        subtitle="WHO Anatomical Therapeutic Chemical ladder for the resolved ingredient(s)"
        right={
          <Badge value="RxClass / ATC" className="bg-teal-500/15 text-teal-200 border-teal-500/30 text-[10px]" />
        }
      />
      <div className="mt-3 space-y-4">
        {detail.map((row) => (
          <div key={row.generic} className="rounded-md border border-slate-800 bg-slate-950/40 px-3 py-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-semibold text-slate-100">{row.generic}</span>
              {row.atc_code && (
                <span className="font-mono text-[11px] text-teal-200">{row.atc_code}</span>
              )}
              {row.rxcui && (
                <span className="font-mono text-[10px] text-slate-500">{row.rxcui}</span>
              )}
            </div>
            <div className="mt-2 space-y-1">
              {(row.atc_levels || []).map((lvl) => (
                <div key={lvl.code} className="flex items-center gap-2 text-xs" style={{ paddingLeft: `${(lvl.level - 1) * 12}px` }}>
                  <span className="w-8 text-[10px] uppercase text-slate-500">L{lvl.level}</span>
                  <span className="w-16 font-mono text-slate-300">{lvl.code}</span>
                  <span className="text-slate-300">{lvl.label}</span>
                </div>
              ))}
              {!row.atc_levels?.length && (
                <p className="text-xs text-slate-500">No ATC code in the offline table for this ingredient.</p>
              )}
            </div>
            {(row.class_members || []).length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                <span className="text-[10px] text-slate-500 w-full">Same ATC subgroup (read-across)</span>
                {row.class_members.slice(0, 10).map((m) => (
                  <Badge key={m} value={m} className="bg-slate-700/40 text-slate-300 border-slate-600/40 text-[10px]" />
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}
