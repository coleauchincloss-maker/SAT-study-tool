// The live 1v1 screen. Renders whatever phase the server says the room is in and
// sends intents back; it never decides scores or timing itself.

import { createCalculator } from '../components/calculator.js';
import { referenceSheet } from '../components/reference.js';
import { difficultyDots, esc, escLines, table } from '../components/ui.js';
import { connect, disconnect, matchInfo, remaining, sendAction, session } from '../net.js';
import { announce } from '../a11y.js';

const LETTERS = ['A', 'B', 'C', 'D'];

export function renderMatch(root, { actions }) {
  let panel = null; // 'calc' | 'ref' | null
  let calculator = null;
  let pending = null; // choice we've sent but haven't seen confirmed
  let notice = '';
  let reported = false; // rivalry record written for this match
  let clockTimer = null;
  let serverInfo = null; // reachability, for the waiting-room instructions

  const me = (state) => state?.players.find((p) => p.id === state.you) ?? null;
  const them = (state) => state?.players.find((p) => p.id !== state.you) ?? null;

  // ─────────────────────────── chrome ───────────────────────────

  function scoreboard(state) {
    const you = me(state);
    const foe = them(state);
    const target = state.target;

    const card = (player, isYou) => {
      if (!player) {
        return `<div class="vs-card is-empty"><span class="vs-name">Waiting…</span><span class="vs-score">–</span></div>`;
      }
      const turn = state.turnPid === player.id && ['question', 'steal', 'draft'].includes(state.phase);
      const distractions = state.focusMode ? (state.distractions?.[player.id] ?? 0) : 0;
      return `
        <div class="vs-card ${isYou ? 'is-you' : ''} ${turn ? 'is-turn' : ''} ${player.connected ? '' : 'is-away'}">
          <span class="vs-name">
            ${esc(player.name)}${isYou ? ' <em>you</em>' : ''}
            ${player.connected ? '' : '<span class="vs-away" title="Disconnected">⚠</span>'}
            ${distractions > 0 ? `<span class="distraction-badge" title="Left the tab or exited fullscreen ${distractions} time(s)">👀 ${distractions}</span>` : ''}
          </span>
          <span class="vs-score">${player.score}</span>
          <span class="vs-meta">
            ${player.streak >= 2 ? `<span class="vs-streak">🔥${player.streak}</span>` : ''}
            ${player.hasAnswered && state.phase === 'question' ? '<span class="vs-tag">answered</span>' : ''}
            ${player.lockedOut && state.phase !== 'reveal' ? '<span class="vs-tag is-bad">locked out</span>' : ''}
            ${player.wagerLocked && state.phase === 'wager' ? '<span class="vs-tag">bet in</span>' : ''}
          </span>
        </div>`;
    };

    return `
      <header class="vs-head">
        ${card(you, true)}
        <div class="vs-mid">
          <span class="vs-mode">${esc(state.modeLabel)}</span>
          <span class="vs-round">
            ${{ over: 'Final', lobby: 'Lobby', draft: 'Drafting' }[state.phase] ?? `Round ${state.round || 1}`}
            ${target && state.phase !== 'draft' ? ` · first to ${target}` : ''}
          </span>
          <span class="vs-code">${esc(state.code)}</span>
          ${state.focusMode
            ? `<button type="button" class="btn btn-quiet btn-sm vs-focus-btn" data-action="fullscreen">
                 ${document.fullscreenElement ? '⛶ Exit fullscreen' : '⛶ Enter fullscreen'}
               </button>`
            : ''}
        </div>
        ${card(foe, false)}
      </header>`;
  }

  function clockTotal(state) {
    if (['question', 'steal'].includes(state.phase) && state.questionSeconds) return state.questionSeconds;
    return state.phase === 'wager' ? 15 : state.phase === 'draft' ? 20 : state.phase === 'steal' ? 12 : 30;
  }

  function clockBar(state) {
    const seconds = remaining(state);
    if (seconds === null) return '';
    const total = clockTotal(state);
    const pct = Math.max(0, Math.min(100, (seconds / total) * 100));
    return `
      <div class="vs-clock ${seconds < 6 ? 'is-urgent' : ''}">
        <div class="vs-clock-fill" style="width:${pct}%"></div>
        <span>${seconds.toFixed(1)}s</span>
      </div>`;
  }

  function questionBody(state, { locked }) {
    const question = state.question;
    if (!question?.choices) return '';
    const you = me(state);
    const revealing = state.phase === 'reveal';
    const yourChoice = you?.choice ?? pending;

    const choices = question.choices
      .map((choice, index) => {
        let cls = '';
        if (revealing) {
          if (index === question.answer) cls = 'is-correct';
          else if (index === yourChoice) cls = 'is-wrong';
          else cls = 'is-dim';
        } else if (index === yourChoice) {
          cls = 'is-picked';
        }
        return `
          <button class="choice ${cls}" data-action="answer" data-i="${index}" ${locked || revealing ? 'disabled' : ''}>
            <span class="choice-letter">${LETTERS[index]}</span>
            <span class="choice-text">${escLines(choice)}</span>
          </button>`;
      })
      .join('');

    return `
      <section class="card question vs-question">
        <div class="q-meta">
          <span class="pill pill-${question.section}">${question.section === 'math' ? 'Math' : 'Reading & Writing'}</span>
          <span class="q-domain">${esc(question.domain)} · ${esc(question.skill)}</span>
          ${difficultyDots(question.difficulty)}
        </div>
        ${question.passage ? `<div class="q-passage">${escLines(question.passage)}</div>` : ''}
        ${question.notes?.length ? `<ul class="q-notes">${question.notes.map((n) => `<li>${esc(n)}</li>`).join('')}</ul>` : ''}
        ${question.table?.headers?.length ? table(question.table) : ''}
        <p class="q-prompt">${escLines(question.prompt)}</p>
        <div class="choices">${choices}</div>
        ${notice ? `<p class="vs-notice">${esc(notice)}</p>` : ''}
      </section>`;
  }

  function mathTools(state) {
    if (state.question?.section !== 'math') return '';
    return `
      <div class="vs-tools">
        <button class="btn btn-ghost btn-sm ${panel === 'ref' ? 'is-on' : ''}" data-action="panel" data-panel="ref">
          Reference
        </button>
        <button class="btn btn-ghost btn-sm ${panel === 'calc' ? 'is-on' : ''}" data-action="panel" data-panel="calc">
          Calculator
        </button>
      </div>`;
  }

  function panelMarkup() {
    if (!panel) return '';
    return `
      <aside class="vs-panel">
        <header>
          <strong>${panel === 'calc' ? 'Graphing calculator' : 'Reference sheet'}</strong>
          <button class="btn btn-quiet btn-sm" data-action="panel" data-panel="">Close</button>
        </header>
        <div class="vs-panel-body" id="panel-body">${panel === 'ref' ? referenceSheet() : ''}</div>
      </aside>`;
  }

  // ─────────────────────────── phases ───────────────────────────

  function lobby(state) {
    const you = me(state);
    const foe = them(state);
    // The host usually has the app open on localhost, but a localhost link is
    // useless to anyone else — on their phone it points at their own device.
    // Share the LAN address the server reported instead.
    const onLoopback = /^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname);
    const base =
      onLoopback && serverInfo?.lanUrl
        ? serverInfo.lanUrl.replace(/\/+$/, '/')
        : `${location.origin}${location.pathname}`;
    const shareUrl = `${base}#join=${state.code}`;
    const shareIsLocal = onLoopback && !serverInfo?.lanUrl;

    // With one player the match cannot start, and a greyed-out ready button is
    // not an explanation. Spell out exactly what the other person has to do.
    const waiting = !foe
      ? `<div class="vs-howto">
           <strong>Waiting for a second player</strong>
           <p>The match can't start until someone else is in this room.</p>
           ${
             serverInfo?.lanBound === false
               ? `<p class="vs-howto-bad">
                    This server is only reachable from this computer, so nobody can join.
                    Restart it with <code>python3 server.py --lan</code>.
                  </p>`
               : `<ol>
                    <li>Same Wi-Fi as this computer.</li>
                    ${serverInfo?.lanUrl ? `<li>They open <strong>${esc(serverInfo.lanUrl)}</strong></li>` : ''}
                    <li>They enter code <strong>${esc(state.code)}</strong> and press Join.</li>
                  </ol>`
           }
         </div>`
      : '';

    return `
      <section class="card vs-lobby">
        <span class="eyebrow">Room code</span>
        <div class="vs-bigcode">${esc(state.code)}</div>
        <p class="card-sub">
          ${foe
            ? `${esc(foe.name)} is in. Both of you hit ready.`
            : 'Give this code to your opponent, or send them the link below.'}
        </p>
        ${waiting}
        ${state.focusMode
          ? `<p class="vs-howto-note">
               <strong>Focus Mode is on.</strong> Leaving this tab or exiting fullscreen during a question
               gets flagged to both players — it can't be blocked, only reported.
             </p>`
          : ''}
        <div class="vs-share">
          <input type="text" readonly value="${esc(shareUrl)}" data-share aria-label="Invite link" />
          <button type="button" class="btn btn-ghost btn-sm" data-action="copy">Copy</button>
        </div>
        ${
          shareIsLocal
            ? `<p class="vs-notice is-bad">
                 This link only works on this computer. Restart the server with
                 <code>--lan</code> to get one you can send.
               </p>`
            : '<p class="vs-share-note">Text this link to your opponent — it drops them straight into this room.</p>'
        }
        <div class="vs-lobby-players">
          ${[you, foe]
            .map((player) =>
              player
                ? `<div class="vs-seat ${player.ready ? 'is-ready' : ''}">
                     <strong>${esc(player.name)}</strong>
                     <span>${player.ready ? 'Ready' : 'Not ready'}</span>
                   </div>`
                : `<div class="vs-seat is-empty"><strong>Empty seat</strong><span>waiting for a player</span></div>`,
            )
            .join('')}
        </div>
        <button class="btn btn-primary btn-block" data-action="ready" ${!foe || you?.ready ? 'disabled' : ''}>
          ${!foe ? 'Waiting for a second player…' : you?.ready ? 'Ready — waiting for them…' : "I'm ready"}
        </button>
        <button class="btn btn-quiet btn-block" data-action="leave">Leave</button>
      </section>`;
  }

  function countdown(state) {
    const seconds = remaining(state);
    const count = seconds === null ? '' : Math.max(1, Math.ceil(seconds));
    return `
      <section class="card vs-countdown">
        <span class="eyebrow">${esc(state.modeLabel)}</span>
        <div class="vs-count">${count}</div>
        <p>${state.round ? 'Next question' : 'First question'} coming up</p>
      </section>`;
  }

  function draft(state) {
    const mine = state.turnPid === state.you;
    const you = me(state);
    const foe = them(state);
    return `
      <section class="card vs-draft">
        <span class="eyebrow">Category draft</span>
        <h2>${mine ? 'Your pick' : `${esc(foe?.name ?? 'Opponent')} is picking…`}</h2>
        <p class="card-sub">
          Claim a domain by winning ${state.flagsToClaim} questions in it. Most domains takes the match.
        </p>
        <div class="vs-domains">
          ${state.draftPool
            .map(
              (domain) => `
              <button class="vs-domain" data-action="pick" data-domain="${esc(domain)}" ${mine ? '' : 'disabled'}>
                ${esc(domain)}
              </button>`,
            )
            .join('') || '<p class="empty">No domains left to draft.</p>'}
        </div>
        <div class="vs-draft-teams">
          ${[you, foe]
            .map(
              (player) => `
              <div class="vs-team">
                <strong>${esc(player?.name ?? '—')}</strong>
                ${(player?.domains ?? []).map((d) => `<span>${esc(d)}</span>`).join('') || '<em>no picks yet</em>'}
              </div>`,
            )
            .join('')}
        </div>
      </section>`;
  }

  function wager(state) {
    const you = me(state);
    const foe = them(state);
    const max = state.maxWager ?? 3;
    const chips = Array.from({ length: max }, (_, i) => i + 1)
      .map(
        (amount) => `
        <button class="vs-chip ${you?.wager === amount ? 'is-on' : ''}" data-action="wager" data-amount="${amount}"
          ${you?.wagerLocked ? 'disabled' : ''}>
          ${amount}
        </button>`,
      )
      .join('');

    return `
      <section class="card vs-wager">
        <span class="eyebrow">Place your bet</span>
        <h2>${esc(state.question?.domain ?? 'Unknown domain')}</h2>
        <p class="card-sub">
          Difficulty ${state.question?.difficulty ?? '?'} of 3. Answer first and you win your bet;
          answer wrong and you lose it.
        </p>
        <div class="vs-chips">${chips}</div>
        <p class="vs-notice">
          ${you?.wagerLocked ? 'Bet locked in.' : 'Pick an amount before the clock runs out (defaults to 1).'}
          ${foe?.wagerLocked ? ` ${esc(foe.name)} has bet.` : ''}
        </p>
      </section>`;
  }

  function question(state) {
    const you = me(state);
    const foe = them(state);
    const stealing = state.phase === 'steal';
    const yourTurn = state.turnPid === state.you;
    const ownsQuestion = state.mode !== 'steal' || yourTurn;
    const locked = Boolean(you?.hasAnswered) || Boolean(you?.lockedOut) || pending !== null || (stealing && !yourTurn) || !ownsQuestion;

    let banner = '';
    if (stealing) {
      banner = yourTurn
        ? `<div class="vs-banner is-steal">Steal it — ${esc(foe?.name ?? 'they')} missed.</div>`
        : `<div class="vs-banner is-warn">${esc(foe?.name ?? 'Opponent')} is trying to steal.</div>`;
    } else if (state.mode === 'steal') {
      banner = yourTurn
        ? '<div class="vs-banner">Your question.</div>'
        : `<div class="vs-banner is-warn">${esc(foe?.name ?? 'Opponent')}'s question — you get it if they miss.</div>`;
    } else if (you?.lockedOut) {
      banner = '<div class="vs-banner is-bad">Wrong — you are locked out of this one.</div>';
    } else if (you?.hasAnswered) {
      banner = '<div class="vs-banner is-good">Answer in. Waiting…</div>';
    }

    return `${banner}${mathTools(state)}${questionBody(state, { locked })}`;
  }

  function reveal(state) {
    const you = me(state);
    const foe = them(state);
    const winner = state.outcome?.winnerPid;
    const deltas = state.outcome?.deltas ?? {};
    const headline = !winner
      ? 'Nobody got it'
      : winner === state.you
        ? 'You took the point'
        : `${foe?.name ?? 'Opponent'} took it`;

    const delta = (player) => {
      const value = deltas[player?.id];
      if (!value) return '';
      return `<span class="vs-delta ${value > 0 ? 'is-up' : 'is-down'}">${value > 0 ? '+' : ''}${value}</span>`;
    };

    return `
      <div class="vs-banner ${!winner ? '' : winner === state.you ? 'is-good' : 'is-bad'}">
        <strong>${esc(headline)}</strong>
        ${delta(you)}${delta(foe)}
        ${state.outcome?.claimed ? `<em>${esc(state.outcome.claimed)} claimed</em>` : ''}
      </div>
      ${questionBody(state, { locked: true })}
      ${state.question?.explanation ? `<div class="card vs-explain"><p>${escLines(state.question.explanation)}</p></div>` : ''}
      ${state.hostPid === state.you ? '<button class="btn btn-ghost btn-block btn-sm" data-action="skip">Skip ahead</button>' : ''}`;
  }

  function over(state) {
    const you = me(state);
    const foe = them(state);
    const draw = !state.winnerPid;
    const won = state.winnerPid === state.you;

    const rows = state.log
      .map((entry) => {
        const mine = entry.answers?.[state.you];
        const theirs = foe ? entry.answers?.[foe.id] : null;
        const mark = (answer) =>
          !answer ? '<span class="rl-none">—</span>'
            : answer.correct
              ? `<span class="rl-ok">✓ ${(answer.atMs / 1000).toFixed(1)}s</span>`
              : '<span class="rl-no">✗</span>';
        return `
          <li>
            <span class="rl-round">${entry.round}</span>
            <span class="rl-skill">${esc(entry.skill)}</span>
            <span class="rl-cell">${mark(mine)}</span>
            <span class="rl-cell">${mark(theirs)}</span>
          </li>`;
      })
      .join('');

    return `
      <section class="card vs-over ${draw ? '' : won ? 'is-win' : 'is-loss'}">
        <span class="eyebrow">${esc(state.modeLabel)} · ${esc(state.sectionLabel)}</span>
        <h1>${draw ? 'Dead even' : won ? 'You win' : `${esc(foe?.name ?? 'Opponent')} wins`}</h1>
        <div class="vs-final">
          <div><strong>${you?.score ?? 0}</strong><span>${esc(you?.name ?? 'You')}</span></div>
          <em>–</em>
          <div><strong>${foe?.score ?? 0}</strong><span>${esc(foe?.name ?? 'Opponent')}</span></div>
        </div>
        <p class="card-sub">
          ${you?.correct ?? 0} correct for you, ${foe?.correct ?? 0} for them${
            you?.fastestMs ? ` · your fastest was ${(you.fastestMs / 1000).toFixed(1)}s` : ''
          }.
        </p>
        ${notice ? `<p class="vs-record">${esc(notice)}</p>` : ''}
      </section>

      ${rows
        ? `<section class="card">
             <h2>Round by round</h2>
             <ol class="round-log">
               <li class="rl-head">
                 <span class="rl-round">#</span><span class="rl-skill">Skill</span>
                 <span class="rl-cell">${esc(you?.name ?? 'You')}</span>
                 <span class="rl-cell">${esc(foe?.name ?? 'Them')}</span>
               </li>
               ${rows}
             </ol>
           </section>`
        : ''}

      <div class="results-actions">
        <button class="btn btn-primary" data-action="rematch" ${you?.ready ? 'disabled' : ''}>
          ${you?.ready ? 'Waiting for them…' : 'Run it back'}
        </button>
        <button class="btn btn-quiet" data-action="leave">Back to lobby</button>
      </div>`;
  }

  // ─────────────────────────── announcements ───────────────────────────

  let spoken = '';

  /** Say what just changed. Keyed so the same event isn't repeated on re-render. */
  function speakPhase(state) {
    const you = me(state);
    const foe = them(state);
    const key = `${state.phase}:${state.round}:${state.winnerPid ?? ''}:${foe?.id ?? ''}`;
    if (key === spoken) return;
    spoken = key;

    let message = '';
    if (state.phase === 'lobby') {
      message = foe ? `${foe.name} joined. Press ready when you are.` : `Room ${state.code.split('').join(' ')}. Waiting for a second player.`;
    } else if (state.phase === 'question' || state.phase === 'steal') {
      const q = state.question;
      const own = state.mode === 'steal' && state.turnPid !== state.you;
      message =
        state.phase === 'steal'
          ? state.turnPid === state.you
            ? 'Steal chance. Your answer.'
            : 'Your opponent is stealing.'
          : `Round ${state.round}. ${q?.domain ?? ''} question.${own ? " Your opponent's question." : ' Press 1 to 4 to answer.'}`;
    } else if (state.phase === 'wager') {
      message = `Place your bet. ${state.question?.domain ?? ''}, difficulty ${state.question?.difficulty ?? ''} of 3.`;
    } else if (state.phase === 'draft') {
      message = state.turnPid === state.you ? 'Your pick. Choose a domain.' : 'Your opponent is picking.';
    } else if (state.phase === 'reveal') {
      const winner = state.outcome?.winnerPid;
      const answer = state.question ? LETTERS[state.question.answer] : '';
      const who = !winner ? 'Nobody scored' : winner === state.you ? 'You took the point' : `${foe?.name ?? 'Opponent'} took the point`;
      message = `${who}. The answer was ${answer}. Score: you ${you?.score ?? 0}, ${foe?.name ?? 'opponent'} ${foe?.score ?? 0}.`;
    } else if (state.phase === 'over') {
      const result = !state.winnerPid ? 'Draw' : state.winnerPid === state.you ? 'You win' : `${foe?.name ?? 'Opponent'} wins`;
      message = `Match over. ${result}, ${you?.score ?? 0} to ${foe?.score ?? 0}.`;
    }
    announce(message);
  }

  // ─────────────────────────── paint ───────────────────────────

  function paint() {
    const state = session.state;
    if (!state) {
      root.innerHTML = `
        <div class="wrap wrap-quiz">
          <section class="card">
            <h2>Connecting…</h2>
            <p class="card-sub">${esc(session.error ?? 'Waiting for the match server.')}</p>
            <button class="btn btn-quiet btn-block" data-action="leave">Back to lobby</button>
          </section>
        </div>`;
      return;
    }

    // Once the server says a choice landed, stop showing the optimistic one.
    if (pending !== null && me(state)?.hasAnswered) pending = null;

    if (state.phase === 'over' && !reported) {
      reported = true;
      notice = actions.matchFinished(state) ?? '';
    }
    if (state.phase !== 'over') reported = false;

    speakPhase(state);

    const body =
      {
        lobby: lobby,
        countdown: countdown,
        draft: draft,
        wager: wager,
        question: question,
        steal: question,
        reveal: reveal,
        over: over,
      }[state.phase]?.(state) ?? '';

    root.innerHTML = `
      <div class="wrap wrap-quiz vs-wrap">
        ${scoreboard(state)}
        ${clockBar(state)}
        ${session.link === 'dropped' ? '<div class="vs-banner is-warn">Connection lost — reconnecting…</div>' : ''}
        <div class="vs-stage ${panel ? 'has-panel' : ''}">
          <div class="vs-main">${body}</div>
          ${panelMarkup()}
        </div>
      </div>`;

    if (panel === 'calc') {
      const host = root.querySelector('#panel-body');
      if (host) calculator = createCalculator(host);
    } else if (calculator) {
      calculator.destroy();
      calculator = null;
    }
  }

  /** Update just the clock text between state changes. */
  function tickClock() {
    const state = session.state;
    const seconds = remaining(state);
    const bar = root.querySelector('.vs-clock');
    if (!bar || seconds === null) return;
    const total = clockTotal(state);
    bar.querySelector('.vs-clock-fill').style.width = `${Math.max(0, Math.min(100, (seconds / total) * 100))}%`;
    bar.querySelector('span').textContent = `${seconds.toFixed(1)}s`;
    bar.classList.toggle('is-urgent', seconds < 6);
    const count = root.querySelector('.vs-count');
    if (count) count.textContent = String(Math.max(1, Math.ceil(seconds)));
  }

  // ─────────────────────────── intents ───────────────────────────

  async function send(type, payload) {
    try {
      notice = '';
      await sendAction(type, payload);
    } catch (error) {
      notice = error.message;
      if (type === 'answer') pending = null;
      paint();
    }
  }

  root.onclick = async (event) => {
    const button = event.target.closest('[data-action]');
    if (!button) return;
    const { action } = button.dataset;

    if (action === 'panel') {
      panel = button.dataset.panel || null;
      paint();
    } else if (action === 'fullscreen') {
      if (document.fullscreenElement) {
        document.exitFullscreen?.().catch(() => {});
      } else {
        document.documentElement.requestFullscreen?.().catch(() => {});
      }
    } else if (action === 'copy') {
      const field = root.querySelector('[data-share]');
      try {
        await navigator.clipboard.writeText(field.value);
        notice = 'Invite link copied.';
      } catch {
        field.select();
        notice = 'Press ⌘C to copy the link.';
      }
      paint();
    } else if (action === 'answer') {
      pending = Number(button.dataset.i);
      paint();
      send('answer', { choice: pending });
    } else if (action === 'wager') {
      send('wager', { amount: Number(button.dataset.amount) });
    } else if (action === 'pick') {
      send('pick', { domain: button.dataset.domain });
    } else if (action === 'ready') {
      send('ready', {});
    } else if (action === 'rematch') {
      reported = false;
      notice = '';
      send('rematch', {});
    } else if (action === 'skip') {
      send('skip', {});
    } else if (action === 'leave') {
      await send('leave', {});
      actions.leaveMatch();
    }
  };

  const onKey = (event) => {
    const state = session.state;
    if (!state) return;
    if (['question', 'steal'].includes(state.phase) && ['1', '2', '3', '4'].includes(event.key)) {
      const index = Number(event.key) - 1;
      const button = root.querySelector(`.choice[data-i="${index}"]:not([disabled])`);
      if (button) button.click();
    } else if (state.phase === 'wager' && ['1', '2', '3'].includes(event.key)) {
      root.querySelector(`.vs-chip[data-amount="${event.key}"]:not([disabled])`)?.click();
    } else if (state.phase === 'lobby' && event.key === 'Enter') {
      root.querySelector('[data-action="ready"]:not([disabled])')?.click();
    }
  };

  // ─────────────────────────── focus mode ───────────────────────────
  // Detection, not prevention: a browser cannot block tab-switching or a
  // second device. This just makes a lapse visible to both players live,
  // instead of relying on the honor system during an active question.

  const activePhase = () => ['question', 'steal', 'wager'].includes(session.state?.phase);

  const onVisibility = () => {
    if (document.hidden && session.state?.focusMode && activePhase()) send('distract', {});
  };

  let wasFullscreen = Boolean(document.fullscreenElement);
  const onFullscreenChange = () => {
    const isFullscreen = Boolean(document.fullscreenElement);
    if (!isFullscreen && wasFullscreen && session.state?.focusMode && activePhase()) send('distract', {});
    wasFullscreen = isFullscreen;
    paint();
  };

  document.addEventListener('visibilitychange', onVisibility);
  document.addEventListener('fullscreenchange', onFullscreenChange);

  document.addEventListener('keydown', onKey);
  matchInfo().then((info) => {
    serverInfo = info;
    if (session.state?.phase === 'lobby') paint();
  });
  connect(() => paint());
  clockTimer = setInterval(tickClock, 100);
  paint();

  actions.setCleanup(() => {
    clearInterval(clockTimer);
    document.removeEventListener('keydown', onKey);
    document.removeEventListener('visibilitychange', onVisibility);
    document.removeEventListener('fullscreenchange', onFullscreenChange);
    calculator?.destroy();
    disconnect();
    root.onclick = null;
  });
}
