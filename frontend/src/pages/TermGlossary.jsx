import { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import { Card, CardHeader, Spinner } from '../components/ui';

/**
 * Term glossary — browseable patient-phrase → MedDRA PT reference.
 *
 * Purpose: transparency for PV scientists. Explains how everyday wording is
 * coded into the Preferred Terms used by KG filters and signal math.
 * Primary UX: dropdown of every known phrase (no typing required).
 */
export default function TermGlossary({ embedded = false }) {
  const [glossary, setGlossary] = useState(null);
  const [selectedPhrase, setSelectedPhrase] = useState('');
  const [selectedPt, setSelectedPt] = useState('');
  const [detail, setDetail] = useState(null);

  useEffect(() => {
    api.termGlossary()
      .then((g) => {
        setGlossary(g);
        const first = g?.phrases?.[0];
        if (first) {
          setSelectedPhrase(first.patient_phrase);
          setDetail(first);
        }
      })
      .catch(() => setGlossary({ terms: [], phrases: [], count: 0, phrase_count: 0 }));
  }, []);

  const ptOptions = useMemo(() => {
    const rows = glossary?.terms || [];
    return rows.map((t) => ({
      value: t.pt,
      label: `${t.pt}  ·  ${(t.patient_phrases || []).length} phrases`,
    }));
  }, [glossary]);

  const activePtBlock = useMemo(() => {
    if (!glossary?.terms?.length) return null;
    if (selectedPt) {
      return glossary.terms.find((t) => t.pt === selectedPt) || null;
    }
    if (detail?.pt) {
      return glossary.terms.find((t) => t.pt === detail.pt) || null;
    }
    return glossary.terms[0] || null;
  }, [glossary, selectedPt, detail]);

  const onPickPhrase = (phrase) => {
    setSelectedPhrase(phrase);
    const row = (glossary?.phrases || []).find((p) => p.patient_phrase === phrase);
    if (row) {
      setDetail(row);
      setSelectedPt(row.pt);
    }
  };

  const onPickPt = (pt) => {
    setSelectedPt(pt);
    const block = (glossary?.terms || []).find((t) => t.pt === pt);
    if (block) {
      const firstPhrase = block.patient_phrases?.[0];
      if (firstPhrase) {
        setSelectedPhrase(firstPhrase);
        const row = (glossary?.phrases || []).find((p) => p.patient_phrase === firstPhrase);
        setDetail(row || {
          patient_phrase: firstPhrase,
          pt: block.pt,
          soc: block.soc,
          soc_code: block.soc_code,
        });
      }
    }
  };

  if (!glossary) return <Spinner label="Loading term glossary…" />;

  const phrases = glossary.phrases || [];

  return (
    <div className="space-y-4">
      <Card className="p-4 border-[var(--app-border-accent)] bg-[var(--app-accent-muted)]/40">
        <div className="text-[10px] uppercase tracking-[0.14em] text-[var(--app-accent)] mb-1">
          What this feature is for
        </div>
        <p className="text-sm text-[var(--app-text-secondary)] leading-relaxed">
          {glossary.purpose || (
            <>
              A coding reference for safety scientists — not a search box you must type into.
              Pick any patient phrase from the list to see the MedDRA-style Preferred Term
              used in filters, the knowledge graph, and disproportionality.
            </>
          )}
        </p>
        <p className="text-[11px] text-[var(--app-text-faint)] mt-2 italic">
          {glossary.disclaimer}
        </p>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card className="p-4">
          <CardHeader
            title="Patient phrase"
            subtitle={`${glossary.phrase_count || phrases.length} coded phrases — pick from the list`}
          />
          <select
            value={selectedPhrase}
            onChange={(e) => onPickPhrase(e.target.value)}
            className="mt-3 w-full rounded-lg border border-[var(--app-border)] bg-[var(--app-surface-solid)] px-3 py-2.5 text-sm text-[var(--app-text)]"
            size={Math.min(14, Math.max(8, Math.min(phrases.length, 14)))}
          >
            {phrases.map((p) => (
              <option key={`${p.patient_phrase}|${p.pt}`} value={p.patient_phrase}>
                {p.patient_phrase}  →  {p.pt}
              </option>
            ))}
          </select>
        </Card>

        <Card className="p-4">
          <CardHeader
            title="Preferred Term (clinical code)"
            subtitle={`${glossary.count || 0} MedDRA-style PTs`}
          />
          <select
            value={selectedPt || activePtBlock?.pt || ''}
            onChange={(e) => onPickPt(e.target.value)}
            className="mt-3 w-full rounded-lg border border-[var(--app-border)] bg-[var(--app-surface-solid)] px-3 py-2.5 text-sm text-[var(--app-text)]"
          >
            {ptOptions.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>

          {(detail || activePtBlock) && (
            <div className="mt-4 rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3">
              <div className="text-xs text-[var(--app-text-muted)]">Maps to</div>
              <div className="text-lg font-semibold text-[var(--app-text)] mt-0.5">
                {detail?.pt || activePtBlock?.pt}
              </div>
              <div className="text-xs text-violet-300 mt-1">
                {(detail?.soc || activePtBlock?.soc) || '—'}
                {(detail?.soc_code || activePtBlock?.soc_code)
                  ? ` (${detail?.soc_code || activePtBlock?.soc_code})`
                  : ''}
              </div>
              {detail?.patient_phrase && (
                <div className="text-xs text-[var(--app-text-secondary)] mt-2">
                  Selected phrase: <span className="text-[var(--app-text)]">“{detail.patient_phrase}”</span>
                </div>
              )}
            </div>
          )}
        </Card>
      </div>

      {activePtBlock && (
        <Card className="p-4">
          <CardHeader
            title={`All patient phrases → ${activePtBlock.pt}`}
            subtitle="Everything in the coding dictionary for this Preferred Term"
          />
          <div className="mt-3 flex flex-wrap gap-2">
            {(activePtBlock.patient_phrases || []).map((phrase) => (
              <button
                key={phrase}
                type="button"
                onClick={() => onPickPhrase(phrase)}
                className={`rounded-md border px-2.5 py-1 text-xs transition ${
                  phrase === selectedPhrase
                    ? 'border-sky-500/50 bg-sky-500/15 text-sky-200'
                    : 'border-[var(--app-border)] bg-[var(--app-surface)] text-[var(--app-text-muted)] hover:text-[var(--app-text)]'
                }`}
              >
                {phrase}
              </button>
            ))}
          </div>
        </Card>
      )}

      <Card className="p-4">
        <CardHeader
          title="Full coding table"
          subtitle="Scroll the complete list — same data as the dropdowns"
        />
        <div className="mt-3 max-h-[22rem] overflow-auto rounded-lg border border-[var(--app-border)]">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-[var(--app-surface-solid)] text-[var(--app-text-muted)]">
              <tr>
                <th className="px-3 py-2 font-medium">Patient phrase</th>
                <th className="px-3 py-2 font-medium">Preferred Term</th>
                <th className="px-3 py-2 font-medium">SOC</th>
              </tr>
            </thead>
            <tbody>
              {phrases.map((p) => (
                <tr
                  key={`${p.patient_phrase}|${p.pt}|row`}
                  className={`border-t border-[var(--app-border)] cursor-pointer hover:bg-[var(--app-surface-hover)] ${
                    p.patient_phrase === selectedPhrase ? 'bg-sky-500/10' : ''
                  }`}
                  onClick={() => onPickPhrase(p.patient_phrase)}
                >
                  <td className="px-3 py-1.5 text-[var(--app-text-secondary)]">{p.patient_phrase}</td>
                  <td className="px-3 py-1.5 text-[var(--app-text)] font-medium">{p.pt}</td>
                  <td className="px-3 py-1.5 text-[var(--app-text-faint)]">{p.soc}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
