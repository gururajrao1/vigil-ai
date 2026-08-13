import { createContext, useContext, useEffect, useState } from 'react';
import { SegmentedControl } from '@clairlabs-ai/prp-ui';

const STORAGE_KEY = 'vigilai_theme';
const CLAIR_MODE_KEY = 'clair-mode';

export const ThemeContext = createContext({
  theme: 'dark',
  setTheme: () => {},
});

export function useTheme() {
  return useContext(ThemeContext);
}

function readStoredTheme() {
  if (typeof window === 'undefined') return 'dark';
  const clair = localStorage.getItem(CLAIR_MODE_KEY);
  if (clair === 'light' || clair === 'dark') return clair;
  const saved = localStorage.getItem(STORAGE_KEY);
  return saved === 'light' || saved === 'dark' ? saved : 'dark';
}

function applyMode(theme) {
  document.documentElement.setAttribute('data-mode', theme);
  // Keep legacy attribute so existing [data-theme] CSS keeps working during restyle.
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem(STORAGE_KEY, theme);
  try {
    localStorage.setItem(CLAIR_MODE_KEY, theme);
  } catch {
    /* ignore */
  }
}

export function ThemeProvider({ children }) {
  const [theme, setThemeState] = useState(readStoredTheme);

  useEffect(() => {
    applyMode(theme);
  }, [theme]);

  const setTheme = (next) => {
    if (next === 'light' || next === 'dark') setThemeState(next);
  };

  return (
    <ThemeContext.Provider value={{ theme, setTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  return (
    <SegmentedControl
      aria-label="Color theme"
      value={theme}
      onValueChange={(v) => setTheme(v)}
      options={[
        { value: 'light', label: 'Light' },
        { value: 'dark', label: 'Dark' },
      ]}
    />
  );
}
