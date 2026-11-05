export const THEME_STORAGE_KEY = 'thermalagent.theme.v1';
export const DEFAULT_THEME = 'engineering';

// Semantic tokens keep a third visual theme independent from application state.
export const THEMES = Object.freeze({
  engineering: {
    id: 'engineering', name: 'Engineering Professional', label: '工程白', description: '白灰蓝 · 专业工程工作台',
    tokens: { bg: '#f3f6fa', surface: '#ffffff', surfaceRaised: '#ffffff', surfaceMuted: '#edf2f7', text: '#182b43', textMuted: '#53667c', border: '#cdd8e5', primary: '#175cce', primarySoft: '#e9f1ff', success: '#217346', warning: '#91520a', danger: '#b42332', info: '#236a89', radius: 12, lineWidth: 1 },
    chart: { primary: '#175cce', secondary: '#16836b', grid: '#cdd8e5', text: '#384f68', background: '#ffffff' },
  },
  cel: {
    id: 'cel', name: 'Anime Cel-shading', label: 'Anime V3', description: '赛璐璐 · Anime Cel-shading / 研究所任务终端',
    tokens: { bg: '#e9eef7', surface: '#fffdf8', surfaceRaised: '#ffffff', surfaceMuted: '#e8edf6', text: '#222b48', textMuted: '#576179', border: '#596480', primary: '#5746c4', primarySoft: '#eeebff', success: '#286548', warning: '#985020', danger: '#ac3346', info: '#167b89', radius: 5, lineWidth: 1 },
    chart: { primary: '#5746c4', secondary: '#167b89', grid: '#c1cadb', text: '#222b48', background: '#fffdf8' },
  },
  hyper: {
    id: 'hyper', name: 'Hyper Fun / Elysian Atelier', label: 'Hyper Fun', description: 'Hyper Fun · 花与书的工程手记 · 粉白',
    tokens: { bg: '#fffafb', surface: '#ffffff', surfaceRaised: '#ffffff', surfaceMuted: '#f8eaf0', text: '#302d3d', textMuted: '#716774', border: '#ecdde3', primary: '#a84671', primarySoft: '#faeaf2', success: '#336858', warning: '#895519', danger: '#ac3656', info: '#3d6884', radius: 12, lineWidth: 1 },
    chart: { primary: '#a84671', secondary: '#3d6884', grid: '#ecdde3', text: '#302d3d', background: '#ffffff' },
  },
});

export function normalizeThemeId(value) { return Object.hasOwn(THEMES, value) ? value : DEFAULT_THEME; }
export function readThemePreference(storage) {
  try { return { themeId: normalizeThemeId((storage || globalThis.localStorage).getItem(THEME_STORAGE_KEY)), storageAvailable: true }; }
  catch { return { themeId: DEFAULT_THEME, storageAvailable: false }; }
}
export function saveThemePreference(value, storage) {
  try { (storage || globalThis.localStorage).setItem(THEME_STORAGE_KEY, normalizeThemeId(value)); return true; }
  catch { return false; }
}
export function antThemeConfig(themeId) {
  const { tokens: t } = THEMES[normalizeThemeId(themeId)];
  return { token: { colorPrimary: t.primary, colorInfo: t.info, colorSuccess: t.success, colorWarning: t.warning, colorError: t.danger, colorText: t.text, colorTextSecondary: t.textMuted, colorBorder: t.border, colorBgBase: t.surface, colorBgContainer: t.surface, colorBgElevated: t.surfaceRaised, colorFillAlter: t.surfaceMuted, borderRadius: t.radius, lineWidth: t.lineWidth, fontFamily: '"Segoe UI", "Microsoft YaHei", system-ui, sans-serif', fontSize: 14 }, components: { Layout: { bodyBg: t.bg, siderBg: t.surface }, Table: { headerBg: t.surfaceMuted } } };
}
