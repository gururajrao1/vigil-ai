import { createContext, useContext, useEffect, useState } from 'react';

const STORAGE_KEY = 'vigilai_theme';

export const ThemeContext = createContext({
  theme: 'dark',
  setTheme: () => {},
});

export function useTheme() {
  return useContext(ThemeContext);
}

function readStoredTheme() {
  if (typeof window === 'undefined') return 'dark';
  const saved = localStorage.getItem(STORAGE_KEY);
  return saved === 'light' || saved === 'dark' ? saved : 'dark';
}

export function ThemeProvider({ children }) {
  const [theme, setThemeState] = useState(readStoredTheme);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem(STORAGE_KEY, theme);
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
    <div
      className="flex items-center rounded-lg border border-[var(--app-border)] bg-[var(--app-surface)] p-0.5 text-[11px] shrink-0"
      role="group"
      aria-label="Color theme"
    >
      <button
        type="button"
        onClick={() => setTheme('light')}
        className={`rounded-md px-2.5 py-1 transition-colors ${
          theme === 'light'
            ? 'bg-[var(--app-accent-muted)] text-[var(--app-accent)] font-medium'
            : 'text-[var(--app-text-muted)] hover:text-[var(--app-text)]'
        }`}
      >
        Light
      </button>
      <button
        type="button"
        onClick={() => setTheme('dark')}
        className={`rounded-md px-2.5 py-1 transition-colors ${
          theme === 'dark'
            ? 'bg-[var(--app-accent-muted)] text-[var(--app-accent)] font-medium'
            : 'text-[var(--app-text-muted)] hover:text-[var(--app-text)]'
        }`}
      >
        Dark
      </button>
    </div>
  );
}
