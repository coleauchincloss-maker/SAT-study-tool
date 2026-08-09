// Persistent player state. One localStorage key, versioned so a future schema
// change can migrate instead of silently reading garbage.

const KEY = 'satquest.v1';

export function todayKey(d = new Date()) {
  // Local calendar day, not UTC — streaks should follow the user's midnight.
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function defaultState() {
  return {
    version: 1,
    xp: 0,
    totalAnswered: 0,
    totalCorrect: 0,
    bestCombo: 0,
    fastCorrect: 0, // correct answers under 10s in a timed round
    perfectRounds: 0,
    rounds: 0,
    streak: 0,
    lastPlayed: null, // 'YYYY-MM-DD'
    badges: [], // badge ids, in unlock order
    skills: {}, // 'math|Algebra|Linear functions' -> { section, domain, skill, seen, correct }
    history: [], // [{ date, answered, correct, xp }] newest last, capped
  };
}

export function loadState() {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return defaultState();
    const parsed = JSON.parse(raw);
    if (!parsed || parsed.version !== 1) return defaultState();
    return { ...defaultState(), ...parsed };
  } catch {
    return defaultState();
  }
}

export function saveState(state) {
  try {
    localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    // Private-browsing or quota failure: the app still works for this session.
  }
}

export function clearState() {
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
  return defaultState();
}

export const skillKey = (q) => `${q.section}|${q.domain}|${q.skill}`;
