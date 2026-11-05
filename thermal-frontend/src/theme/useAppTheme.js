import { createContext, useContext } from 'react';
import { DEFAULT_THEME, THEMES } from './themeRegistry.js';
const defaultTheme = THEMES[DEFAULT_THEME];
export const ThemeContext = createContext({ themeId: DEFAULT_THEME, setThemeId: () => {}, theme: defaultTheme, tokens: defaultTheme.tokens, chart: defaultTheme.chart, storageAvailable: true });
export function useAppTheme() { return useContext(ThemeContext); }
