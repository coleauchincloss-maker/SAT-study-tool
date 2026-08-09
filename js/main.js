// Router, and the single place persistent state is mutated.

import { bank, byId, loadBank, loadStatus, requestGeneration } from './bank.js';
import { applyAnswer, buildRound, finalizeRound, levelInfo, MODES } from './engine.js';
import * as net from './net.js';
import {
  judgeChallenge,
  makeChallengeCode,
  myLocation,
  myName,
  myPlayerId,
  overallRecord,
  readChallengeCode,
  recordMatch,
  setMyLocation,
  setMyName,
} from './rivals.js';
import { clearState, loadState, saveState } from './state.js';
import { cycleTheme, watchSystemTheme } from './theme.js';
import { announce } from './a11y.js';
import { renderDashboard } from './views/dashboard.js';
import { renderHome } from './views/home.js';
import { renderImport } from './views/import.js';
import { renderLeaderboard } from './views/leaderboard.js';
import { renderMatch } from './views/match.js';
import { renderQuiz } from './views/quiz.js';
import { renderResults } from './views/results.js';

const root = document.getElementById('app');

let state = loadState();
let route = { name: 'home' };
let cleanup = null;

/** Transient hub UI state — not persisted beyond the name. */
const lobby = {
  name: myName(),
  location: myLocation(),
  mode: 'buzzer',
  section: '',
  source: 'all',
  target: '',
  questionSeconds: '',
  focusMode: false,
  code: '',
  challenge: '',
  server: '',
  notice: '',
  noticeBad: false,
  genStatus: '',
  info: null,
  focusField: null,
};

/** Set while playing a challenge run, so results know what to compare. */
let challengeContext = null;

function say(message, bad = false) {
  lobby.notice = message;
  lobby.noticeBad = bad;
}

// ─────────────────────────── actions ───────────────────────────

