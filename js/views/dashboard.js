// The dashboard — the app's home view.

import { BADGES, MODES, activitySeries, domainStats, levelInfo, scoreFeel, strongestSkill, titleForLevel, weakSpots } from '../engine.js';
import { DOMAINS } from '../questions.js';
import { topNav } from '../components/nav.js';
import { activityChart, badgeShelf, bar, esc, pct, ring, statCard } from '../components/ui.js';

function modeCard(mode) {
  return `
    <button class="mode" data-action="start" data-mode="${mode.id}">
      <span class="mode-icon" aria-hidden="true">${mode.icon}</span>
      <span class="mode-body">
        <strong>${esc(mode.name)}</strong>
        <span>${esc(mode.blurb)}</span>
      </span>
      <span class="mode-go" aria-hidden="true">▶</span>
    </button>`;
}

function weakSpotList(state) {
  const spots = weakSpots(state, 5);
  if (!spots.length) {
    return `<p class="empty">Answer a few rounds and your weakest skills will be ranked here, worst first.</p>`;
  }
  return `<ul class="weak-list">${spots
    .map(
      (s) => `<li>
        <div class="weak-main">
          <span class="weak-skill">${esc(s.skill)}</span>
          <span class="weak-domain">${esc(s.domain)}</span>
        </div>
        <div class="weak-score ${s.accuracy < 0.5 ? 'is-bad' : s.accuracy < 0.75 ? 'is-mid' : 'is-good'}">
          ${pct(s.accuracy)}<em>${s.correct}/${s.seen}</em>
        </div>
      </li>`,
    )
    .join('')}</ul>
    <button class="btn btn-ghost btn-block" data-action="start" data-mode="drill">Drill these five →</button>`;
}

function sectionPanel(state, section, label) {
  const stats = domainStats(state, section);
  const feel = scoreFeel(state, section);
  const rows = DOMAINS[section]
    .map((domain) => {
      const s = stats.get(domain) ?? { seen: 0, correct: 0 };
      const value = s.seen ? s.correct / s.seen : 0;
      const tone = !s.seen ? 'accent' : value >= 0.8 ? 'good' : value >= 0.6 ? 'ok' : 'low';
      return bar({ label: domain, value, seen: s.seen, tone });
    })
    .join('');
  return `
    <div class="panel-section">
      <div class="panel-section-head">
        <h3>${esc(label)}</h3>
        <span class="score-feel">${feel ? `${feel} <em>score feel</em>` : '<em>needs 5+ questions</em>'}</span>
      </div>
      ${rows}
    </div>`;
}

export function renderDashboard(root, { state, actions, lobby }) {
  const lvl = levelInfo(state.xp);
  const accuracy = state.totalAnswered ? state.totalCorrect / state.totalAnswered : 0;
  const strong = strongestSkill(state);
  const series = activitySeries(state, 14);
  const activeDays = series.filter((d) => d.answered > 0).length;

  const extraRight = `
    <div class="streak ${state.streak > 0 ? 'is-live' : ''}" title="Consecutive days played">
      <span aria-hidden="true">🔥</span>
      <strong>${state.streak}</strong>
      <em>day streak</em>
    </div>
    <button class="btn btn-quiet btn-sm" data-action="reset" title="Erase all local progress">Reset</button>`;

  root.innerHTML = `
    <div class="wrap">
      ${topNav({ active: 'dashboard', name: lobby?.name ?? '', extraRight })}

      <section class="hero card">
        ${ring({ value: lvl.pct / 100, label: `L${lvl.level}`, sub: 'level' })}
        <div class="hero-body">
          <span class="hero-title">${esc(titleForLevel(lvl.level))}</span>
          <div class="xp-track" role="progressbar" aria-valuenow="${Math.round(lvl.pct)}" aria-valuemin="0" aria-valuemax="100">
            <div class="xp-fill" style="width:${lvl.pct}%"></div>
          </div>
          <span class="hero-meta">
            <strong>${state.xp.toLocaleString()} XP</strong> total ·
            ${lvl.toNext.toLocaleString()} XP to level ${lvl.level + 1}
          </span>
        </div>
        <div class="hero-cta">
          <button class="btn btn-primary" data-action="start" data-mode="quick">Start Quick 10</button>
          <button class="btn btn-ghost" data-action="start" data-mode="sprint">Timed Sprint</button>
        </div>
      </section>

      <section class="stats">
        ${statCard({ icon: '🧮', label: 'Questions answered', value: state.totalAnswered, sub: `${state.rounds} rounds` })}
        ${statCard({
          icon: '🎯',
          label: 'Overall accuracy',
          value: state.totalAnswered ? pct(accuracy) : '—',
          sub: state.totalAnswered ? `${state.totalCorrect} correct` : 'no data yet',
          tone: accuracy >= 0.8 ? 'good' : accuracy >= 0.6 ? 'ok' : state.totalAnswered ? 'low' : '',
        })}
        ${statCard({ icon: '⛓️', label: 'Best combo', value: state.bestCombo, sub: 'consecutive correct' })}
        ${statCard({
          icon: '🏅',
          label: 'Badges',
          value: `${state.badges.length}/${BADGES.length}`,
          sub: `${state.perfectRounds} perfect round${state.perfectRounds === 1 ? '' : 's'}`,
        })}
      </section>

      <div class="grid">
        <section class="card col-8">
          <h2>Accuracy by domain</h2>
          <p class="card-sub">Where the points are going. “Score feel” is a rough 200–800 mapping of your accuracy — motivation, not a predicted score.</p>
          ${sectionPanel(state, 'math', 'Math')}
          ${sectionPanel(state, 'rw', 'Reading & Writing')}
        </section>

        <section class="card col-4">
          <h2>Weak spots</h2>
          <p class="card-sub">Skills you have missed, ranked worst-first.</p>
          ${weakSpotList(state)}
          ${
            strong
              ? `<div class="strong-note"><span aria-hidden="true">💪</span> Strongest right now: <strong>${esc(
                  strong.skill,
                )}</strong> at ${pct(strong.accuracy)}</div>`
              : ''
          }
        </section>

        <section class="card col-5">
          <h2>Practice modes</h2>
          <div class="modes">${Object.values(MODES).map(modeCard).join('')}</div>
        </section>

        <section class="card col-7 activity-card">
          <h2>Activity</h2>
          <p class="card-sub">${activeDays} of the last 14 days practiced. Bar height is questions answered; color is that day's accuracy.</p>
          ${activityChart(series)}
        </section>

        <section class="card col-12">
          <h2>Badges <span class="count">${state.badges.length}/${BADGES.length}</span></h2>
          ${badgeShelf(BADGES, state.badges)}
        </section>
      </div>

      <footer class="foot">
        All questions are original practice items written for this app — not reproduced College Board material.
        Progress is stored locally in this browser.
      </footer>
    </div>`;

  root.oninput = (event) => {
    const field = event.target.closest('[data-field]');
    if (field) actions.setLobbyField(field.dataset.field, field.value);
  };

  root.onclick = (event) => {
    const btn = event.target.closest('[data-action]');
    if (!btn) return;
    if (btn.dataset.action === 'start') actions.startRound(btn.dataset.mode);
    if (btn.dataset.action === 'reset') actions.hardReset();
    if (btn.dataset.action === 'navigate') actions.navigate(btn.dataset.route);
    if (btn.dataset.action === 'theme') actions.cycleTheme();
  };
}
