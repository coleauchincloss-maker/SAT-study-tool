// Shared top navigation used by the three top-level pages (Duel, Leaderboard,
// Dashboard). Kept as one component so the three pages read as one app instead
// of three loosely related screens.

import { esc } from './ui.js';
import { themeToggle } from '../theme.js';

const TABS = [
  { id: 'home', label: 'Duel' },
  { id: 'leaderboard', label: 'Leaderboard' },
  { id: 'dashboard', label: 'Dashboard' },
  { id: 'import', label: 'Import' },
];

export function topNav({ active, name = '', extraRight = '' }) {
  const tabs = TABS.map(
    (t) => `
    <button type="button" class="nav-pill ${active === t.id ? 'is-on' : ''}"
            data-action="navigate" data-route="${t.id}">${esc(t.label)}</button>`,
  ).join('');

  return `
    <header class="topbar">
      <div class="brand">
        <span class="brand-mark" aria-hidden="true">⚔</span>
        <div>
          <h1>SAT Quest</h1>
          <p>1v1 SAT duels</p>
        </div>
      </div>
      <nav class="top-nav" aria-label="Sections">${tabs}</nav>
      <div class="topbar-right">
        <label class="sr-only" for="player-name">Your name</label>
        <input class="name-field" id="player-name" type="text" value="${esc(name)}" data-field="name"
               placeholder="Your name" maxlength="16" />
        ${themeToggle()}
        ${extraRight}
      </div>
    </header>`;
}
