import { useCallback, useEffect, useMemo, useState } from 'react';
import { ConfigProvider } from 'antd';
import { antThemeConfig, normalizeThemeId, readThemePreference, saveThemePreference, THEMES, THEME_STORAGE_KEY } from './themeRegistry.js';
import { ThemeContext } from './useAppTheme.js';
import './theme.css';
import './hyperShell.css';

export default function ThemeProvider({ children }) {
  const [preference, setPreference] = useState(readThemePreference);
  const themeId = preference.themeId;
  const setThemeId = useCallback(value => {
    const next = normalizeThemeId(value);
    setPreference({ themeId: next, storageAvailable: saveThemePreference(next) });
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = themeId;
    document.documentElement.style.colorScheme = 'light';
  }, [themeId]);
  useEffect(() => {
    const receive = event => { if (event.key === THEME_STORAGE_KEY || event.key === null) setPreference({ themeId: normalizeThemeId(event.newValue), storageAvailable: true }); };
    window.addEventListener('storage', receive);
    return () => window.removeEventListener('storage', receive);
  }, []);
  const value = useMemo(() => ({ ...preference, setThemeId, theme: THEMES[themeId], tokens: THEMES[themeId].tokens, chart: THEMES[themeId].chart }), [preference, setThemeId, themeId]);
  return <ThemeContext.Provider value={value}><ConfigProvider theme={antThemeConfig(themeId)}>{children}</ConfigProvider></ThemeContext.Provider>;
}
