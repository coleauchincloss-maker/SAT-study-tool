// Light / dark / system theme.
//
// "system" is resolved to a concrete value here and written to data-theme, so the
// stylesheet only ever deals with two states. That avoids a media query silently
// overriding an explicit choice, and keeps the resolution logic in one place.

const KEY = 'satquest.theme';
const MODES = ['system', 'light', 'dark'];

const query = window.matchMedia?.('(prefers-color-scheme: light)');

export function themePreference() {
  try {
    const stored = localStorage.getItem(KEY);
    return MODES.includes(stored) ? stored : 'system';
  } catch {
    return 'system';
  }
}

/** What the preference actually resolves to right now. */
export function resolvedTheme(preference = themePreference()) {
  if (preference === 'system') return query?.matches ? 'light' : 'dark';
  return preference;
}

export function applyTheme(preference = themePreference()) {
  const resolved = resolvedTheme(preference);
  document.documentElement.dataset.theme = resolved;
  // Keep the browser UI (form controls, scrollbars) in step.
  document.documentElement.style.colorScheme = resolved;
  return resolved;
}

export function setTheme(preference) {
  try {
    if (preference === 'system') localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, preference);
  } catch {
    /* private browsing — the choice just won't persist */
  }
  return applyTheme(preference);
}

/** Cycle system → light → dark → system, for a single-button control. */
export function cycleTheme() {
  const next = MODES[(MODES.indexOf(themePreference()) + 1) % MODES.length];
  return { preference: next, resolved: setTheme(next) };
}

const LABELS = {
  system: { icon: '🖥️', text: 'System' },
  light: { icon: '☀️', text: 'Light' },
  dark: { icon: '🌙', text: 'Dark' },
};

/** Markup for the toggle. Announces the current setting, not a bare icon. */
export function themeToggle() {
  const preference = themePreference();
  const { icon, text } = LABELS[preference];
  const resolved = resolvedTheme(preference);
  return `
    <button type="button" class="theme-toggle" data-action="theme"
            aria-label="Appearance: ${text}${preference === 'system' ? ` (currently ${resolved})` : ''}. Activate to change."
            title="Appearance: ${text}">
      <span aria-hidden="true">${icon}</span>${text}
    </button>`;
}

/** Follow the OS while the preference is "system". */
export function watchSystemTheme(onChange) {
  query?.addEventListener?.('change', () => {
    if (themePreference() === 'system') {
      applyTheme('system');
      onChange?.();
    }
  });
}

// Apply before first paint so there is no flash of the wrong theme.
applyTheme();
