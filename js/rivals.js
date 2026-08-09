// Who you play and how it's gone: local head-to-head records, plus challenge
// codes for playing someone who isn't on your network and isn't online now.

const RIVALS_KEY = 'satquest.rivals';
const PROFILE_KEY = 'satquest.profile';
const LOCATION_KEY = 'satquest.location';
const PLAYER_ID_KEY = 'satquest.playerId';

// ─────────────────────────── your name ───────────────────────────

export function myName() {
  try {
    return localStorage.getItem(PROFILE_KEY) || '';
  } catch {
    return '';
  }
}

export function setMyName(name) {
  try {
    const clean = (name || '').trim().slice(0, 16);
    if (clean) localStorage.setItem(PROFILE_KEY, clean);
  } catch {
    /* ignore */
  }
}

// ─────────────────────────── your location ───────────────────────────
// Self-reported, free text (city, school, whatever you want to be grouped
// by) — there's no accounts or geolocation lookup here, so it's exactly as
// trustworthy as everyone typing it in honestly.

export function myLocation() {
  try {
    return localStorage.getItem(LOCATION_KEY) || '';
  } catch {
    return '';
  }
}

export function setMyLocation(location) {
  try {
    const clean = (location || '').trim().slice(0, 40);
    if (clean) localStorage.setItem(LOCATION_KEY, clean);
    else localStorage.removeItem(LOCATION_KEY);
  } catch {
    /* ignore */
  }
}

// ─────────────────────────── anonymous player id ───────────────────────────
// A random id generated once per browser so the leaderboard can update your
// existing row instead of creating a new one every time you submit a score.
// It identifies a browser, not a person — clearing site data resets it.

export function myPlayerId() {
  try {
    let id = localStorage.getItem(PLAYER_ID_KEY);
    if (!id) {
      id = (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`);
      localStorage.setItem(PLAYER_ID_KEY, id);
    }
    return id;
  } catch {
    return 'anonymous';
  }
}

// ─────────────────────────── records ───────────────────────────

export function loadRivals() {
  try {
    const raw = localStorage.getItem(RIVALS_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

function saveRivals(rivals) {
  try {
    localStorage.setItem(RIVALS_KEY, JSON.stringify(rivals));
  } catch {
    /* ignore */
  }
}

const blank = (name) => ({
  name,
  wins: 0,
  losses: 0,
  draws: 0,
  pointsFor: 0,
  pointsAgainst: 0,
  /** Positive = you're on a win streak, negative = they are. */
  streak: 0,
  lastPlayed: null,
  lastMode: null,
  matches: 0,
});

/**
 * Record a finished match. `result` is 'win' | 'loss' | 'draw' from your side.
 * Returns the updated record so the UI can show "now 4–2 against Sam".
 */
export function recordMatch({ opponent, result, myScore = 0, theirScore = 0, mode = null }) {
  const key = (opponent || 'Opponent').trim().toLowerCase() || 'opponent';
  const rivals = loadRivals();
  const record = { ...blank(opponent || 'Opponent'), ...(rivals[key] ?? {}) };

  record.name = opponent || record.name;
  record.matches += 1;
  record.pointsFor += myScore;
  record.pointsAgainst += theirScore;
  record.lastPlayed = new Date().toISOString().slice(0, 10);
  record.lastMode = mode;

  if (result === 'win') {
    record.wins += 1;
    record.streak = record.streak >= 0 ? record.streak + 1 : 1;
  } else if (result === 'loss') {
    record.losses += 1;
    record.streak = record.streak <= 0 ? record.streak - 1 : -1;
  } else {
    record.draws += 1;
    record.streak = 0;
  }

  rivals[key] = record;
  saveRivals(rivals);
  return record;
}

export function rivalList() {
  return Object.values(loadRivals()).sort(
    (a, b) => b.matches - a.matches || b.wins - a.wins || a.name.localeCompare(b.name),
  );
}

export function overallRecord() {
  return rivalList().reduce(
    (totals, rival) => ({
      wins: totals.wins + rival.wins,
      losses: totals.losses + rival.losses,
      draws: totals.draws + rival.draws,
      matches: totals.matches + rival.matches,
    }),
    { wins: 0, losses: 0, draws: 0, matches: 0 },
  );
}

export function forgetRival(name) {
  const rivals = loadRivals();
  delete rivals[(name || '').trim().toLowerCase()];
  saveRivals(rivals);
}

// ─────────────────────────── challenge codes ───────────────────────────
// A challenge is self-contained: the question ids you played, plus your score.
// Your friend's app replays the identical questions and compares. No server, so
// this works across the internet — it just isn't live.

const CHALLENGE_VERSION = 1;

function toBase64Url(text) {
  const bytes = new TextEncoder().encode(text);
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function fromBase64Url(code) {
  const padded = code.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(code.length / 4) * 4, '=');
  const binary = atob(padded);
  const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

/** Build a code your friend can paste. `results` come from a finished round. */
export function makeChallengeCode({ name, section = null, results }) {
  const payload = {
    v: CHALLENGE_VERSION,
    n: (name || 'A friend').slice(0, 16),
    s: section,
    q: results.map((r) => r.question.id),
    c: results.filter((r) => r.correct).length,
    t: Math.round(results.reduce((total, r) => total + (r.elapsedMs || 0), 0)),
  };
  return `SQ1-${toBase64Url(JSON.stringify(payload))}`;
}

export function readChallengeCode(code) {
  const trimmed = (code || '').trim();
  const body = trimmed.startsWith('SQ1-') ? trimmed.slice(4) : trimmed;
  if (!body) throw new Error('paste a challenge code first');

  let payload;
  try {
    payload = JSON.parse(fromBase64Url(body));
  } catch {
    throw new Error("that doesn't look like a challenge code");
  }
  if (payload?.v !== CHALLENGE_VERSION || !Array.isArray(payload.q) || !payload.q.length) {
    throw new Error('that challenge code is not readable by this version');
  }
  return {
    name: String(payload.n || 'A friend').slice(0, 16),
    section: payload.s ?? null,
    questionIds: payload.q.map(String),
    theirCorrect: Number(payload.c) || 0,
    theirTimeMs: Number(payload.t) || 0,
  };
}

/** Compare your finished round against the challenge you accepted. */
export function judgeChallenge(challenge, results) {
  const myCorrect = results.filter((r) => r.correct).length;
  const myTimeMs = Math.round(results.reduce((total, r) => total + (r.elapsedMs || 0), 0));
  let result = 'draw';
  if (myCorrect > challenge.theirCorrect) result = 'win';
  else if (myCorrect < challenge.theirCorrect) result = 'loss';
  else if (myTimeMs && challenge.theirTimeMs) {
    // Same number correct: the faster run takes it.
    result = myTimeMs < challenge.theirTimeMs ? 'win' : myTimeMs > challenge.theirTimeMs ? 'loss' : 'draw';
  }
  return { result, myCorrect, myTimeMs, total: results.length };
}
