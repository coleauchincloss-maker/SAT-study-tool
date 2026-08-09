// Turns pasted text into the question shape the server expects. Three input
// formats, chosen explicitly by the user rather than sniffed — sniffing a
// format wrong silently mangles data, an explicit choice just fails loudly.
//
// Every parser returns { questions, errors } where `questions` are plain
// objects (prompt, choices[4], answer 0-3, domain, section, skill,
// difficulty, explanation) and `errors` are human-readable strings pointing
// at the offending row/block. Nothing here talks to the network — parsing is
// pure so it can be unit-tested and previewed before anything is sent.

const LETTER_INDEX = { A: 0, B: 1, C: 2, D: 3, 1: 0, 2: 1, 3: 2, 4: 3 };

function answerToIndex(raw, choices) {
  if (raw == null) return null;
  const text = String(raw).trim();
  if (text === '') return null;
  const upper = text.toUpperCase();
  if (upper in LETTER_INDEX) return LETTER_INDEX[upper];
  const asNum = Number(text);
  if (Number.isInteger(asNum) && asNum >= 0 && asNum <= 3) return asNum; // already a 0-based index
  // Fall back to matching the literal text of one of the choices.
  const match = choices.findIndex((c) => c.trim().toLowerCase() === text.toLowerCase());
  return match >= 0 ? match : null;
}

function normalizeSection(raw) {
  const text = (raw || '').trim().toLowerCase();
  if (['math', 'm'].includes(text)) return 'math';
  if (['rw', 'reading', 'reading & writing', 'reading and writing', 'r'].includes(text)) return 'rw';
  return null;
}

// ─────────────────────────────── JSON ───────────────────────────────

export function parseJSON(text) {
  let data;
  try {
    data = JSON.parse(text);
  } catch (error) {
    return { questions: [], errors: [`Invalid JSON: ${error.message}`] };
  }
  const list = Array.isArray(data) ? data : Array.isArray(data?.questions) ? data.questions : null;
  if (!list) return { questions: [], errors: ['Expected a JSON array of questions, or {"questions": [...]}.'] };

  const questions = [];
  const errors = [];
  list.forEach((item, i) => {
    if (!item || typeof item !== 'object') {
      errors.push(`Item ${i + 1}: not an object.`);
      return;
    }
    const choices = Array.isArray(item.choices) ? item.choices.map((c) => String(c)) : [];
    const answer = answerToIndex(item.answer, choices);
    questions.push({
      prompt: String(item.prompt || '').trim(),
      choices,
      answer,
      domain: (item.domain || '').trim(),
      section: normalizeSection(item.section) || (item.section ?? null),
      skill: (item.skill || '').trim(),
      difficulty: [1, 2, 3].includes(item.difficulty) ? item.difficulty : null,
      explanation: String(item.explanation || '').trim(),
    });
  });
  return { questions, errors };
}

// ─────────────────────────────── plain text ───────────────────────────────
//
// Q: What is 2+2?
// A) 3
// B) 4
// C) 5
// D) 6
// ANSWER: B
// EXPLANATION: 2 + 2 = 4.
// DOMAIN: Algebra
// SECTION: math
// ---
// Q: next question...

const CHOICE_PREFIX = /^([A-D1-4])[).:]\s*(.*)$/i;
const FIELD_PREFIX = /^(Q|QUESTION|ANSWER|EXPLANATION|DOMAIN|SECTION|SKILL|DIFFICULTY)\s*:\s*(.*)$/i;

