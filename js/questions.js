// Section and domain metadata.
//
// The questions themselves live in data/questions.json (built-in) and
// data/generated.json (Claude-generated) so that the Python match server and the
// browser read one source of truth — the server has to be the authority on which
// answer is correct, and it can't import a JS module.
//
// All questions are original items written for this project. Real College Board
// SAT questions are copyrighted and are not reproduced here.

export const SECTIONS = {
  math: { label: 'Math', short: 'M' },
  rw: { label: 'Reading & Writing', short: 'RW' },
};

export const DOMAINS = {
  math: ['Algebra', 'Advanced Math', 'Problem-Solving & Data', 'Geometry & Trig'],
  rw: ['Information & Ideas', 'Craft & Structure', 'Expression of Ideas', 'Standard English Conventions'],
};

export const ALL_DOMAINS = [...DOMAINS.math, ...DOMAINS.rw];

export const sectionOf = (domain) => (DOMAINS.math.includes(domain) ? 'math' : 'rw');
