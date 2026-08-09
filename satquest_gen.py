"""Claude-backed question generation for SAT Quest.

Shared by the CLI (generate.py) and the local proxy endpoint (server.py), so both
paths produce identically shaped, identically validated questions.

Design notes:
  * Output shape is guaranteed by `output_config.format` (a JSON schema), so there
    is no prose parsing and no "model forgot the format" failure mode.
  * Every batch goes through a second, independent verification pass: a fresh
    request is shown the question WITHOUT the marked answer and asked to solve it.
    Items where the two disagree are dropped. This is the only automatic guard
    against a plausible-looking question with a wrong answer key.
  * The API key is read from the environment and never returned to a caller.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

MODEL = "claude-opus-5"
ROOT = Path(__file__).resolve().parent
GENERATED_PATH = ROOT / "data" / "generated.json"
BUILTIN_PATH = ROOT / "data" / "questions.json"
IMPORTED_PATH = ROOT / "data" / "imported.json"

# Batches are kept small: thinking is on by default on Opus 5 and `max_tokens`
# caps thinking plus output together, so a large batch risks truncation.
BATCH_SIZE = 5
MAX_TOKENS = 16000

DOMAINS = {
    "math": [
        "Algebra",
        "Advanced Math",
        "Problem-Solving & Data",
        "Geometry & Trig",
    ],
    "rw": [
        "Information & Ideas",
        "Craft & Structure",
        "Expression of Ideas",
        "Standard English Conventions",
    ],
}
ALL_DOMAINS = DOMAINS["math"] + DOMAINS["rw"]

# Skills the app already tracks. New skills are allowed — the dashboard picks them
# up automatically — but steering toward these keeps weak-spot stats meaningful.
KNOWN_SKILLS = {
    "Algebra": [
        "Linear equations in one variable",
        "Linear functions",
        "Systems of two linear equations",
        "Linear inequalities",
        "Linear models in context",
        "Interpreting linear models",
    ],
    "Advanced Math": [
        "Quadratic equations",
        "Quadratic graphs and vertex form",
        "Exponential growth",
        "Radical equations",
        "Polynomial factors and zeros",
        "Exponent rules",
        "Rational equations",
        "Discriminant and number of solutions",
    ],
    "Problem-Solving & Data": [
        "Percentages",
        "Percent change",
        "Rates and unit rates",
        "Ratios and proportions",
        "Mean and center",
        "Two-way tables and probability",
        "Scatterplots and models",
        "Inference from samples",
    ],
    "Geometry & Trig": [
        "Circles",
        "Right triangle trigonometry",
        "Angle relationships",
        "Volume",
        "Similar triangles",
    ],
    "Information & Ideas": [
        "Central ideas and details",
        "Command of evidence",
        "Inferences",
        "Quantitative evidence",
    ],
    "Craft & Structure": [
        "Words in context",
        "Text structure and purpose",
        "Cross-text connections",
    ],
    "Expression of Ideas": ["Transitions", "Rhetorical synthesis"],
    "Standard English Conventions": [
        "Subject-verb agreement",
        "Sentence boundaries",
        "Possessives and plurals",
        "Verb tense",
        "Colons and punctuation",
        "Finite verbs and fragments",
        "Modifier placement",
        "Pronoun clarity",
    ],
}

# ────────────────────────────── schemas ──────────────────────────────
# Structured-output schemas must set additionalProperties:false and list every
# property in `required`. Optional-in-practice fields are therefore always
# present and empty rather than absent, which also simplifies the JS side.

QUESTION_SCHEMA = {
    "type": "object",
    "properties": {
        "section": {"type": "string", "enum": ["math", "rw"]},
        "domain": {"type": "string", "enum": ALL_DOMAINS},
        "skill": {"type": "string"},
        "difficulty": {"type": "integer", "enum": [1, 2, 3]},
        "passage": {
            "type": "string",
            "description": "Stimulus text shown above the question. Empty string if not needed.",
        },
        "notes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Bullet notes for rhetorical synthesis items. Empty array if not needed.",
        },
        "table": {
            "type": "object",
            "properties": {
                "headers": {"type": "array", "items": {"type": "string"}},
                "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
            },
            "required": ["headers", "rows"],
            "additionalProperties": False,
            "description": "Data table. Empty headers and rows if not needed.",
        },
        "prompt": {"type": "string", "description": "The question itself."},
        "choices": {"type": "array", "items": {"type": "string"}, "description": "Exactly four options."},
        "answer": {"type": "integer", "enum": [0, 1, 2, 3], "description": "Index of the correct choice."},
        "explanation": {
            "type": "string",
            "description": "Why the answer is right, and where the tempting wrong answer goes wrong.",
        },
    },
    "required": [
        "section", "domain", "skill", "difficulty", "passage",
        "notes", "table", "prompt", "choices", "answer", "explanation",
    ],
    "additionalProperties": False,
}

BATCH_SCHEMA = {
    "type": "object",
    "properties": {"questions": {"type": "array", "items": QUESTION_SCHEMA}},
    "required": ["questions"],
    "additionalProperties": False,
}

VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer", "description": "Position of the question in the list you were given."},
                    "answer": {"type": "integer", "enum": [0, 1, 2, 3], "description": "The choice you believe is correct."},
                    "sound": {
                        "type": "boolean",
                        "description": "True only if exactly one choice is defensibly correct and the question is unambiguous.",
                    },
                    "issue": {"type": "string", "description": "What is wrong with the item, or empty string."},
                },
                "required": ["index", "answer", "sound", "issue"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}

# ────────────────────────────── prompts ──────────────────────────────

AUTHOR_SYSTEM = """\
You write original practice questions for the digital SAT. You are an experienced \
item writer: you know the real test's domains, question formats, and the specific \
errors students actually make.