export function parsePlainText(text) {
  const blocks = text
    .split(/\n\s*-{3,}\s*\n/)
    .map((b) => b.trim())
    .filter(Boolean);

  const questions = [];
  const errors = [];

  blocks.forEach((block, i) => {
    const lines = block.split('\n');
    const q = { prompt: '', choices: [], answer: null, domain: '', section: null, skill: '', difficulty: null, explanation: '' };
    const choiceLines = ['', '', '', ''];
    let current = null; // which field is accumulating multi-line text

    for (const rawLine of lines) {
      const line = rawLine.trimEnd();
      const choiceMatch = line.match(CHOICE_PREFIX);
      const fieldMatch = line.match(FIELD_PREFIX);

      if (choiceMatch) {
        const idx = LETTER_INDEX[choiceMatch[1].toUpperCase()];
        choiceLines[idx] = choiceMatch[2];
        current = { kind: 'choice', idx };
      } else if (fieldMatch) {
        const key = fieldMatch[1].toUpperCase();
        const value = fieldMatch[2];
        if (key === 'Q' || key === 'QUESTION') { q.prompt = value; current = { kind: 'prompt' }; }
        else if (key === 'ANSWER') { q.answer = value; current = null; }
        else if (key === 'EXPLANATION') { q.explanation = value; current = { kind: 'explanation' }; }
        else if (key === 'DOMAIN') { q.domain = value; current = null; }
        else if (key === 'SECTION') { q.section = value; current = null; }
        else if (key === 'SKILL') { q.skill = value; current = null; }
        else if (key === 'DIFFICULTY') { q.difficulty = Number(value) || null; current = null; }
      } else if (line.trim() && current) {
        // A continuation line for whatever field we were last filling in.
        if (current.kind === 'prompt') q.prompt += '\n' + line;
        else if (current.kind === 'explanation') q.explanation += '\n' + line;
        else if (current.kind === 'choice') choiceLines[current.idx] += '\n' + line;
      }
    }

    if (!q.prompt && choiceLines.every((c) => !c)) return; // a stray blank block

    q.choices = choiceLines.map((c) => c.trim());
    q.prompt = q.prompt.trim();
    q.section = normalizeSection(q.section);
    q.answer = answerToIndex(q.answer, q.choices);
    q.domain = q.domain.trim();
    q.skill = q.skill.trim();
    q.explanation = q.explanation.trim();

    if (!q.prompt) errors.push(`Block ${i + 1}: missing "Q:" line.`);
    questions.push(q);
  });

  return { questions, errors };
}

// ─────────────────────────────── CSV ───────────────────────────────
// Header row required. Recognized columns (any order, case-insensitive):
// prompt, choice1, choice2, choice3, choice4, answer, explanation, domain,
// section, skill, difficulty.

function splitCsvLine(line) {
  const cells = [];
  let cur = '';
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (inQuotes) {
      if (ch === '"' && line[i + 1] === '"') { cur += '"'; i++; }
      else if (ch === '"') inQuotes = false;
      else cur += ch;
    } else if (ch === '"') {
      inQuotes = true;
    } else if (ch === ',') {
      cells.push(cur);
      cur = '';
    } else {
      cur += ch;
    }
  }
  cells.push(cur);
  return cells.map((c) => c.trim());
}

export function parseCSV(text) {
  const lines = text.split(/\r?\n/).filter((l) => l.trim() !== '');
  if (lines.length < 2) return { questions: [], errors: ['Need a header row plus at least one question row.'] };

  const headers = splitCsvLine(lines[0]).map((h) => h.toLowerCase());
  const col = (name) => headers.indexOf(name);
  const need = ['prompt', 'choice1', 'choice2', 'choice3', 'choice4', 'answer'];
  const missing = need.filter((n) => col(n) === -1);
  if (missing.length) return { questions: [], errors: [`Missing column(s): ${missing.join(', ')}.`] };

  const questions = [];
  const errors = [];
  for (let i = 1; i < lines.length; i++) {
    const cells = splitCsvLine(lines[i]);
    const get = (name) => (col(name) >= 0 ? cells[col(name)] ?? '' : '');
    const choices = [get('choice1'), get('choice2'), get('choice3'), get('choice4')];
    const difficulty = Number(get('difficulty'));
    questions.push({
      prompt: get('prompt'),
      choices,
      answer: answerToIndex(get('answer'), choices),
      domain: get('domain'),
      section: normalizeSection(get('section')),
      skill: get('skill'),
      difficulty: [1, 2, 3].includes(difficulty) ? difficulty : null,
      explanation: get('explanation'),
    });
  }
  return { questions, errors };
}

export function parse(format, text) {
  if (format === 'json') return parseJSON(text);
  if (format === 'csv') return parseCSV(text);
  return parsePlainText(text);
}

/** Client-side sanity pass before we bother the server — same rules it enforces. */
export function validateForPreview(q, defaultSection) {
  const problems = [];
  if (!q.prompt) problems.push('missing prompt');
  const choices = (q.choices || []).map((c) => (c || '').trim());
  if (choices.length !== 4 || choices.some((c) => !c)) problems.push('needs exactly 4 non-empty choices');
  else if (new Set(choices.map((c) => c.toLowerCase())).size !== 4) problems.push('duplicate choices');
  if (q.answer === null || q.answer === undefined || q.answer < 0 || q.answer > 3) problems.push('answer not recognized (use A-D, 1-4, or the exact choice text)');
  const section = q.section || defaultSection;
  if (section !== 'math' && section !== 'rw') problems.push('section must be Math or Reading & Writing');
  return problems;
}
