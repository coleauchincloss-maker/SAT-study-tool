// The question bank: built-in questions plus anything Claude has generated.
//
// Both files are JSON so the Python match server reads exactly the same data.
// Everything else imports `bank` and reads `bank.all`, so growing the bank never
// touches another module.

export const bank = {
  all: [],
  builtIn: 0,
  generated: 0,
  /** Server capabilities, or null when not served by server.py. */
  status: null,
  loaded: false,
};

/** The generator always emits passage/notes/table; drop them when empty. */
function normalize(question) {
  const clean = { ...question };
  if (!clean.passage) delete clean.passage;
  if (!clean.notes?.length) delete clean.notes;
  if (!clean.table?.headers?.length) delete clean.table;
  return clean;
}

function usable(question) {
  return (
    question &&
    typeof question.id === 'string' &&
    typeof question.prompt === 'string' &&
    Array.isArray(question.choices) &&
    question.choices.length === 4 &&
    Number.isInteger(question.answer) &&
    question.answer >= 0 &&
    question.answer <= 3 &&
    (question.section === 'math' || question.section === 'rw')
  );
}

async function loadFile(path) {
  try {
    const response = await fetch(path, { cache: 'no-store' });
    if (!response.ok) return [];
    const data = await response.json();
    return (data?.questions ?? []).filter(usable).map(normalize);
  } catch {
    return [];
  }
}

/** Load (or reload) the bank. Safe to call again after a generation run. */
export async function loadBank() {
  const [builtIn, generated] = await Promise.all([
    loadFile('./data/questions.json'),
    loadFile('./data/generated.json'),
  ]);

  const seen = new Set();
  const merged = [];
  for (const question of [...builtIn, ...generated]) {
    if (seen.has(question.id)) continue;
    seen.add(question.id);
    merged.push(question);
  }

  bank.all = merged;
  bank.builtIn = builtIn.length;
  bank.generated = merged.length - builtIn.length;
  bank.loaded = true;
  return bank;
}

/** Ask the server what it can do. Null when opened without server.py. */
export async function loadStatus() {
  try {
    const response = await fetch('./api/status', { cache: 'no-store' });
    bank.status = response.ok ? await response.json() : null;
  } catch {
    bank.status = null;
  }
  return bank.status;
}

/**
 * Ask the local proxy to generate questions. The API key lives in the server
 * process; this only ever sends and receives question data.
 */
export async function requestGeneration({ count = 5, section = null, domain = null } = {}) {
  const response = await fetch('./api/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ count, section, domain }),
  });

  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    throw new Error(payload?.error ?? `generation failed (HTTP ${response.status})`);
  }
  await loadBank();
  return payload;
}

export const byId = (id) => bank.all.find((q) => q.id === id) ?? null;
export const questionsFor = (section) => bank.all.filter((q) => q.section === section);