Hard requirements:
- Every item must be ORIGINAL. Never reproduce, paraphrase, or closely imitate a \
real College Board question, passage, or answer set. Invent your own passages, \
names, data, and scenarios.
- Exactly four choices. Exactly one is defensibly correct; the other three must be \
clearly wrong to a careful reader — no "best of two reasonable answers" items.
- Distractors must encode real mistakes (sign errors, percent-of-the-wrong-base, \
answering the un-asked quantity, a plausible-but-unsupported inference), not \
filler.
- Math: verify your own arithmetic before committing to an answer key. If a \
question has two valid solutions, more than one choice satisfies it, or an \
extraneous root is not excluded, discard it and write a different one.
- Reading & Writing: the passage must contain everything needed. Conventions items \
use a blank (______) and the choices are the candidate replacements.
- Explanations state why the key is right AND why the most tempting wrong choice \
is wrong. Two or three sentences.
- Write plain text, not LaTeX. Use Unicode for math (x², √, π, ≥, ÷, −).

Difficulty: 1 = one step, most students get it. 2 = two or three steps, or a \
common trap. 3 = multi-step, or requires noticing something (an extraneous root, \
a conditional probability, an assumption a text depends on).
"""

VERIFY_SYSTEM = """\
You are a test-item reviewer. You will be shown SAT-style practice questions with \
their answer choices, but NOT their answer keys.

For each question, independently solve it and report the index of the choice you \
believe is correct. Then judge whether the item is sound: exactly one choice is \
defensibly correct, the question is unambiguous, and nothing needed to answer it \
is missing.

