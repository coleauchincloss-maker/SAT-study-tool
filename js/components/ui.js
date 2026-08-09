// Small presentational helpers. Everything returns an HTML string; views
// compose them and wire events with delegation.

export function esc(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// Preserve authored line breaks in passages without allowing markup through.
export const escLines = (value) => esc(value).replace(/\n/g, '<br>');

export const pct = (n) => `${Math.round(n * 100)}%`;

/** Level ring: an SVG donut with the level number in the middle. */
export function ring({ value, label, sub, size = 116 }) {
  const r = size / 2 - 9;
  const c = 2 * Math.PI * r;
  const filled = c * Math.max(0, Math.min(1, value));
  return `
    <div class="ring" style="--ring-size:${size}px">
      <svg viewBox="0 0 ${size} ${size}" aria-hidden="true">
        <circle class="ring-track" cx="${size / 2}" cy="${size / 2}" r="${r}"></circle>
        <circle class="ring-fill" cx="${size / 2}" cy="${size / 2}" r="${r}"
          stroke-linecap="${value > 0 ? 'round' : 'butt'}"
          stroke-dasharray="${filled.toFixed(2)} ${c.toFixed(2)}"></circle>
      </svg>
      <div class="ring-label">
        <strong>${esc(label)}</strong>
        ${sub ? `<span>${esc(sub)}</span>` : ''}
      </div>
    </div>`;
}

/** Horizontal accuracy bar with an n= count on the right. */
export function bar({ label, value, seen, tone = 'accent' }) {
  const has = seen > 0;
  return `
    <div class="bar-row">
      <div class="bar-head">
        <span class="bar-label">${esc(label)}</span>
        <span class="bar-value">${has ? pct(value) : '—'}<em>${has ? `${seen} seen` : 'not started'}</em></span>
      </div>
      <div class="bar-track">
        <div class="bar-fill tone-${tone}" style="width:${has ? Math.max(2, value * 100) : 0}%"></div>
      </div>
    </div>`;
}

export function statCard({ label, value, sub, icon, tone = '' }) {
  return `
    <div class="stat ${tone ? `stat-${tone}` : ''}">
      <span class="stat-icon" aria-hidden="true">${icon}</span>
      <span class="stat-value">${esc(value)}</span>
      <span class="stat-label">${esc(label)}</span>
      ${sub ? `<span class="stat-sub">${esc(sub)}</span>` : ''}
    </div>`;
}

/** Bars for daily questions answered, newest on the right. */
export function activityChart(series) {
  const max = Math.max(4, ...series.map((d) => d.answered));
  const cols = series
    .map((d) => {
      const h = (d.answered / max) * 100;
      const acc = d.answered ? d.correct / d.answered : 0;
      const tone = !d.answered ? 'empty' : acc >= 0.8 ? 'good' : acc >= 0.6 ? 'ok' : 'low';
      const title = d.answered
        ? `${d.date}: ${d.correct}/${d.answered} correct · ${d.xp} XP`
        : `${d.date}: no practice`;
      return `<div class="spark-col" title="${esc(title)}">
          <div class="spark-bar spark-${tone}" style="height:${Math.max(d.answered ? 6 : 2, h)}%"></div>
        </div>`;
    })
    .join('');
  return `<div class="spark">${cols}</div>
    <div class="spark-axis"><span>14 days ago</span><span>today</span></div>`;
}

export function badgeShelf(allBadges, earnedIds) {
  const earned = new Set(earnedIds);
  return `<div class="badges">${allBadges
    .map(
      (b) => `<div class="badge ${earned.has(b.id) ? 'is-earned' : 'is-locked'}"
          title="${esc(b.name)} — ${esc(b.desc)}">
          <span class="badge-icon" aria-hidden="true">${b.icon}</span>
          <span class="badge-name">${esc(b.name)}</span>
        </div>`,
    )
    .join('')}</div>`;
}

export function table({ headers, rows }) {
  return `<table class="q-table">
      <thead><tr>${headers.map((h) => `<th>${esc(h)}</th>`).join('')}</tr></thead>
      <tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody>
    </table>`;
}

export const sectionPill = (section) =>
  `<span class="pill pill-${section}">${section === 'math' ? 'Math' : 'Reading & Writing'}</span>`;

export const difficultyDots = (d) =>
  `<span class="dots" title="Difficulty ${d} of 3">${'●'.repeat(d)}${'○'.repeat(3 - d)}</span>`;
