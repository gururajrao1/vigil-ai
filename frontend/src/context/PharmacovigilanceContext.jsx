import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from 'react';
import { api } from '../api';

/**
 * Global pharmacovigilance clinical state (Phase 5).
 * One Omni-Search drives OMOP PRR grid + Detect corpus filters (no second jump box).
 */
const PharmacovigilanceContext = createContext({
  activeSearchTerm: '',
  eventFilter: '',
  resolvedConcept: null,
  signalData: [],
  isLoading: false,
  searchError: null,
  executeSearch: async () => {},
  setEventFilter: () => {},
  // Back-compat aliases (Module 3 / Omni lens)
  resolvedRxCUI: null,
  resolvedMedDRAPT: null,
  comparisonBrands: [],
  omopSignals: null,
  setFromOmniSearch: () => {},
  setResolvedMedDRAPT: () => {},
  setComparisonBrands: () => {},
  clearClinicalState: () => {},
});

export function usePharmacovigilance() {
  return useContext(PharmacovigilanceContext);
}

function buildResolvedConcept(payload) {
  if (!payload || typeof payload !== 'object') return null;
  const resolved = payload.resolved || {};
  return {
    conceptId: resolved.concept_id ?? payload.concept_ids?.[0] ?? null,
    conceptName: resolved.concept_name || payload.drug_name || null,
    rxcui: resolved.rxcui || payload.resolved_rxcui || payload.rxcui || null,
    meddraId: null,
    vocabularyId: resolved.vocabulary_id || null,
    brandNames: resolved.brand_names || payload.comparison_brands || [],
    activeIngredients: resolved.active_ingredients || [],
    atcCode: resolved.atc_code || null,
    matchMethod: resolved.match_method || null,
    confidence: resolved.confidence ?? null,
    source: payload.source || null,
  };
}

export function PharmacovigilanceProvider({ children }) {
  const [activeSearchTerm, setActiveSearchTerm] = useState('');
  const [eventFilter, setEventFilter] = useState('');
  const [resolvedConcept, setResolvedConcept] = useState(null);
  const [signalData, setSignalData] = useState([]);
  const [omopSignals, setOmopSignals] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [searchError, setSearchError] = useState(null);
  const [resolvedRxCUI, setResolvedRxCUI] = useState(null);
  const [resolvedMedDRAPT, setResolvedMedDRAPT] = useState(null);
  const [comparisonBrands, setComparisonBrands] = useState([]);

  const clearClinicalState = useCallback(() => {
    setActiveSearchTerm('');
    setEventFilter('');
    setResolvedConcept(null);
    setSignalData([]);
    setOmopSignals(null);
    setSearchError(null);
    setResolvedRxCUI(null);
    setResolvedMedDRAPT(null);
    setComparisonBrands([]);
  }, []);

  const applyPayload = useCallback((term, payload) => {
    const concept = buildResolvedConcept(payload);
    const rows = Array.isArray(payload?.adverse_events) ? payload.adverse_events : [];
    const brands =
      concept?.brandNames?.length
        ? concept.brandNames
        : payload?.comparison_brands || [];
    const meddraPt =
      rows[0]?.meddra_pt
      || rows[0]?.condition_name
      || null;

    setActiveSearchTerm(term || '');
    setResolvedConcept(concept);
    setSignalData(rows);
    setOmopSignals(payload);
    setResolvedRxCUI(concept?.rxcui || null);
    setResolvedMedDRAPT(meddraPt);
    setComparisonBrands(Array.isArray(brands) ? brands : []);
    setSearchError(null);
  }, []);

  const executeSearch = useCallback(async (query, { eventAe } = {}) => {
    const q = String(query || '').trim();
    const ae = eventAe !== undefined ? String(eventAe || '').trim() : undefined;
    if (ae !== undefined) setEventFilter(ae);

    if (!q) {
      // AE-only refine of the Detect table (no new drug resolve)
      if (ae !== undefined) {
        setSearchError(null);
        return { mode: 'event_filter', eventFilter: ae };
      }
      setSearchError('Enter a brand, INN, device, vaccine, or clinical term.');
      return null;
    }

    setIsLoading(true);
    setSearchError(null);
    setActiveSearchTerm(q);
    try {
      const payload = await api.omopSignalsByRxcui(q);
      applyPayload(q, payload);
      return payload;
    } catch (err) {
      const message = err?.message || String(err);
      // Symptom / slang → filter Detect by AE instead of hard-failing the page
      if (/adverse event|meddra|symptom/i.test(message)) {
        setEventFilter(q);
        setActiveSearchTerm('');
        setResolvedConcept(null);
        setSignalData([]);
        setOmopSignals(null);
        setResolvedRxCUI(null);
        setResolvedMedDRAPT(q);
        setSearchError(null);
        return { mode: 'ae_detect_filter', term: q };
      }
      // Still seed Detect corpus search with the typed product term
      setSignalData([]);
      setOmopSignals(null);
      setResolvedConcept(null);
      setResolvedRxCUI(null);
      setSearchError(message);
      throw err;
    } finally {
      setIsLoading(false);
    }
  }, [applyPayload]);

  /** Legacy helper used by OmniSearch lens (resolution without full Phase 4 payload). */
  const setFromOmniSearch = useCallback((payload = {}) => {
    const {
      term = '',
      rxcui = null,
      meddraPt = null,
      brands = [],
      omop = null,
    } = payload;
    setActiveSearchTerm(term || '');
    if (rxcui !== undefined) setResolvedRxCUI(rxcui);
    if (meddraPt !== undefined) {
      setResolvedMedDRAPT(meddraPt);
      if (meddraPt) setEventFilter(meddraPt);
    }
    if (brands !== undefined) setComparisonBrands(Array.isArray(brands) ? brands : []);
    if (omop !== undefined && omop !== null) {
      applyPayload(term, omop);
    } else if (omop === null) {
      setOmopSignals(null);
      setSignalData([]);
      setResolvedConcept(
        rxcui || term
          ? {
              conceptId: null,
              conceptName: term || null,
              rxcui,
              meddraId: null,
              vocabularyId: null,
              brandNames: brands || [],
              activeIngredients: [],
              atcCode: null,
              matchMethod: null,
              confidence: null,
              source: null,
            }
          : null,
      );
    }
  }, [applyPayload]);

  const value = useMemo(
    () => ({
      activeSearchTerm,
      eventFilter,
      resolvedConcept,
      signalData,
      isLoading,
      searchError,
      executeSearch,
      setEventFilter,
      resolvedRxCUI,
      resolvedMedDRAPT,
      comparisonBrands,
      omopSignals,
      setFromOmniSearch,
      setResolvedMedDRAPT,
      setComparisonBrands,
      clearClinicalState,
    }),
    [
      activeSearchTerm,
      eventFilter,
      resolvedConcept,
      signalData,
      isLoading,
      searchError,
      executeSearch,
      resolvedRxCUI,
      resolvedMedDRAPT,
      comparisonBrands,
      omopSignals,
      setFromOmniSearch,
      clearClinicalState,
    ],
  );

  return (
    <PharmacovigilanceContext.Provider value={value}>
      {children}
    </PharmacovigilanceContext.Provider>
  );
}