Be strict. Mark an item unsound if two choices could be argued, if a math item has \
an unexcluded extraneous root, if the arithmetic does not work out to any choice, \
or if a reading item depends on information the passage does not supply. Solve the \
math yourself rather than trusting the item's framing.
"""


class GenerationError(RuntimeError):
    """Raised for a missing key, a refusal, or an unusable response."""


@dataclass
class GenerationReport:
    """Outcome of one generation run, for the CLI and the API response."""

    accepted: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)  # {reason, prompt}
    requested: int = 0

    def note(self, reason: str, question: dict) -> None:
        self.rejected.append({"reason": reason, "prompt": (question.get("prompt") or "")[:120]})

    def as_dict(self) -> dict:
        return {
            "requested": self.requested,
            "accepted": len(self.accepted),
            "rejected": self.rejected,
            "questions": self.accepted,
        }


# ────────────────────────────── client ──────────────────────────────

def _client():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise GenerationError(
            "ANTHROPIC_API_KEY is not set. Export it in the shell that runs this "
            "(export ANTHROPIC_API_KEY=sk-ant-...) and try again."
        )
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover
        raise GenerationError("The anthropic package is not installed: pip3 install anthropic") from exc
    return anthropic.Anthropic()


def _structured_call(client, *, system: str, user: str, schema: dict, effort: str) -> dict:
    """One request whose response is guaranteed to match `schema`."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        output_config={"format": {"type": "json_schema", "schema": schema}, "effort": effort},
        messages=[{"role": "user", "content": user}],
    )

    # Opus 5 can decline a request; that arrives as a 200 with stop_reason
    # "refusal" and possibly empty content, so check it before reading blocks.
    if response.stop_reason == "refusal":
        detail = getattr(response.stop_details, "explanation", None) or "no explanation given"
        raise GenerationError(f"The model declined this request ({detail}).")
    if response.stop_reason == "max_tokens":
        raise GenerationError(
            "Response hit max_tokens before finishing. Lower --count or reduce BATCH_SIZE."
        )

    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        raise GenerationError(f"No text content in response (stop_reason={response.stop_reason}).")
    return json.loads(text)


# ────────────────────────────── validation ──────────────────────────────

