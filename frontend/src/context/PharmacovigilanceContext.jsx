import { createContext, useCallback, useContext, useMemo, useState } from 'react';

/**
 * Global clinical state for the OMOP-driven SPA (Module 3).
 * Omni-Search updates this context; Signals / analytics re-render without a full reload.
 */
const PharmacovigilanceContext = createContext({
  activeSearchTerm: '',
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

export function PharmacovigilanceProvider({ children }) {
  const [activeSearchTerm, setActiveSearchTerm] = useState('');
  const [resolvedRxCUI, setResolvedRxCUI] = useState(null);
  const [resolvedMedDRAPT, setResolvedMedDRAPT] = useState(null);
  const [comparisonBrands, setComparisonBrands] = useState([]);
  const [omopSignals, setOmopSignals] = useState(null);

  const clearClinicalState = useCallback(() => {
    setActiveSearchTerm('');
    setResolvedRxCUI(null);
    setResolvedMedDRAPT(null);
    setComparisonBrands([]);
    setOmopSignals(null);
  }, []);

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
    if (meddraPt !== undefined) setResolvedMedDRAPT(meddraPt);
    if (brands !== undefined) setComparisonBrands(Array.isArray(brands) ? brands : []);
    if (omop !== undefined) setOmopSignals(omop);
  }, []);

  const value = useMemo(
    () => ({
      activeSearchTerm,
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
