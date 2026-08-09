// Round summary: XP earned, accuracy, new badges, and per-question review.

import { levelInfo, titleForLevel } from '../engine.js';
import { esc, pct, ring, statCard } from '../components/ui.js';

const LETTERS = ['A', 'B', 'C', 'D'];

/** Challenge-code outcome: the code to send, or the verdict against their run. */
function challengeBlock(challenge) {
  if (!challenge) return '';

  if (challenge.kind === 'send') {
    return `
      <section class="card challenge-card">
        <span class="eyebrow">Challenge ready</span>
        <h2>Send this to your friend</h2>
        <p class="card-sub">
          They paste it into their copy of SAT Quest and race the exact same eight questions.
          Your score is baked in.
        </p>
        <div class="vs-share">
          <input type="text" readonly value="${esc(challenge.code)}" data-challenge-code aria-label="Challenge code" />
          <button class="btn btn-primary btn-sm" data-action="copy-challenge">Copy</button>
        </div>
      </section>`;
  }

  const { verdict, them, tally } = challenge;
  const headline =
    verdict.result === 'win'
      ? `You beat ${esc(them.name)}`
      : verdict.result === 'loss'
        ? `${esc(them.name)} beat you`
        : `Tied with ${esc(them.name)}`;
  const tiebreak =
    verdict.myCorrect === them.theirCorrect && verdict.result !== 'draw'
      ? ` Same score, decided on time (${(verdict.myTimeMs / 1000).toFixed(1)}s vs ${(them.theirTimeMs / 1000).toFixed(1)}s).`
      : '';

  return `
    <section class="card challenge-card ${verdict.result === 'win' ? 'is-win' : verdict.result === 'loss' ? 'is-loss' : ''}">
      <span class="eyebrow">Challenge result</span>
      <h2>${headline}</h2>
      <div class="vs-final">
        <div><strong>${verdict.myCorrect}</strong><span>you</span></div>
        <em>–</em>
        <div><strong>${them.theirCorrect}</strong><span>${esc(them.name)}</span></div>
      </div>
      <p class="card-sub">Out of ${verdict.total}.${tiebreak} You're now ${esc(tally)} against them.</p>
    </section>`;
}

export function renderResults(root, { state, summary, actions }) {
  const { session, newBadges, leveledTo } = summary;
  const accuracy = session.answered ? session.correct / session.answered : 0;
  const lvl = levelInfo(state.xp);
  const seconds = Math.round(session.durationMs / 1000);
  const perQuestion = session.answered ? (session.durationMs / session.answered / 1000).toFixed(1) : '0';

  const headline = session.abandoned
    ? 'Round ended early'
    : accuracy === 1
      ? 'Perfect round'
      : accuracy >= 0.8
        ? 'Strong round'
        : accuracy >= 0.5
          ? 'Solid work'
          : 'Rough one — good data though';

  root.innerHTML = `
    <div class="wrap wrap-results">
      <section class="card results-hero">
        <div>
          <span class="eyebrow">${esc(session.abandoned ? 'Partial round banked' : 'Round complete')}</span>
          <h1>${esc(headline)}</h1>
          <p class="results-sub">${session.correct} of ${session.answered} correct in ${seconds}s (${perQuestion}s per question).</p>
        </div>
        ${ring({ value: accuracy, label: pct(accuracy), sub: 'accuracy', size: 128 })}
      </section>

      ${challengeBlock(summary.challenge)}

      ${
        leveledTo
          ? `<div class="levelup card">
               <span class="levelup-icon" aria-hidden="true">🎉</span>
               <div>
                 <strong>Level ${leveledTo} reached</strong>
                 <span>You are now a ${esc(titleForLevel(leveledTo))}.</span>
               </div>
             </div>`
          : ''
      }

      <section class="stats">
        ${statCard({ icon: '✨', label: 'XP earned', value: `+${session.xp}`, sub: `${state.xp.toLocaleString()} total`, tone: 'good' })}
        ${statCard({ icon: '⛓️', label: 'Best combo', value: session.bestCombo, sub: `${state.bestCombo} all-time` })}
        ${statCard({ icon: '🔥', label: 'Day streak', value: state.streak, sub: 'keep it alive tomorrow' })}
        ${statCard({ icon: '📊', label: 'Level progress', value: `L${lvl.level}`, sub: `${lvl.toNext} XP to next` })}
      </section>

      ${
        newBadges.length
          ? `<section class="card">
               <h2>New badges</h2>
               <div class="badges">${newBadges
                 .map(
                   (b) => `<div class="badge is-earned is-new" title="${esc(b.desc)}">
                       <span class="badge-icon" aria-hidden="true">${b.icon}</span>
                       <span class="badge-name">${esc(b.name)}</span>
                     </div>`,
                 )
                 .join('')}</div>
             </section>`
          : ''
      }

      <section class="card">
        <h2>Question review</h2>
        <ol class="review">
          ${session.results
            .map(
              (r, i) => `<li class="${r.correct ? 'is-correct' : 'is-wrong'}">
                <div class="review-head">
                  <span class="review-num">${i + 1}</span>
                  <span class="review-skill">${esc(r.question.skill)}</span>
                  <span class="review-mark">${r.correct ? `+${r.xpGained} XP` : `answer ${LETTERS[r.question.answer]}`}</span>
                </div>
                <p class="review-prompt">${esc(r.question.prompt.split('\n').pop())}</p>
                ${r.correct ? '' : `<p class="review-explain">${esc(r.question.explanation)}</p>`}
              </li>`,
            )
            .join('')}
        </ol>
      </section>

      <div class="results-actions">
        <button class="btn btn-primary" data-action="home">Back to the lobby</button>
        <button class="btn btn-ghost" data-action="again" data-mode="${esc(session.mode)}">Run it again</button>
        <button class="btn btn-quiet" data-action="again" data-mode="drill">Drill my weak spots</button>
      </div>
    </div>`;

  root.onclick = async (event) => {
    const btn = event.target.closest('[data-action]');
    if (!btn) return;
    if (btn.dataset.action === 'again') actions.startRound(btn.dataset.mode);
    if (btn.dataset.action === 'home') actions.goHome();
    if (btn.dataset.action === 'copy-challenge') {
      const field = root.querySelector('[data-challenge-code]');
      try {
        await navigator.clipboard.writeText(field.value);
        btn.textContent = 'Copied';
      } catch {
        field.select();
        btn.textContent = 'Press ⌘C';
      }
    }
  };
}
