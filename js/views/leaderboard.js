// Leaderboard: three tabs. "Global" and "Nearby" are real, pulled from the
// server's shared leaderboard (data/leaderboard.json) — every browser that's
// played submits its own stats there. "Friends" is real too, but purely
// local: your actual head-to-head record against people you've dueled, from
// rivals.js. None of this is behind a login, so treat rank as a fun
// scoreboard, not a verified one — see the note under the location field.

import { esc, pct } from '../components/ui.js';
import { topNav } from '../components/nav.js';
import { levelInfo } from '../engine.js';
import { fetchLeaderboard } from '../net.js';
import { myPlayerId, overallRecord, rivalList } from '../rivals.js';

const TABS = {
  global: { label: 'Global', sub: 'Every player who has submitted a score' },
  nearby: { label: 'Nearby', sub: 'Filtered to your location, below' },
  friends: { label: 'Friends', sub: "People you've actually dueled" },
};

let activeTab = 'global';
/** null = not fetched yet, otherwise the last response for that tab. */
const cache = { global: null, nearby: null };
/** The location string the cached "nearby" result was fetched for. */
let nearbyFetchedFor = null;
let loading = false;
let submittedThisSession = false;

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

function friendsList(state, name) {
  const list = rivalList().map((r) => ({
    name: r.name,
    xp: Math.max(0, r.pointsFor) * 10,
    accuracy: r.matches ? r.pointsFor / Math.max(1, r.pointsFor + r.pointsAgainst) : 0,
    wins: r.wins,
    streak: Math.max(0, r.streak),
  }));
  list.push(myRow(state, name));
  list.sort((a, b) => b.xp - a.xp);
  return list;
}

function serverList(rows, state, name) {
  const myId = myPlayerId();
  const list = rows.map((p) => ({
    name: p.id === myId ? `${p.name} (you)` : p.name,
    xp: p.xp,
    accuracy: p.accuracy,
    wins: p.wins,
    streak: p.bestCombo,
    isMe: p.id === myId,
  }));
  // Your own row comes back from the server once the first submit round-trips.
  // Before that (e.g. the very first visit), show a local fallback row instead.
  if (!list.some((p) => p.isMe)) list.push(myRow(state, name));
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
  // Push your current stats once per visit so your row is fresh, then
  // populate whichever tab is active.
  if (!submittedThisSession) {
    submittedThisSession = true;
    actions.submitLeaderboardStats();
  }

  if (activeTab === 'global' && cache.global === null && !loading) {
    loading = true;
    fetchLeaderboard({ limit: 100 }).then((res) => {
      cache.global = res.players ?? [];
      loading = false;
      renderLeaderboard(root, { state, actions, lobby });
    });
  }
  if (activeTab === 'nearby' && lobby.location && (cache.nearby === null || nearbyFetchedFor !== lobby.location) && !loading) {
    loading = true;
    nearbyFetchedFor = lobby.location;
    fetchLeaderboard({ location: lobby.location, limit: 100 }).then((res) => {
      cache.nearby = res.players ?? [];
      loading = false;
      renderLeaderboard(root, { state, actions, lobby });
    });
  }

  const meta = TABS[activeTab];
  const lvl = levelInfo(state.xp);

  let list;
  let bodyContent;
  if (activeTab === 'friends') {
    list = friendsList(state, lobby.name);
  } else if (activeTab === 'nearby' && !lobby.location) {
    list = [];
  } else {
    const rows = activeTab === 'global' ? cache.global : cache.nearby;
    list = rows === null ? null : serverList(rows, state, lobby.name);
  }

  const myRank = Array.isArray(list) ? list.findIndex((p) => p.isMe) + 1 : 0;

  if (activeTab === 'nearby' && !lobby.location) {
    bodyContent = `<p class="empty">Add your location above, then click Save — this tab ranks you against everyone who set the same one.</p>`;
  } else if (list === null) {
    bodyContent = `<p class="empty">Loading rankings…</p>`;
  } else if (!list.length) {
    bodyContent = `<p class="empty">${activeTab === 'friends' ? 'Nobody here yet — duel a friend to show up on the board.' : 'Nobody here yet — be the first to show up on this board.'}</p>`;
  } else {
    const top3 = list.slice(0, 3);
    const podiumOrder = [top3[1], top3[0], top3[2]];
    bodyContent = `
      ${list.length >= 3
        ? `<div class="lb-podium">
            ${podiumOrder
              .map((p, i) => {
                if (!p) return '';
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
      <table class="lb-table">
        <thead><tr><th>RANK</th><th>PLAYER</th><th>XP</th><th>ACCURACY</th><th>WINS</th><th>FORM</th></tr></thead>
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
      </table>`;
  }

  root.innerHTML = `
    <div class="wrap">
      ${topNav({ active: 'leaderboard', name: lobby.name })}

      <section class="card lb-header">
        <div>
          <div class="eyebrow">SAT QUEST &middot; LIVE RANKINGS</div>
          <h1 class="page-hero lb-title">Climb the Duel leaderboard</h1>
          <p class="page-hero-sub lb-sub">Win duels, answer accurately, and keep your streak alive to move up.</p>
        </div>
        <div class="lb-position">
          <div class="lb-position-label">YOUR POSITION</div>
          <div class="lb-position-rank">${myRank ? `#${myRank}` : '—'}</div>
          <div class="lb-position-sub">Level ${lvl.level} &middot; ${state.xp.toLocaleString()} total XP</div>
        </div>
      </section>

      <section class="card lb-location">
        <label for="lb-location-input"><strong>Your location</strong> <span class="card-sub">— a city, school, or region. Used to group the Nearby tab.</span></label>
        <div class="lb-location-row">
          <input id="lb-location-input" class="wide-field" type="text" value="${esc(lobby.location)}"
                 data-field="location" placeholder="e.g. London, or your school's name" maxlength="40" />
          <button class="btn btn-primary" data-action="save-location">Save</button>
        </div>
        <p class="card-sub">Self-reported, like your name — there's no login, so this (and every score here) is exactly as honest as whoever typed it.</p>
      </section>

      <div class="lb-tabs">
        ${Object.entries(TABS)
          .map(([id, t]) => `<button type="button" class="${id === activeTab ? 'is-on' : ''}" data-action="tab" data-tab="${id}">${esc(t.label)}</button>`)
          .join('')}
      </div>

      <section class="card lb-body">
        <h2>${esc(meta.label)}</h2>
        <p class="card-sub lb-resets">${esc(meta.sub)}</p>
        ${bodyContent}
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
    else if (action === 'save-location') {
      cache.nearby = null;
      actions.submitLeaderboardStats();
      if (activeTab !== 'nearby') {
        activeTab = 'nearby';
      }
      renderLeaderboard(root, { state, actions, lobby });
    } else if (action === 'tab') {
      activeTab = button.dataset.tab;
      renderLeaderboard(root, { state, actions, lobby });
    } else if (action === 'theme') actions.cycleTheme();
  };
}
