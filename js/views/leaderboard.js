// Leaderboard: there's no account system or shared server-side ranking here —
// matches are ephemeral 1v1 rooms — so "This week" / "All time" are clearly
// labeled demo data for flavor, blended with your real local stats. "Friends"
// is the one tab that's fully real: it's your actual head-to-head record
// against people you've played, from rivals.js.

import { esc, pct } from '../components/ui.js';
import { topNav } from '../components/nav.js';
import { levelInfo } from '../engine.js';
import { overallRecord, rivalList } from '../rivals.js';

const DEMO_BASE = [
  { name: 'Maya R.', xp: 3180, accuracy: 0.96, wins: 18, streak: 12 },
  { name: 'TheoPark', xp: 2940, accuracy: 0.91, wins: 16, streak: 8 },
  { name: 'calc_wizard', xp: 2765, accuracy: 0.89, wins: 14, streak: 6 },
  { name: 'Zara T.', xp: 2440, accuracy: 0.87, wins: 13, streak: 4 },
  { name: 'NoahBuilds', xp: 2180, accuracy: 0.84, wins: 11, streak: 3 },
  { name: 'priya_k', xp: 1990, accuracy: 0.82, wins: 10, streak: 2 },
  { name: 'jwrites', xp: 1820, accuracy: 0.80, wins: 9, streak: 1 },
  { name: 'sam_b', xp: 1610, accuracy: 0.78, wins: 8, streak: 0 },
];

const TABS = {
  week: { label: 'This week', sub: 'Resets Monday at midnight', mult: 1, mock: true },
  all: { label: 'All time', sub: 'Cumulative since you started', mult: 6.5, mock: true },
  friends: { label: 'Friends', sub: "People you've actually dueled", mult: 1, mock: false },
};

let activeTab = 'week';

function initials(name) {
  return (name || '?').trim().charAt(0).toUpperCase();
}

function myRow(state, name) {
  const lvl = levelInfo(state.xp);
  const accuracy = state.totalAnswered ? state.totalCorrect / state.totalAnswered : 0;
  const record = overallRecord();
  return {
    name: `${name || 'You'} (you)`,
    xp: state.xp,
    accuracy,
    wins: record.wins,
    streak: state.bestCombo,
    isMe: true,
    level: lvl.level,
  };
}

function buildList(tab, state, name) {
  const meta = TABS[tab];
  let list;
  if (tab === 'friends') {
    list = rivalList().map((r) => ({
      name: r.name,
      xp: Math.max(0, r.pointsFor) * 10,
      accuracy: r.matches ? r.pointsFor / Math.max(1, r.pointsFor + r.pointsAgainst) : 0,
      wins: r.wins,
      streak: Math.max(0, r.streak),
    }));
  } else {
    list = DEMO_BASE.map((p) => ({ ...p, xp: Math.round(p.xp * meta.mult), wins: Math.round(p.wins * meta.mult) }));
  }
  list.push(myRow(state, name));
  list.sort((a, b) => b.xp - a.xp);
  return list;
}

function formPill(streak) {
  if (streak >= 6) return `<span class="streak-pill is-hot">🔥 ${streak}</span>`;
  if (streak > 0) return `<span class="streak-pill">${streak} straight</span>`;
  return `<span class="streak-pill is-flat">—</span>`;
}

function medal(rank) {
  return rank <= 3 ? `<div class="medal medal-${rank}">${rank}</div>` : '';
}

export function renderLeaderboard(root, { state, actions, lobby }) {
  const meta = TABS[activeTab];
  const list = buildList(activeTab, state, lobby.name);
  const myRank = list.findIndex((p) => p.isMe) + 1;
  const lvl = levelInfo(state.xp);

  const top3 = list.slice(0, 3);
  const podiumOrder = [top3[1], top3[0], top3[2]];

  root.innerHTML = `
    <div class="wrap">
      ${topNav({ active: 'leaderboard', name: lobby.name })}

      <section class="card lb-header">
        <div>
          <div class="eyebrow">SAT QUEST &middot; DEMO LEAGUE</div>
          <h1 class="page-hero lb-title">Climb the Duel leaderboard</h1>
          <p class="page-hero-sub lb-sub">Win duels, answer accurately, and keep your streak alive to move up.</p>
        </div>
        <div class="lb-position">
          <div class="lb-position-label">YOUR POSITION</div>
          <div class="lb-position-rank">#${myRank}</div>
          <div class="lb-position-sub">Level ${lvl.level} &middot; ${state.xp.toLocaleString()} total XP</div>
        </div>
      </section>

      <div class="lb-tabs">
        ${Object.entries(TABS)
          .map(([id, t]) => `<button type="button" class="${id === activeTab ? 'is-on' : ''}" data-action="tab" data-tab="${id}">${esc(t.label)}</button>`)
          .join('')}
      </div>

      <section class="card lb-body">
        ${meta.mock ? '<span class="mock-pill">MOCK RANKINGS</span>' : ''}
        <h2>${esc(meta.label)}</h2>
        <p class="card-sub lb-resets">${esc(meta.sub)}</p>

        ${list.length >= 3
          ? `<div class="lb-podium">
              ${podiumOrder
                .map((p, i) => {
                  const rank = i === 1 ? 1 : i === 0 ? 2 : 3;
                  return `<div class="lb-podium-card ${rank === 1 ? 'is-first' : ''} ${p.isMe ? 'is-me' : ''}">
                    ${medal(rank)}
                    <div class="lb-avatar">${esc(initials(p.name))}</div>
                    <div class="lb-podium-name">${esc(p.name)}</div>
                    <div class="lb-podium-xp">${Math.round(p.xp).toLocaleString()}</div>
                  </div>`;
                })
                .join('')}
            </div>`
          : ''}

        ${list.length
          ? `<table class="lb-table">
              <thead><tr><th>RANK</th><th>PLAYER</th><th>${activeTab === 'friends' ? 'RECORD XP' : 'WEEKLY XP'}</th><th>ACCURACY</th><th>WINS</th><th>FORM</th></tr></thead>
              <tbody>
                ${list
                  .map(
                    (p, i) => `<tr class="${p.isMe ? 'is-me' : ''}">
                      <td>${i + 1}</td>
                      <td class="lb-name-cell"><span class="lb-mini-avatar">${esc(initials(p.name))}</span>${esc(p.name)}</td>
                      <td>${Math.round(p.xp).toLocaleString()}</td>
                      <td>${pct(p.accuracy)}</td>
                      <td>${p.wins}</td>
                      <td>${formPill(p.streak)}</td>
                    </tr>`,
                  )
                  .join('')}
              </tbody>
            </table>`
          : '<p class="empty">Nobody here yet — duel a friend to show up on the board.</p>'}
      </section>
    </div>`;

  root.oninput = (event) => {
    const field = event.target.closest('[data-field]');
    if (field) actions.setLobbyField(field.dataset.field, field.value);
  };

  root.onclick = (event) => {
    const button = event.target.closest('[data-action]');
    if (!button) return;
    const { action } = button.dataset;
    if (action === 'navigate') actions.navigate(button.dataset.route);
    else if (action === 'tab') {
      activeTab = button.dataset.tab;
      renderLeaderboard(root, { state, actions, lobby });
    } else if (action === 'theme') actions.cycleTheme();
  };
}