const actions = {
  setCleanup(fn) {
    cleanup = fn;
  },

  setLobbyField(field, value) {
    lobby[field] = field === 'code' ? value.toUpperCase() : value;
    lobby.focusField = ['name', 'location', 'code', 'challenge', 'server'].includes(field) ? field : null;
    if (field === 'name') setMyName(value);
    if (field === 'location') setMyLocation(value);
    if (field === 'mode' || field === 'section' || field === 'focusMode') render();
  },

  /** Push current stats to the shared leaderboard. Best-effort: failures are silent. */
  submitLeaderboardStats() {
    const record = overallRecord();
    net.submitLeaderboard({
      playerId: myPlayerId(),
      name: lobby.name || myName() || 'Anonymous',
      location: lobby.location || myLocation() || '',
      xp: state.xp,
      level: levelInfo(state.xp).level,
      accuracy: state.totalAnswered ? state.totalCorrect / state.totalAnswered : 0,
      totalAnswered: state.totalAnswered,
      wins: record.wins,
      bestCombo: state.bestCombo,
      badgeCount: state.badges.length,
    });
  },

  // ── live matches ──
  async createMatch() {
    say('');
    try {
      await net.createMatch({
        name: lobby.name || myName() || 'You',
        mode: lobby.mode,
        section: lobby.section || null,
        source: lobby.source || 'all',
        target: lobby.target === '' ? null : Number(lobby.target),
        questionSeconds: lobby.questionSeconds === '' ? null : Number(lobby.questionSeconds),
        focusMode: !!lobby.focusMode,
      });
      route = { name: 'match' };
      render();
    } catch (error) {
      say(error.message, true);
      render();
    }
  },

  async joinMatch(code = lobby.code) {
    say('');
    if (!code?.trim()) {
      say('Enter the four-character room code.', true);
      return render();
    }
    try {
      await net.joinMatch({ code, name: lobby.name || myName() || 'You' });
      route = { name: 'match' };
      render();
    } catch (error) {
      say(error.message, true);
      render();
    }
  },

  setServer() {
    net.setServerBase(lobby.server);
    say(lobby.server ? `Using ${net.serverBase()}` : 'Using this page’s own server.');
    refreshLobbyInfo().then(render);
  },

  leaveMatch() {
    net.forgetSession();
    route = { name: 'home' };
    render();
  },

  /**
   * A match ended: bank the XP, update the head-to-head record, and hand back a
   * line for the UI. Called once per match by the match view.
   */
  matchFinished(snapshot) {
    const you = snapshot.players.find((p) => p.id === snapshot.you);
    const them = snapshot.players.find((p) => p.id !== snapshot.you);
    if (!you) return '';

    // Feed each of your answers into the skill stats, so "what to work on" still
    // reflects real play even though nothing here is a study session.
    let xp = 0;
    let correct = 0;
    let streak = 0;
    let bestStreak = 0;

    for (const entry of snapshot.log ?? []) {
      const answered = entry.answers?.[snapshot.you];
      if (!answered) {
        streak = 0;
        continue;
      }
      const question =
        byId(entry.questionId) ?? {
          id: entry.questionId,
          section: (entry.domain && bankSectionOf(entry.domain)) || 'math',
          domain: entry.domain,
          skill: entry.skill,
          difficulty: entry.difficulty ?? 2,
        };
      const gained = answered.correct ? 10 + 5 * ((question.difficulty ?? 2) - 1) : 0;
      xp += gained;
      correct += answered.correct ? 1 : 0;
      streak = answered.correct ? streak + 1 : 0;
      bestStreak = Math.max(bestStreak, streak);

      state = applyAnswer(state, {
        question,
        correct: answered.correct,
        xpGained: gained,
        elapsedMs: answered.atMs ?? 0,
        timed: true,
      });
    }

    const result = !snapshot.winnerPid ? 'draw' : snapshot.winnerPid === snapshot.you ? 'win' : 'loss';
    if (result === 'win') xp += 25;

    // Record the match first so badges that read the head-to-head record
    // (e.g. "win your first duel") see this result, not the prior one.
    const record = recordMatch({
      opponent: them?.name ?? 'Opponent',
      result,
      myScore: you.score,
      theirScore: them?.score ?? 0,
      mode: snapshot.modeLabel,
    });

    const levelBefore = levelInfo(state.xp).level;
    state = { ...state, xp: state.xp + (result === 'win' ? 25 : 0) };
    const { state: next, newBadges } = finalizeRound(state, {
      mode: snapshot.mode,
      answered: snapshot.log?.length ?? 0,
      correct,
      xp,
      bestCombo: bestStreak,
      durationMs: 0,
      results: [],
    });
    state = next;
    saveState(state);
    this.submitLeaderboardStats();
    const levelAfter = levelInfo(state.xp).level;

    const tally = `${record.wins}–${record.losses}${record.draws ? `–${record.draws}` : ''}`;
    const levelUp = levelAfter > levelBefore ? ` Level ${levelAfter}!` : '';
    const badgeNote = newBadges.length ? ` New badge${newBadges.length > 1 ? 's' : ''}: ${newBadges.map((b) => b.name).join(', ')}!` : '';
    return `+${xp} XP. You're now ${tally} against ${record.name}.${levelUp}${badgeNote}`;
  },

  // ── challenge codes ──
  sendChallenge() {
    const round = buildRound('challenge', state);
    if (round.questions.length < 4) {
      say('Not enough questions in the bank for a challenge run.', true);
      return render();
    }
    challengeContext = { kind: 'send' };
    route = { name: 'quiz', round };
    render();
  },

  acceptChallenge() {
    say('');
    let challenge;
    try {
      challenge = readChallengeCode(lobby.challenge);
    } catch (error) {
      say(error.message, true);
      return render();
    }

    const questions = challenge.questionIds.map((id) => byId(id)).filter(Boolean);
    if (questions.length !== challenge.questionIds.length) {
      const missing = challenge.questionIds.length - questions.length;
      say(
        `${missing} of their ${challenge.questionIds.length} questions aren't in your bank — ` +
          `ask them to share data/generated.json, or generate more.`,
        true,
      );
      return render();
    }

    challengeContext = { kind: 'accept', challenge };
    route = { name: 'quiz', round: { mode: 'challenge', timeLimitMs: MODES.challenge.timeLimitMs, questions } };
    render();
  },

  // ── solo practice (secondary) ──
  startRound(modeId) {
    challengeContext = null;
    route = { name: 'quiz', round: buildRound(modeId, state) };
    render();
  },

  recordAnswer(payload) {
    state = applyAnswer(state, payload);
    saveState(state);
  },

  finishRound(session) {
    const levelBefore = levelInfo(state.xp).level;
    const { state: next, newBadges } = finalizeRound(state, session);
    state = next;
    saveState(state);
    this.submitLeaderboardStats();
    const levelAfter = levelInfo(state.xp).level;

    // A challenge run turns into a code to send, or a verdict against theirs.
    let challenge = null;
    if (challengeContext?.kind === 'send') {
      challenge = {
        kind: 'send',
        code: makeChallengeCode({
          name: lobby.name || myName() || 'A friend',
          section: lobby.section || null,
          results: session.results,
        }),
      };
    } else if (challengeContext?.kind === 'accept') {
      const verdict = judgeChallenge(challengeContext.challenge, session.results);
      const record = recordMatch({
        opponent: challengeContext.challenge.name,
        result: verdict.result,
        myScore: verdict.myCorrect,
        theirScore: challengeContext.challenge.theirCorrect,
        mode: 'Challenge code',
      });
      challenge = {
        kind: 'accept',
        verdict,
        them: challengeContext.challenge,
        tally: `${record.wins}–${record.losses}${record.draws ? `–${record.draws}` : ''}`,
      };
    }
    challengeContext = null;

    route = {
      name: 'results',
      summary: { session, newBadges, leveledTo: levelAfter > levelBefore ? levelAfter : null, challenge },
    };
    render();
  },

  // ── generation ──
  async generate(count) {
    lobby.genStatus = `Generating ${count}… this takes a minute.`;
    render();
    try {
      const report = await requestGeneration({ count, section: lobby.section || null });
      const dropped = report.rejected?.length ?? 0;
      lobby.genStatus =
        `Added ${report.accepted} question(s); bank is now ${bank.all.length}.` +
        (dropped ? ` ${dropped} rejected by the answer-key check.` : '');
    } catch (error) {
      lobby.genStatus = `Generation failed: ${error.message}`;
    }
    render();
  },

  showCard() {
    route = { name: 'dashboard' };
    render();
  },

  navigate(name) {
    route = { name: name || 'home' };
    render();
  },

  cycleTheme() {
    const { preference, resolved } = cycleTheme();
    announce(`Appearance set to ${preference}${preference === 'system' ? `, currently ${resolved}` : ''}.`);
    render();
  },

  goHome() {
    route = { name: 'home' };
    render();
  },

  hardReset() {
    if (!window.confirm('Erase XP, badges, skill history and rival records in this browser?')) return;
    state = clearState();
    try {
      localStorage.removeItem('satquest.rivals');
    } catch {
      /* ignore */
    }
    actions.goHome();
  },
};

