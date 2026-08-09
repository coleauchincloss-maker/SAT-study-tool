// Game rules: XP, levels, combos, streaks, badges, weak-spot detection and
// round construction. Pure functions over state — no DOM, no storage.

import { bank } from './bank.js';
import { overallRecord } from './rivals.js';
import { skillKey, todayKey } from './state.js';

// ─────────────────────────────── Levels ───────────────────────────────
// Cumulative XP needed to *reach* level L. Gap grows by 50 each level:
// L2 = 100, L3 = 250, L4 = 450, L5 = 700, L6 = 1000 ...
export function xpToReach(level) {
  const n = level - 1;
  return 100 * n + 25 * n * (n - 1);
}

export function levelInfo(xp) {
  let level = 1;
  while (xpToReach(level + 1) <= xp) level += 1;
  const floor = xpToReach(level);
  const ceiling = xpToReach(level + 1);
  const span = ceiling - floor;
  return {
    level,
    into: xp - floor,
    span,
    toNext: ceiling - xp,
    pct: span === 0 ? 0 : Math.min(100, ((xp - floor) / span) * 100),
  };
}

export const titleForLevel = (level) => {
  const titles = [
    'Bubble Sheet Rookie', // 1
    'No. 2 Apprentice', // 2
    'Calculator Wrangler', // 3
    'Passage Prowler', // 4
    'Grid-In Grinder', // 5
    'Section Slayer', // 6
    'Curve Bender', // 7
    'Score Report Legend', // 8
    'Domain Dominator', // 9
    'Perfect Scaled Score', // 10
    'Proctor’s Nightmare', // 11
    'Superscore Savant', // 12
    'National Merit Material', // 13
    'Ivy Bound', // 14
    'Test Day Titan', // 15
    'Answer Key Oracle', // 16
    'The Curve Itself', // 17
    'SAT Mythos', // 18
    'Beyond the Bell Curve', // 19
    'SAT Quest Grandmaster', // 20+
  ];
  return titles[Math.min(level - 1, titles.length - 1)];
};

// ────────────────────────────── Scoring ──────────────────────────────
export const BASE_XP = 10;
export const MAX_COMBO_BONUS = 10; // combo multiplier caps at 2.0x

// combo = number of consecutive correct answers *including* this one.
export function comboMultiplier(combo) {
  return 1 + Math.min(Math.max(combo - 1, 0), MAX_COMBO_BONUS) * 0.1;
}

export function scoreAnswer({ question, combo, timeLeftMs, timeLimitMs }) {
  const base = BASE_XP + 5 * (question.difficulty - 1);
  const mult = comboMultiplier(combo);
  const speed = timeLimitMs ? Math.round(10 * Math.max(0, timeLeftMs / timeLimitMs)) : 0;
  return {
    base,
    mult,
    speed,
    total: Math.round(base * mult) + speed,
  };
}

// ─────────────────────────────── Rounds ───────────────────────────────
export const MODES = {
  quick: {
    id: 'quick',
    name: 'Quick 10',
    blurb: 'Ten mixed questions. No clock, full explanations.',
    icon: '⚡',
    count: 10,
    timeLimitMs: 0,
  },
  sprint: {
    id: 'sprint',
    name: 'Timed Sprint',
    blurb: '12 questions, 45 seconds each. Speed pays XP.',
    icon: '⏱️',
    count: 12,
    timeLimitMs: 45000,
  },
  drill: {
    id: 'drill',
    name: 'Weak-Spot Drill',
    blurb: 'Ten questions weighted toward the skills you keep missing.',
    icon: '🎯',
    count: 10,
    timeLimitMs: 0,
  },
  math: {
    id: 'math',
    name: 'Math Section',
    blurb: 'Algebra through geometry — 15 questions.',
    icon: '📐',
    count: 15,
    timeLimitMs: 0,
    section: 'math',
  },
  rw: {
    id: 'rw',
    name: 'Reading & Writing',
    blurb: 'Passages, evidence and grammar — 15 questions.',
    icon: '📖',
    count: 15,
    timeLimitMs: 0,
    section: 'rw',
  },
  /** Challenge codes: a fixed question list, timed, scored for comparison. */
  challenge: {
    id: 'challenge',
    name: 'Challenge',
    blurb: 'Eight questions against a friend’s recorded run.',
    icon: '⚔️',
    count: 8,
    timeLimitMs: 30000,
  },
};

