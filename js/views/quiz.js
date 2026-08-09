// The quiz view. Owns its own round-local state (index, combo, timer) and
// reports each answer up through actions so persistent state stays in one place.

import { MODES, comboMultiplier, scoreAnswer } from '../engine.js';
import { difficultyDots, esc, escLines, sectionPill, table } from '../components/ui.js';

const LETTERS = ['A', 'B', 'C', 'D'];

export function renderQuiz(root, { round, actions }) {
  const mode = MODES[round.mode];
  const session = {
    index: 0,
    combo: 0,
    bestCombo: 0,
    xp: 0,
    correct: 0,
    answered: 0,
    picked: null, // index of the chosen choice, or null before answering
    results: [], // { question, correct, xpGained }
    startedAt: Date.now(),
    questionStart: Date.now(),
  };

  let ticker = null;

  const stopTicker = () => {
    if (ticker) {
      clearInterval(ticker);
      ticker = null;
    }
  };

  function timeLeft() {
    if (!round.timeLimitMs) return null;
    return Math.max(0, round.timeLimitMs - (Date.now() - session.questionStart));
  }

  function paint() {
    const q = round.questions[session.index];
    const answered = session.picked !== null;
    const total = round.questions.length;
    const progress = ((session.index + (answered ? 1 : 0)) / total) * 100;
    const remaining = timeLeft();
    const mult = comboMultiplier(session.combo + 1);

    root.innerHTML = `
      <div class="wrap wrap-quiz">
        <header class="quizbar">
          <button class="btn btn-quiet" data-action="quit">← Dashboard</button>
          <div class="quizbar-mid">
            <span class="quiz-mode">${mode.icon} ${esc(mode.name)}</span>
            <span class="quiz-count">Question ${session.index + 1} of ${total}</span>
          </div>
          <div class="quizbar-right">
            <span class="combo ${session.combo >= 2 ? 'is-hot' : ''}" title="Consecutive correct answers">
              <em>combo</em><strong>${session.combo}</strong>
              ${session.combo >= 1 ? `<span class="combo-mult">×${mult.toFixed(1)} next</span>` : ''}
            </span>
            <span class="xp-chip"><strong>${session.xp}</strong> XP this round</span>
          </div>
        </header>

        <div class="progress"><div class="progress-fill" style="width:${progress}%"></div></div>

        ${
          remaining !== null
            ? `<div class="timer ${remaining < 10000 ? 'is-urgent' : ''}">
                 <div class="timer-fill" style="width:${(remaining / round.timeLimitMs) * 100}%"></div>
                 <span>${(remaining / 1000).toFixed(1)}s</span>
               </div>`
            : ''
        }

        <section class="card question">
          <div class="q-meta">
            ${sectionPill(q.section)}
            <span class="q-domain">${esc(q.domain)} · ${esc(q.skill)}</span>
            ${difficultyDots(q.difficulty)}
          </div>

          ${q.passage ? `<div class="q-passage">${escLines(q.passage)}</div>` : ''}
          ${q.notes ? `<ul class="q-notes">${q.notes.map((n) => `<li>${esc(n)}</li>`).join('')}</ul>` : ''}
          ${q.table ? table(q.table) : ''}

          <p class="q-prompt">${escLines(q.prompt)}</p>

          <div class="choices" role="group">
            ${q.choices
              .map((choice, i) => {
                let cls = '';
                if (answered) {
                  if (i === q.answer) cls = 'is-correct';
                  else if (i === session.picked) cls = 'is-wrong';
                  else cls = 'is-dim';
                }
                return `<button class="choice ${cls}" data-action="pick" data-i="${i}" ${answered ? 'disabled' : ''}>
                    <span class="choice-letter">${LETTERS[i]}</span>
                    <span class="choice-text">${escLines(choice)}</span>
                  </button>`;
              })
              .join('')}
          </div>

          ${
            answered
              ? `<div class="feedback ${session.picked === q.answer ? 'is-good' : 'is-bad'}">
                   <div class="feedback-head">
                     <strong>${session.picked === q.answer ? 'Correct' : `Not quite — the answer is ${LETTERS[q.answer]}`}</strong>
                     ${
                       session.lastAward
                         ? `<span class="award">+${session.lastAward.total} XP${
                             session.lastAward.mult > 1 ? ` <em>×${session.lastAward.mult.toFixed(1)} combo</em>` : ''
                           }${session.lastAward.speed ? ` <em>+${session.lastAward.speed} speed</em>` : ''}</span>`
                         : '<span class="award award-zero">no XP</span>'
                     }
                   </div>
                   <p>${escLines(q.explanation)}</p>
                 </div>
                 <button class="btn btn-primary btn-block" data-action="next" autofocus>
                   ${session.index + 1 === total ? 'See results' : 'Next question'} <span class="kbd">↵</span>
                 </button>`
              : `<p class="hint">Pick an answer — or press <span class="kbd">1</span>–<span class="kbd">4</span>.</p>`
          }
        </section>
      </div>`;
  }

  function submit(choiceIndex) {
    if (session.picked !== null) return;
    const q = round.questions[session.index];
    const elapsedMs = Date.now() - session.questionStart;
    const correct = choiceIndex === q.answer;

    session.picked = choiceIndex;
    session.answered += 1;

    if (correct) {
      session.combo += 1;
      session.bestCombo = Math.max(session.bestCombo, session.combo);
      session.correct += 1;
      const award = scoreAnswer({
        question: q,
        combo: session.combo,
        timeLeftMs: Math.max(0, round.timeLimitMs - elapsedMs),
        timeLimitMs: round.timeLimitMs,
      });
      session.lastAward = award;
      session.xp += award.total;
    } else {
      session.combo = 0;
      session.lastAward = null;
    }

    const gained = correct ? session.lastAward.total : 0;
    session.results.push({ question: q, correct, xpGained: gained, elapsedMs });
    actions.recordAnswer({ question: q, correct, xpGained: gained, elapsedMs, timed: !!round.timeLimitMs });

    stopTicker();
    paint();
  }

  function advance() {
    if (session.index + 1 >= round.questions.length) {
      stopTicker();
      actions.finishRound({
        mode: round.mode,
        answered: session.answered,
        correct: session.correct,
        xp: session.xp,
        bestCombo: session.bestCombo,
        durationMs: Date.now() - session.startedAt,
        results: session.results,
      });
      return;
    }
    session.index += 1;
    session.picked = null;
    session.lastAward = null;
    session.questionStart = Date.now();
    paint();
    startTicker();
  }

  function startTicker() {
    stopTicker();
    if (!round.timeLimitMs) return;
    ticker = setInterval(() => {
      const remaining = timeLeft();
      const fill = root.querySelector('.timer-fill');
      const label = root.querySelector('.timer span');
      if (!fill || !label) return;
      fill.style.width = `${(remaining / round.timeLimitMs) * 100}%`;
      label.textContent = `${(remaining / 1000).toFixed(1)}s`;
      root.querySelector('.timer').classList.toggle('is-urgent', remaining < 10000);
      if (remaining <= 0) submit(-1); // time out counts as a miss
    }, 100);
  }

  root.onclick = (event) => {
    const btn = event.target.closest('[data-action]');
    if (!btn) return;
    const { action } = btn.dataset;
    if (action === 'pick') submit(Number(btn.dataset.i));
    else if (action === 'next') advance();
    else if (action === 'quit') {
      stopTicker();
      // A quit round still banks the answers already given.
      if (session.answered > 0) {
        actions.finishRound({
          mode: round.mode,
          answered: session.answered,
          correct: session.correct,
          xp: session.xp,
          bestCombo: session.bestCombo,
          durationMs: Date.now() - session.startedAt,
          results: session.results,
          abandoned: true,
        });
      } else {
        actions.goHome();
      }
    }
  };

  const onKey = (event) => {
    if (['1', '2', '3', '4'].includes(event.key)) {
      submit(Number(event.key) - 1);
    } else if (event.key === 'Enter' && session.picked !== null) {
      event.preventDefault();
      advance();
    }
  };
  document.addEventListener('keydown', onKey);

  // Called by the router before swapping views.
  actions.setCleanup(() => {
    stopTicker();
    document.removeEventListener('keydown', onKey);
    root.onclick = null;
  });

  paint();
  startTicker();
}
