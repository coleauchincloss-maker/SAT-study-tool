// Client for the match server.
//
// The server base URL is configurable: empty means "same origin", which covers
// both playing on your own laptop and a friend opening your LAN address. Point it
// at a deployed server to play someone who isn't on your network.

const SERVER_KEY = 'satquest.server';
const SESSION_KEY = 'satquest.session';

export const session = {
  code: null,
  playerId: null,
  state: null,
  /** 'idle' | 'connecting' | 'live' | 'dropped' */
  link: 'idle',
  error: null,
};

export function serverBase() {
  try {
    return (localStorage.getItem(SERVER_KEY) || '').replace(/\/+$/, '');
  } catch {
    return '';
  }
}

export function setServerBase(url) {
  try {
    const clean = (url || '').trim().replace(/\/+$/, '');
    if (clean) localStorage.setItem(SERVER_KEY, clean);
    else localStorage.removeItem(SERVER_KEY);
  } catch {
    /* private browsing */
  }
}

const api = (path) => `${serverBase()}${path}`;

async function post(path, body) {
  let response;
  try {
    response = await fetch(api(path), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch {
    throw new Error(
      serverBase()
        ? `Could not reach the match server at ${serverBase()}.`
        : 'Could not reach the match server. Is server.py running?',
    );
  }

  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) throw new Error(payload?.error ?? `request failed (HTTP ${response.status})`);
  return payload;
}

export async function matchInfo() {
  try {
    const response = await fetch(api('/api/match/info'), { cache: 'no-store' });
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

// ─────────────────────────── session persistence ───────────────────────────
// A refresh mid-match shouldn't forfeit, so the seat is remembered by playerId.
//
// This lives in sessionStorage, not localStorage: a seat belongs to one tab.
// sessionStorage survives a reload but is not shared between tabs, so opening a
// second tab can't hijack the seat you're already playing.

function remember() {
  try {
    if (session.code && session.playerId) {
      sessionStorage.setItem(SESSION_KEY, JSON.stringify({ code: session.code, playerId: session.playerId }));
    } else {
      sessionStorage.removeItem(SESSION_KEY);
    }
  } catch {
    /* ignore */
  }
}

export function rememberedSession() {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function forgetSession() {
  session.code = null;
  session.playerId = null;
  session.state = null;
  session.link = 'idle';
  remember();
  try {
    sessionStorage.removeItem(SESSION_KEY);
  } catch {
    /* ignore */
  }
}

// ─────────────────────────── joining ───────────────────────────

export async function createMatch({ name, mode, section = null, target = null, questionSeconds = null, focusMode = false, source = 'all' }) {
  const result = await post('/api/match/create', { name, mode, section, target, questionSeconds, focusMode, source });
  session.code = result.code;
  session.playerId = result.playerId;
  session.state = result.state;
  remember();
  return result;
}

export async function joinMatch({ code, name }) {
  const result = await post('/api/match/join', { code: (code || '').trim().toUpperCase(), name });
  session.code = result.code;
  session.playerId = result.playerId;
  session.state = result.state;
  remember();
  return result;
}

// ─────────────────────────── bring-your-own questions ───────────────────────────

export async function fetchImportedQuestions() {
  try {
    const response = await fetch(api('/api/questions/imported'), { cache: 'no-store' });
    return response.ok ? await response.json() : { count: 0, questions: [] };
  } catch {
    return { count: 0, questions: [] };
  }
}

export async function importQuestions(questions) {
  return post('/api/questions/import', { questions });
}

export async function clearImportedQuestions() {
  return post('/api/questions/import/clear', {});
}

// ─────────────────────────── leaderboard ───────────────────────────

export async function submitLeaderboard(payload) {
  try {
    return await post('/api/leaderboard/submit', payload);
  } catch {
    return null; // best-effort — a failed submit shouldn't interrupt play
  }
}

export async function fetchLeaderboard({ location = null, limit = 100 } = {}) {
  const params = new URLSearchParams();
  if (location) params.set('location', location);
  params.set('limit', String(limit));
  try {
    const response = await fetch(api(`/api/leaderboard?${params}`), { cache: 'no-store' });
    return response.ok ? await response.json() : { players: [] };
  } catch {
    return { players: [] };
  }
}

export async function fetchLeaderboardLocations() {
  try {
    const response = await fetch(api('/api/leaderboard/locations'), { cache: 'no-store' });
    return response.ok ? await response.json() : { locations: [] };
  } catch {
    return { locations: [] };
  }
}

export async function sendAction(type, payload = {}) {
  if (!session.code || !session.playerId) throw new Error('not in a match');
  const result = await post('/api/match/action', {
    code: session.code,
    playerId: session.playerId,
    type,
    payload,
  });
  if (result?.state) session.state = result.state;
  return result;
}

/** Confirm a remembered seat still exists before showing the match screen. */
export async function resumeMatch({ code, playerId }) {
  const response = await fetch(api(`/api/match/state?code=${encodeURIComponent(code)}&playerId=${encodeURIComponent(playerId)}`), {
    cache: 'no-store',
  });
  if (!response.ok) throw new Error('that match is gone');
  const state = await response.json();
  if (state.error) throw new Error(state.error);
  // The server only lists seats it still knows about.
  if (!state.players.some((p) => p.id === playerId)) throw new Error('your seat was taken');
  session.code = code;
  session.playerId = playerId;
  session.state = state;
  remember();
  return state;
}

// ─────────────────────────── live state ───────────────────────────

let stream = null;
let listener = null;
/** serverTime - clientTime, so both screens agree on the countdown. */
let clockOffset = 0;

export const serverNow = () => Date.now() / 1000 + clockOffset;

/** Seconds left on the server's clock, or null when nothing is timed. */
export function remaining(state = session.state) {
  if (!state?.deadline) return null;
  return Math.max(0, state.deadline - serverNow());
}

export function connect(onState) {
  disconnect();
  if (!session.code || !session.playerId) return;
  listener = onState;
  session.link = 'connecting';

  const url = api(
    `/api/match/stream?code=${encodeURIComponent(session.code)}&playerId=${encodeURIComponent(session.playerId)}`,
  );
  stream = new EventSource(url);

  stream.onmessage = (event) => {
    let state;
    try {
      state = JSON.parse(event.data);
    } catch {
      return;
    }
    if (state.gone) {
      session.link = 'dropped';
      session.error = 'The match ended.';
      listener?.(null);
      return;
    }
    if (typeof state.serverTime === 'number') {
      clockOffset = state.serverTime - Date.now() / 1000;
    }
    session.state = state;
    session.link = 'live';
    session.error = null;
    listener?.(state);
  };

  stream.onerror = () => {
    // EventSource reconnects on its own; surface the gap without tearing down.
    session.link = session.state ? 'dropped' : 'connecting';
    listener?.(session.state);
  };
}

export function disconnect() {
  if (stream) {
    stream.close();
    stream = null;
  }
  listener = null;
  session.link = 'idle';
}