function shuffle(list) {
  const out = list.slice();
  for (let i = out.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

// Weighted sample without replacement.
function weightedPick(pool, weights, count) {
  const items = pool.slice();
  const w = weights.slice();
  const picked = [];
  while (picked.length < count && items.length) {
    const total = w.reduce((a, b) => a + b, 0);
    let r = Math.random() * total;
    let idx = 0;
    while (idx < items.length - 1 && r > w[idx]) {
      r -= w[idx];
      idx += 1;
    }
    picked.push(items[idx]);
    items.splice(idx, 1);
    w.splice(idx, 1);
  }
  return picked;
}

export function buildRound(modeId, state) {
  const mode = MODES[modeId] ?? MODES.quick;
  const pool = bank.all.filter((q) => (mode.section ? q.section === mode.section : true));

  let questions;
  if (mode.id === 'drill') {
    // Weight by how badly the skill is going. Unseen skills get a middling
    // weight so a fresh account still gets a varied drill.
    const weights = pool.map((q) => {
      const rec = state.skills[skillKey(q)];
      if (!rec || rec.seen === 0) return 2;
      const acc = rec.correct / rec.seen;
      return 1 + (1 - acc) * 8 + Math.min(rec.seen, 5) * 0.2;
    });
    questions = weightedPick(pool, weights, Math.min(mode.count, pool.length));
  } else {
    questions = shuffle(pool).slice(0, Math.min(mode.count, pool.length));
  }

  return {
    mode: mode.id,
    timeLimitMs: mode.timeLimitMs,
    questions,
  };
}

// ─────────────────────── Applying results to state ───────────────────────
export function applyAnswer(state, { question, correct, xpGained, elapsedMs, timed }) {
  const key = skillKey(question);
  const prev = state.skills[key] ?? {
    section: question.section,
    domain: question.domain,
    skill: question.skill,
    seen: 0,
    correct: 0,
  };
  return {
    ...state,
    xp: state.xp + xpGained,
    totalAnswered: state.totalAnswered + 1,
    totalCorrect: state.totalCorrect + (correct ? 1 : 0),
    fastCorrect: state.fastCorrect + (correct && timed && elapsedMs < 10000 ? 1 : 0),
    skills: {
      ...state.skills,
      [key]: { ...prev, seen: prev.seen + 1, correct: prev.correct + (correct ? 1 : 0) },
    },
  };
}

export function finalizeRound(state, session) {
  const { answered, correct, xp, bestCombo } = session;
  const today = todayKey();

  // Daily streak: same day keeps it, yesterday extends it, anything else resets.
  let streak = state.streak;
  if (state.lastPlayed !== today) {
    const yesterday = todayKey(new Date(Date.now() - 86400000));
    streak = state.lastPlayed === yesterday ? state.streak + 1 : 1;
  }
  if (streak === 0) streak = 1;

  const perfect = answered >= 10 && correct === answered;

  const history = state.history.slice();
  const last = history[history.length - 1];
  if (last && last.date === today) {
    history[history.length - 1] = {
      date: today,
      answered: last.answered + answered,
      correct: last.correct + correct,
      xp: last.xp + xp,
    };
  } else {
    history.push({ date: today, answered, correct, xp });
  }

  const next = {
    ...state,
    streak,
    lastPlayed: today,
    rounds: state.rounds + 1,
    bestCombo: Math.max(state.bestCombo, bestCombo),
    perfectRounds: state.perfectRounds + (perfect ? 1 : 0),
    history: history.slice(-30),
  };

  const earned = BADGES.filter((b) => !next.badges.includes(b.id) && b.test(next));
  return {
    state: { ...next, badges: [...next.badges, ...earned.map((b) => b.id)] },
    newBadges: earned,
    perfect,
  };
}

// ─────────────────────────────── Badges ───────────────────────────────
const sectionCorrect = (state, section) =>
  Object.values(state.skills)
    .filter((r) => r.section === section)
    .reduce((a, r) => a + r.correct, 0);

export const BADGES = [
  { id: 'first-steps', name: 'First Steps', icon: '👟', desc: 'Answer your first question.', test: (s) => s.totalAnswered >= 1 },
  { id: 'warmed-up', name: 'Warmed Up', icon: '🔥', desc: 'Answer 25 questions.', test: (s) => s.totalAnswered >= 25 },
  { id: 'century', name: 'Century', icon: '💯', desc: 'Answer 100 questions.', test: (s) => s.totalAnswered >= 100 },
  { id: 'marathon', name: 'Marathon', icon: '🏃', desc: 'Answer 250 questions.', test: (s) => s.totalAnswered >= 250 },
  { id: 'combo-5', name: 'On a Roll', icon: '🎲', desc: 'Hit a 5-answer combo.', test: (s) => s.bestCombo >= 5 },
  { id: 'combo-10', name: 'Unbroken', icon: '⛓️', desc: 'Hit a 10-answer combo.', test: (s) => s.bestCombo >= 10 },
  { id: 'combo-20', name: 'Untouchable', icon: '💠', desc: 'Hit a 20-answer combo.', test: (s) => s.bestCombo >= 20 },
  { id: 'flawless', name: 'Flawless', icon: '✨', desc: 'Finish a round with 100% accuracy.', test: (s) => s.perfectRounds >= 1 },
  { id: 'flawless-3', name: 'Clean Sweep', icon: '🧼', desc: 'Finish three perfect rounds.', test: (s) => s.perfectRounds >= 3 },
  { id: 'quickdraw', name: 'Quickdraw', icon: '⚡', desc: '10 correct answers in under 10 seconds each.', test: (s) => s.fastCorrect >= 10 },
  { id: 'streak-3', name: 'Habit Forming', icon: '📆', desc: 'Practice three days in a row.', test: (s) => s.streak >= 3 },
  { id: 'streak-7', name: 'Week Strong', icon: '🗓️', desc: 'Practice seven days in a row.', test: (s) => s.streak >= 7 },
  { id: 'level-5', name: 'Rising Score', icon: '📈', desc: 'Reach level 5.', test: (s) => levelInfo(s.xp).level >= 5 },
  { id: 'level-8', name: 'Top Percentile', icon: '👑', desc: 'Reach level 8.', test: (s) => levelInfo(s.xp).level >= 8 },
  { id: 'mathlete', name: 'Mathlete', icon: '📐', desc: 'Get 25 math questions right.', test: (s) => sectionCorrect(s, 'math') >= 25 },
  { id: 'wordsmith', name: 'Wordsmith', icon: '📖', desc: 'Get 25 Reading & Writing questions right.', test: (s) => sectionCorrect(s, 'rw') >= 25 },
  {
    id: 'well-rounded',
    name: 'Well Rounded',
    icon: '🧭',
    desc: 'Practice all eight SAT domains.',
    test: (s) => new Set(Object.values(s.skills).map((r) => r.domain)).size >= 8,
  },
  {
    id: 'no-weak-spots',
    name: 'No Weak Spots',
    icon: '🛡️',
    desc: 'Hold 70%+ accuracy in every skill you have seen 3+ times.',
    test: (s) => {
      const tracked = Object.values(s.skills).filter((r) => r.seen >= 3);
      return tracked.length >= 6 && tracked.every((r) => r.correct / r.seen >= 0.7);
    },
  },

  // ── Bigger volume milestones ──
  { id: 'grinder-500', name: 'Grinder', icon: '⚙️', desc: 'Answer 500 questions.', test: (s) => s.totalAnswered >= 500 },
  { id: 'iron-will-1000', name: 'Iron Will', icon: '🗿', desc: 'Answer 1,000 questions.', test: (s) => s.totalAnswered >= 1000 },
  { id: 'legend-2500', name: 'Legend', icon: '🏛️', desc: 'Answer 2,500 questions.', test: (s) => s.totalAnswered >= 2500 },
  { id: 'immortal-5000', name: 'Immortal', icon: '♾️', desc: 'Answer 5,000 questions.', test: (s) => s.totalAnswered >= 5000 },

  // ── Bigger combos ──
  { id: 'combo-30', name: 'Nuclear', icon: '☢️', desc: 'Hit a 30-answer combo.', test: (s) => s.bestCombo >= 30 },
  { id: 'combo-50', name: 'Godlike', icon: '🌟', desc: 'Hit a 50-answer combo.', test: (s) => s.bestCombo >= 50 },

  // ── Longer streaks ──
  { id: 'streak-14', name: 'Two-Week Ritual', icon: '📅', desc: 'Practice fourteen days in a row.', test: (s) => s.streak >= 14 },
  { id: 'streak-30', name: 'Monthly Devotion', icon: '🌕', desc: 'Practice thirty days in a row.', test: (s) => s.streak >= 30 },
  { id: 'streak-100', name: 'Centurion', icon: '🛡️', desc: 'Practice one hundred days in a row.', test: (s) => s.streak >= 100 },

  // ── Higher levels ──
  { id: 'level-10', name: 'Perfect Scaled Score', icon: '💎', desc: 'Reach level 10.', test: (s) => levelInfo(s.xp).level >= 10 },
  { id: 'level-15', name: 'Test Day Titan', icon: '⚡', desc: 'Reach level 15.', test: (s) => levelInfo(s.xp).level >= 15 },
  { id: 'level-20', name: 'Grandmaster', icon: '🏆', desc: 'Reach level 20.', test: (s) => levelInfo(s.xp).level >= 20 },

  // ── Deeper section mastery ──
  { id: 'mathlete-100', name: 'Numbers Person', icon: '🧮', desc: 'Get 100 math questions right.', test: (s) => sectionCorrect(s, 'math') >= 100 },
  { id: 'mathlete-250', name: 'Math Savant', icon: '🔢', desc: 'Get 250 math questions right.', test: (s) => sectionCorrect(s, 'math') >= 250 },
  { id: 'wordsmith-100', name: 'Well-Read', icon: '📚', desc: 'Get 100 Reading & Writing questions right.', test: (s) => sectionCorrect(s, 'rw') >= 100 },
  { id: 'wordsmith-250', name: 'Literary Mind', icon: '🖋️', desc: 'Get 250 Reading & Writing questions right.', test: (s) => sectionCorrect(s, 'rw') >= 250 },

  // ── More perfect rounds ──
  { id: 'flawless-10', name: 'Precision Machine', icon: '🎯', desc: 'Finish ten perfect rounds.', test: (s) => s.perfectRounds >= 10 },

  // ── Speed ──
  { id: 'quickdraw-50', name: 'Lightning Reflexes', icon: '🌩️', desc: '50 correct answers in under 10 seconds each.', test: (s) => s.fastCorrect >= 50 },

  // ── Duel record (reads your real head-to-head history) ──
  { id: 'duelist-1', name: 'First Blood', icon: '⚔️', desc: 'Win your first duel.', test: () => overallRecord().wins >= 1 },
  { id: 'duelist-10', name: 'Seasoned Duelist', icon: '🗡️', desc: 'Win 10 duels.', test: () => overallRecord().wins >= 10 },
  { id: 'duelist-50', name: 'Arena Champion', icon: '🏹', desc: 'Win 50 duels.', test: () => overallRecord().wins >= 50 },
  { id: 'duelist-100', name: 'Undisputed', icon: '👑', desc: 'Win 100 duels.', test: () => overallRecord().wins >= 100 },
];

export const badgeById = Object.fromEntries(BADGES.map((b) => [b.id, b]));

// ───────────────────── Analytics for the dashboard ─────────────────────
export function domainStats(state, section) {
  const map = new Map();
  for (const rec of Object.values(state.skills)) {
    if (rec.section !== section) continue;
    const cur = map.get(rec.domain) ?? { seen: 0, correct: 0 };
    map.set(rec.domain, { seen: cur.seen + rec.seen, correct: cur.correct + rec.correct });
  }
  return map;
}

// Skills sorted worst-first. A skill qualifies once it has been missed at least
// once, or attempted twice — with ~45 narrow skills in the bank, waiting for
// repeat attempts would leave this list empty for several rounds.
export function weakSpots(state, limit = 5) {
  return Object.values(state.skills)
    .filter((r) => r.seen >= 2 || r.correct < r.seen)
    .map((r) => ({ ...r, accuracy: r.correct / r.seen }))
    .sort((a, b) => a.accuracy - b.accuracy || b.seen - a.seen)
    .slice(0, limit);
}

export function strongestSkill(state) {
  return (
    Object.values(state.skills)
      .filter((r) => r.seen >= 2)
      .map((r) => ({ ...r, accuracy: r.correct / r.seen }))
      .sort((a, b) => b.accuracy - a.accuracy || b.seen - a.seen)[0] ?? null
  );
}

// Last `days` calendar days of activity, oldest first — for the sparkline.
export function activitySeries(state, days = 14) {
  const byDate = Object.fromEntries(state.history.map((h) => [h.date, h]));
  const out = [];
  for (let i = days - 1; i >= 0; i -= 1) {
    const date = todayKey(new Date(Date.now() - i * 86400000));
    const h = byDate[date];
    out.push({ date, answered: h?.answered ?? 0, correct: h?.correct ?? 0, xp: h?.xp ?? 0 });
  }
  return out;
}

// Very rough section-score feel (200–800) so progress maps onto something
// familiar. Not a predicted SAT score, and the UI says so.
export function scoreFeel(state, section) {
  const stats = domainStats(state, section);
  let seen = 0;
  let correct = 0;
  for (const v of stats.values()) {
    seen += v.seen;
    correct += v.correct;
  }
  if (seen < 5) return null;
  return Math.round((200 + 600 * (correct / seen)) / 10) * 10;
}
