import { useEffect, useState } from 'react';
import { api } from '../api';
import { useRefresh } from '../App';
import { Badge, Card, CardHeader, Spinner } from '../components/ui';

function SignalRows({ rows, empty }) {
  if (!rows?.length) {
    return <div className="text-sm text-slate-500 py-2">{empty}</div>;
  }
  return (
    <div className="space-y-2">
      {rows.map((s) => (
        <div
          key={`${s.drug}|${s.symptom}`}
          className="flex flex-wrap items-center justify-between gap-2 rounded border border-slate-800 bg-slate-950/40 px-3 py-2"
        >
          <div className="text-sm text-slate-200 capitalize">
            {s.drug} <span className="text-slate-500">→</span> {s.symptom}
          </div>
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
            <span>n={s.post_count}</span>
            <span>PRR={s.prr}</span>
            <span>IC025={s.ic025}</span>
            <span>EB05={s.eb05}</span>
            <Badge
              value={s.strength}
              className={
                s.strength === 'STRONG'
                  ? 'bg-rose-500/15 text-rose-300 border-rose-500/30'
                  : 'bg-slate-600/20 text-slate-400 border-slate-600/30'
              }
            />
            {s.sdr_flag && (
              <Badge value="SDR" className="bg-rose-500/15 text-rose-300 border-rose-500/30" />
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

/** Pregnancy / teratogen cohort stratified DMA. */
export default function Pregnancy({ embedded = false }) {
  const { tick } = useRefresh();
  const [data, setData] = useState(null);

  useEffect(() => {
    api.pregnancy().then(setData).catch(() => setData(null));
  }, [tick]);

  if (!data) return <Spinner label="Building pregnancy cohort…" />;

  return (
    <div className="space-y-5">
      {!embedded && (
        <div>
          <h2 className="text-xl font-bold text-slate-100">Pregnancy / teratogen surveillance</h2>
          <p className="text-sm text-slate-400 mt-1">
            Lexicon pregnancy-exposure cohort with stratified disproportionality on congenital
            anomaly outcomes. Registry links remain surrogates.
          </p>
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Card className="p-3">
          <div className="text-[10px] uppercase text-slate-500">Corpus AE posts</div>
          <div className="text-lg text-slate-100">{data.n_posts_total}</div>
        </Card>
        <Card className="p-3">
          <div className="text-[10px] uppercase text-slate-500">Pregnancy cohort</div>
          <div className="text-lg text-amber-200">{data.n_pregnancy_posts}</div>
        </Card>
        <Card className="p-3">
          <div className="text-[10px] uppercase text-slate-500">Cohort reports</div>
          <div className="text-lg text-slate-100">{data.n_reports}</div>
        </Card>
        <Card className="p-3">
          <div className="text-[10px] uppercase text-slate-500">Congenital signals</div>
          <div className="text-lg text-rose-300">{(data.congenital_signals || []).length}</div>
        </Card>
      </div>

      <Card className="p-4 border-rose-700/30">
        <CardHeader
          title="Congenital anomaly stratum"
          subtitle="DMA restricted to pregnancy-cohort posts with congenital / teratogen outcome PTs"
        />
        <div className="mt-3">
          <SignalRows rows={data.congenital_signals} empty="No congenital-anomaly signals in cohort yet." />
        </div>
      </Card>

      <Card className="p-4">
        <CardHeader
          title="Other pregnancy-context signals"
          subtitle="Pregnancy lexicon posts with non-congenital events (maternal ADRs, etc.)"
        />
        <div className="mt-3">
          <SignalRows
            rows={data.other_pregnancy_signals}
            empty="No other pregnancy-context signals."
          />
        </div>
      </Card>

      {data.registries_note && (
        <p className="text-[10px] text-slate-500">{data.registries_note}</p>
      )}
      {data.disclaimer && (
        <p className="text-[10px] text-slate-500 leading-relaxed">{data.disclaimer}</p>
      )}
    </div>
  );
}
