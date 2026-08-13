import { useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import { Badge, Button, Spinner } from '../../components/ui';

/**
 * Unified Omni-Search bar — brand / generic / device / noisy patient wording.
 * Dropdown autocomplete is powered by the MicroMeSH fuzzy BEL resolver.
 */
export default function OmniSearchGateway({
  onResolved,
  initialQuery = '',
  busy = false,
}) {
  const [q, setQ] = useState(initialQuery);
  const [suggestions, setSuggestions] = useState([]);
  const [open, setOpen] = useState(false);
  const [hint, setHint] = useState('');
  const boxRef = useRef(null);
  const timer = useRef(null);

  useEffect(() => {
    const onDoc = (e) => {
      if (!boxRef.current?.contains(e.target)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  const fetchSuggestions = (value) => {
    clearTimeout(timer.current);
    if (!value || value.trim().length < 2) {
      setSuggestions([]);
      return;
    }
    timer.current = setTimeout(() => {
      api.searchAutocomplete(value.trim())
        .then((r) => {
          setSuggestions(r.suggestions || []);
          setOpen(true);
        })
        .catch(() => setSuggestions([]));
    }, 180);
  };

  const submit = (value = q) => {
    const term = (value || '').trim();
    if (!term) return;
    setOpen(false);
    setHint('');
    onResolved?.(term);
  };

  return (
    <div ref={boxRef} className="relative">
      <form
        className="flex flex-wrap gap-2"
        onSubmit={(e) => { e.preventDefault(); submit(); }}
      >
        <div className="relative flex-1 min-w-[240px]">
          <input
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              fetchSuggestions(e.target.value);
            }}
            onFocus={() => suggestions.length && setOpen(true)}
            placeholder="Janumet · ozmpic · Coumadin · sick to my stomach…"
            className="w-full rounded-md border border-slate-800 bg-slate-950/60 px-3 py-2.5 text-sm text-slate-100 placeholder:text-slate-600"
            autoComplete="off"
          />
          {open && suggestions.length > 0 && (
            <ul className="absolute z-20 mt-1 max-h-56 w-full overflow-auto rounded-md border border-slate-700 bg-slate-950 shadow-xl">
              {suggestions.map((s) => (
                <li key={`${s.term}-${s.score}`}>
                  <Button
                    type="button"
                    variant="ghost"
                    className="w-full justify-between text-left h-auto py-2 px-3"
                    onClick={() => {
                      setQ(s.term);
                      submit(s.term);
                    }}
                  >
                    <span>{s.term}</span>
                    <span className="font-mono text-[10px] opacity-60">{s.score}</span>
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <Button type="submit" variant="primary" disabled={busy}>
          {busy ? 'Resolving…' : 'Resolve'}
        </Button>
      </form>
      <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-500">
        <Badge value="RxE · RxNorm · ATC" className="bg-slate-700/40 text-slate-300 border-slate-600/40 text-[10px]" />
        <Badge value="CADEC / SMM4H / PharmaCoNER surrogates" className="bg-slate-700/40 text-slate-300 border-slate-600/40 text-[10px]" />
        {hint && <span className="text-rose-300">{hint}</span>}
        {busy && <Spinner label="" />}
      </div>
    </div>
  );
}
