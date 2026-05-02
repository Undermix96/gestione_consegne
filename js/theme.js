/**
 * theme.js — Gestione tema chiaro/scuro
 */

const THEME_KEY = 'gc_theme';

export function initTheme() {
  const saved       = localStorage.getItem(THEME_KEY);
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const theme       = saved || (prefersDark ? 'dark' : 'light');
  applyTheme(theme, false);
}

export function applyTheme(theme, save = true) {
  document.documentElement.setAttribute('data-theme', theme);
  const btn = document.getElementById('themeBtn');
  if (btn) btn.textContent = theme === 'dark' ? '☀️' : '🌙';
  if (save) localStorage.setItem(THEME_KEY, theme);
}

export function toggleTheme() {
  const cur = document.documentElement.getAttribute('data-theme') || 'dark';
  applyTheme(cur === 'dark' ? 'light' : 'dark');
}