/** Map a domain back to its section for questions not in this browser's bank. */
function bankSectionOf(domain) {
  const mathDomains = ['Algebra', 'Advanced Math', 'Problem-Solving & Data', 'Geometry & Trig'];
  return mathDomains.includes(domain) ? 'math' : 'rw';
}

// ─────────────────────────── render ───────────────────────────

function render() {
  if (cleanup) {
    cleanup();
    cleanup = null;
  }
  root.onclick = null;
  root.oninput = null;
  root.onchange = null;
  window.scrollTo({ top: 0 });

  const previous = route.name;
  if (route.name === 'match') renderMatch(root, { actions });
  else if (route.name === 'quiz') renderQuiz(root, { state, actions, round: route.round });
  else if (route.name === 'results') renderResults(root, { state, actions, summary: route.summary });
  else if (route.name === 'dashboard') renderDashboard(root, { state, actions, lobby });
  else if (route.name === 'leaderboard') renderLeaderboard(root, { state, actions, lobby });
  else if (route.name === 'import') renderImport(root, { actions, lobby });
  else renderHome(root, { state, actions, lobby });

  // A view swap replaces everything under <main> without moving focus, which
  // strands keyboard and screen-reader users at the top of the document. Send
  // focus to the new view unless the user is mid-typing in a field we re-rendered.
  if (!lobby.focusField && previous !== route.name) {
    root.focus({ preventScroll: true });
  }

  lobby.focusField = null;
}

async function refreshLobbyInfo() {
  const [info] = await Promise.all([net.matchInfo(), loadStatus()]);
  lobby.info = info;
  if (info?.modes && !info.modes[lobby.mode]) lobby.mode = Object.keys(info.modes)[0];
  return info;
}

async function boot() {
  watchSystemTheme(render);
  root.innerHTML = '<div class="wrap"><section class="card"><h2>Loading…</h2></section></div>';
  await loadBank();
  await refreshLobbyInfo();

  // An invite link drops you straight into the join flow.
  const invited = /[#&?]join=([A-Z0-9]{4})/i.exec(location.hash);
  if (invited) {
    lobby.code = invited[1].toUpperCase();
    history.replaceState(null, '', location.pathname);
    render();
    if (lobby.name) return actions.joinMatch(lobby.code);
    say('Enter your name, then join.');
    return render();
  }

  // Rejoin a match this browser was already in (a refresh shouldn't forfeit).
  const remembered = net.rememberedSession();
  if (remembered) {
    try {
      const resumed = await net.resumeMatch(remembered);
      if (resumed.phase !== 'over') {
        route = { name: 'match' };
        return render();
      }
      net.forgetSession();
    } catch {
      net.forgetSession();
    }
  }

  render();
}

boot();