def _normalize(text: str) -> str:
    """Collapse a prompt to a comparable form for duplicate detection."""
    text = unicodedata.normalize("NFKD", text or "").lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _read_bank(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data.get("questions", []) if isinstance(data, dict) else []


def load_builtin() -> list[dict]:
    return _read_bank(BUILTIN_PATH)


def load_all() -> list[dict]:
    """Every question the app knows about — what the match server serves from."""
    return load_builtin() + load_generated()


def existing_prompts() -> set[str]:
    """Normalized prompts already in the bank, so we don't generate near-duplicates."""
    seen = {_normalize(q.get("prompt", "")) for q in load_all()}
    return {s for s in seen if s}


def validate(question: dict, report: GenerationReport, seen: set[str]) -> bool:
    """Reject anything structurally unusable. Schema guarantees types, not sense."""
    prompt = (question.get("prompt") or "").strip()
    choices = question.get("choices") or []

    if not prompt:
        report.note("empty prompt", question)
        return False
    if len(choices) != 4 or any(not str(c).strip() for c in choices):
        report.note(f"needs exactly 4 non-empty choices, got {len(choices)}", question)
        return False
    if len({_normalize(str(c)) for c in choices}) != 4:
        report.note("duplicate answer choices", question)
        return False
    if not question.get("explanation", "").strip():
        report.note("missing explanation", question)
        return False

    section = question.get("section")
    if question.get("domain") not in DOMAINS.get(section, []):
        report.note(f"domain {question.get('domain')!r} does not belong to section {section!r}", question)
        return False

    key = _normalize(prompt)
    if key in seen:
        report.note("duplicate of an existing question", question)
        return False
    seen.add(key)
    return True


def _verify(client, questions: list[dict], report: GenerationReport, effort: str) -> list[dict]:
    """Drop questions whose answer key an independent solve disagrees with."""
    if not questions:
        return []

    payload = []
    for i, q in enumerate(questions):
        payload.append(
            {
                "index": i,
                "section": q["section"],
                "passage": q.get("passage") or "",
                "notes": q.get("notes") or [],
                "table": q.get("table") or {"headers": [], "rows": []},
                "prompt": q["prompt"],
                "choices": q["choices"],  # answer key deliberately omitted
            }
        )

    result = _structured_call(
        client,
        system=VERIFY_SYSTEM,
        user="Solve and review each question.\n\n" + json.dumps(payload, ensure_ascii=False, indent=2),
        schema=VERIFY_SCHEMA,
        effort=effort,
    )

    verdicts = {r["index"]: r for r in result.get("results", [])}
    kept = []
    for i, question in enumerate(questions):
        verdict = verdicts.get(i)
        if verdict is None:
            report.note("verifier returned no verdict", question)
            continue
        if not verdict["sound"]:
            report.note(f"verifier flagged the item: {verdict.get('issue') or 'unsound'}", question)
            continue
        if verdict["answer"] != question["answer"]:
            report.note(
                f"answer key disputed (author said {question['answer']}, verifier said {verdict['answer']})",
                question,
            )
            continue
        kept.append(question)
    return kept


# ────────────────────────────── storage ──────────────────────────────

def load_generated() -> list[dict]:
    return _read_bank(GENERATED_PATH)


def save_generated(questions: list[dict]) -> None:
    GENERATED_PATH.parent.mkdir(parents=True, exist_ok=True)
    GENERATED_PATH.write_text(
        json.dumps({"version": 1, "questions": questions}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_imported() -> list[dict]:
    return _read_bank(IMPORTED_PATH)


def save_imported(questions: list[dict]) -> None:
    IMPORTED_PATH.parent.mkdir(parents=True, exist_ok=True)
    IMPORTED_PATH.write_text(
        json.dumps({"version": 1, "questions": questions}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def clear_imported() -> None:
    save_imported([])


# ────────────────────────────── import (no LLM) ──────────────────────────────
# Bring-your-own questions: the caller supplies everything, including the
# answer key, so there's no independent-verification pass the way generated
# questions get — only structural checks (four distinct choices, a valid
# answer index, no duplicate of something already in the bank).

def _validate_import(question: dict, report: GenerationReport, seen: set[str]) -> bool:
    prompt = (question.get("prompt") or "").strip()
    choices = [str(c).strip() for c in (question.get("choices") or [])]

    if not prompt:
        report.note("empty prompt", question)
        return False
    if len(choices) != 4 or any(not c for c in choices):
        report.note(f"needs exactly 4 non-empty choices, got {len(choices)}", question)
        return False
    if len({_normalize(c) for c in choices}) != 4:
        report.note("duplicate answer choices", question)
        return False
    answer = question.get("answer")
    if not isinstance(answer, int) or not (0 <= answer <= 3):
        report.note("answer must be an index 0-3 (or a letter A-D)", question)
        return False
    if question.get("section") not in ("math", "rw"):
        report.note("section must be 'math' or 'rw'", question)
        return False

    key = _normalize(prompt)
    if key in seen:
        report.note("duplicate of an existing question", question)
        return False
    seen.add(key)
    return True


def import_questions(raw_questions: list[dict]) -> GenerationReport:
    """Validate and store user-submitted questions into data/imported.json."""
    report = GenerationReport(requested=len(raw_questions))
    seen = existing_prompts() | {_normalize(q.get("prompt", "")) for q in load_imported()}
    accepted: list[dict] = []

    for raw in raw_questions:
        domain = (raw.get("domain") or "").strip()
        section = raw.get("section") or ("math" if domain in DOMAINS["math"] else ("rw" if domain in DOMAINS["rw"] else None))
        question = {
            "section": section,
            "domain": domain or "Imported",
            "skill": (raw.get("skill") or "Imported").strip() or "Imported",
            "difficulty": raw.get("difficulty") if raw.get("difficulty") in (1, 2, 3) else 2,
            "passage": raw.get("passage") or "",
            "notes": raw.get("notes") or [],
            "table": raw.get("table") or {"headers": [], "rows": []},
            "prompt": raw.get("prompt") or "",
            "choices": raw.get("choices") or [],
            "answer": raw.get("answer"),
            "explanation": raw.get("explanation") or "",
        }
        if _validate_import(question, report, seen):
            accepted.append(question)

    _assign_ids(accepted, load_imported())
    for question in accepted:
        question["id"] = "imp-" + question["id"].split("gen-", 1)[-1]
        question["imported"] = True

    if accepted:
        save_imported(load_imported() + accepted)
    report.accepted = accepted
    return report


def _assign_ids(questions: list[dict], existing: list[dict]) -> None:
    used = {q.get("id") for q in existing}
    counter = len(existing) + 1
    for question in questions:
        slug = re.sub(r"[^a-z0-9]+", "-", question["skill"].lower()).strip("-")[:28]
        while True:
            candidate = f"gen-{question['section']}-{slug}-{counter}"
            counter += 1
            if candidate not in used:
                break
        used.add(candidate)
        question["id"] = candidate
        question["generated"] = True


# ────────────────────────────── entry point ──────────────────────────────

def _author_request(count: int, section: str | None, domain: str | None, skills: list[str] | None) -> str:
    if domain:
        scope = f"All {count} questions must be in the {domain} domain."
        pool = skills or KNOWN_SKILLS.get(domain, [])
    elif section:
        label = "Math" if section == "math" else "Reading & Writing"
        scope = (
            f"All {count} questions must be in the {label} section. "
            f"Spread them across these domains: {', '.join(DOMAINS[section])}."
        )
        pool = skills or [s for d in DOMAINS[section] for s in KNOWN_SKILLS[d]]
    else:
        scope = (
            f"Write {count} questions spread across both sections and all eight domains: "
            f"{', '.join(ALL_DOMAINS)}."
        )
        pool = skills or [s for d in ALL_DOMAINS for s in KNOWN_SKILLS[d]]

    return (
        f"{scope}\n\n"
        f"Prefer these skill labels where they fit, so the app's per-skill tracking stays "
        f"consistent: {', '.join(pool)}. If an item genuinely covers something else, use a "
        f"short new label in the same style.\n\n"
        f"Mix difficulty: roughly a quarter at 1, half at 2, a quarter at 3. Make the items "
        f"distinct from one another — different scenarios, different numbers, different traps. "
        f"Leave `passage` as an empty string, `notes` as an empty array, and `table` with empty "
        f"headers/rows whenever the question does not need them."
    )


def generate(
    count: int = 10,
    section: str | None = None,
    domain: str | None = None,
    skills: list[str] | None = None,
    *,
    verify: bool = True,
    effort: str = "high",
    progress=None,
) -> GenerationReport:
    """Generate, validate, verify and ID-stamp questions. Does not write to disk."""
    if domain and domain not in ALL_DOMAINS:
        raise GenerationError(f"Unknown domain {domain!r}. Known: {', '.join(ALL_DOMAINS)}")
    if domain:
        section = "math" if domain in DOMAINS["math"] else "rw"
    if section and section not in DOMAINS:
        raise GenerationError(f"Unknown section {section!r}. Use 'math' or 'rw'.")

    say = progress or (lambda _msg: None)
    client = _client()
    report = GenerationReport(requested=count)
    seen = existing_prompts()

    remaining = count
    while remaining > 0:
        batch_size = min(BATCH_SIZE, remaining)
        remaining -= batch_size
        say(f"authoring {batch_size} question(s)…")

        result = _structured_call(
            client,
            system=AUTHOR_SYSTEM,
            user=_author_request(batch_size, section, domain, skills),
            schema=BATCH_SCHEMA,
            effort=effort,
        )
        batch = [q for q in result.get("questions", []) if validate(q, report, seen)]

        if verify and batch:
            say(f"verifying {len(batch)} question(s) against an independent solve…")
            batch = _verify(client, batch, report, effort)

        report.accepted.extend(batch)
        say(f"kept {len(batch)} of {batch_size}")

    _assign_ids(report.accepted, load_generated())
    return report


def generate_and_save(**kwargs) -> GenerationReport:
    """Generate and append to data/generated.json."""
    report = generate(**kwargs)
    if report.accepted:
        save_generated(load_generated() + report.accepted)
    return report
