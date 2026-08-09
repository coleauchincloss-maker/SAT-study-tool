// Digital-SAT section structure: two modules, where Module 2's difficulty is
// chosen by how Module 1 went. Pure logic — no DOM.
//
// The real test uses 27 questions / 32 minutes per Reading & Writing module and
// 22 questions / 35 minutes per Math module. The bank may be smaller than that,
// so module size is clamped to what's available and the UI says so explicitly
// rather than silently serving a short section.

import { bank } from './bank.js';
import { skillKey } from './state.js';

export const SECTION_SPEC = {
  rw: {
    id: 'rw',
    label: 'Reading and Writing',
    perModule: 27,
    minutes: 32,
    domains: ['Information & Ideas', 'Craft & Structure', 'Expression of Ideas', 'Standard English Conventions'],
  },
  math: {
    id: 'math',
    label: 'Math',
    perModule: 22,
    minutes: 35,
    domains: ['Algebra', 'Advanced Math', 'Problem-Solving & Data', 'Geometry & Trig'],
  },
};

/** Module 2 is the harder form when Module 1 accuracy clears this. */
export const ROUTING_THRESHOLD = 0.6;

function shuffle(list) {
  const out = list.slice();
  for (let i = out.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

/**
 * Pick `count` questions, spreading across domains before doubling up on any one,
 * and ordering by the given difficulty preference within each pass.
 */
function pick(pool, count, difficultyRank) {
  const byDomain = new Map();
  for (const question of shuffle(pool)) {
    if (!byDomain.has(question.domain)) byDomain.set(question.domain, []);
    byDomain.get(question.domain).push(question);
  }
  for (const list of byDomain.values()) {
    list.sort((a, b) => difficultyRank(a) - difficultyRank(b));
  }

  // Round-robin across domains so a short bank still covers the whole section.
  const domains = shuffle([...byDomain.keys()]);
  const chosen = [];
  let exhausted = false;
  while (chosen.length < count && !exhausted) {
    exhausted = true;
    for (const domain of domains) {
      if (chosen.length >= count) break;
      const next = byDomain.get(domain).shift();
      if (next) {
        chosen.push(next);
        exhausted = false;
      }
    }
  }

  // Easy-to-hard within the module, as the real test roughly does.
  return chosen.sort((a, b) => a.difficulty - b.difficulty);
}

/** Module 1 is mixed difficulty and always the same shape regardless of skill. */
export function buildModuleOne(sectionId) {
  const spec = SECTION_SPEC[sectionId];
  const pool = bank.all.filter((q) => q.section === sectionId);
  // Half the pool at most, so Module 2 has untouched questions to draw from.
  const count = Math.min(spec.perModule, Math.floor(pool.length / 2));
  const target = { 1: 0, 2: 1, 3: 2 };
  return {
    number: 1,
    form: 'mixed',
    questions: pick(pool, count, (q) => target[q.difficulty]),
    fullLength: count === spec.perModule,
  };
}

/**
 * Module 2, routed by Module 1 accuracy: the upper form leans on difficulty 3,
 * the lower form on difficulty 1. Questions already seen are excluded.
 */
export function buildModuleTwo(sectionId, moduleOne, correctCount) {
  const spec = SECTION_SPEC[sectionId];
  const used = new Set(moduleOne.questions.map((q) => q.id));
  const pool = bank.all.filter((q) => q.section === sectionId && !used.has(q.id));

  const accuracy = moduleOne.questions.length ? correctCount / moduleOne.questions.length : 0;
  const upper = accuracy >= ROUTING_THRESHOLD;
  const rank = upper ? (q) => -q.difficulty : (q) => q.difficulty;
  const count = Math.min(spec.perModule, pool.length);

  return {
    number: 2,
    form: upper ? 'upper' : 'lower',
    accuracyIn: accuracy,
    questions: pick(pool, count, rank),
    fullLength: count === spec.perModule,
  };
}

/** Is there enough in the bank to run a two-module section at all? */
export function canRunSection(sectionId) {
  const pool = bank.all.filter((q) => q.section === sectionId);
  return { ok: pool.length >= 8, available: pool.length, needed: 8 };
}

// ─────────────────────────────── scoring ───────────────────────────────
/**
 * A rough section score. The routed module bounds the range the way the real
 * adaptive test does — the lower form can't reach the top of the scale — but
 * this is a motivational estimate, not a predicted SAT score, and the UI says so.
 */
export function estimateSectionScore({ correct, total, form }) {
  if (!total) return null;
  const fraction = correct / total;
  const [floor, span] = form === 'upper' ? [340, 460] : [200, 380];
  return Math.round((floor + span * fraction) / 10) * 10;
}

/** Per-domain and per-skill rollup for the exam report. */
export function examBreakdown(results) {
  const domains = new Map();
  const skills = new Map();
  for (const { question, correct } of results) {
    for (const [map, key] of [
      [domains, question.domain],
      [skills, skillKey(question)],
    ]) {
      const record = map.get(key) ?? { seen: 0, correct: 0, label: question.domain, skill: question.skill };
      record.seen += 1;
      record.correct += correct ? 1 : 0;
      map.set(key, record);
    }
  }
  return {
    domains: [...domains.entries()].map(([domain, r]) => ({ domain, ...r })),
    skills: [...skills.values()],
  };
}

/** Longest run of consecutive correct answers, for the XP/combo stats. */
export function longestStreak(results) {
  let best = 0;
  let run = 0;
  for (const { correct } of results) {
    run = correct ? run + 1 : 0;
    best = Math.max(best, run);
  }
  return best;
}
