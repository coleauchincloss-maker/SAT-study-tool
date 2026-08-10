#!/usr/bin/env python3
"""Bulk-generate SAT Quest practice questions with parametric templates —
no API key, no cost, no waiting. Each template picks random numbers or
scenarios and computes the correct answer in code, so the key is always
right by construction (unlike an LLM, which needs a second verification
pass to catch mistakes).

    python3 template_gen.py --count 3000                 # spread across everything
    python3 template_gen.py --count 500 --section math
    python3 template_gen.py --count 200 --domain "Geometry & Trig"
    python3 template_gen.py --stats

Questions land in data/generated.json, the same file satquest_gen.py (the
Claude-backed generator) writes to — the app doesn't know or care which
generator produced a question. Re-running is safe: near-duplicate prompts
are skipped.

Scope, honestly: this covers Math (all four domains) and Standard English
Conventions well, because a computed number or a grammar rule has a single
checkable right answer. Information & Ideas, Craft & Structure passages, and
Expression of Ideas need real prose to be worth answering — those still go
through satquest_gen.py (Claude) when you have an ANTHROPIC_API_KEY set.
Craft & Structure gets a templated "words in context" vocabulary set here,
since that format doesn't need a full passage.
"""

from __future__ import annotations

import argparse
import math
import random
import re
import sys
from collections import Counter
from fractions import Fraction

import satquest_gen as sg

# ────────────────────────────── shared helpers ──────────────────────────────

NAMES = ["Maria", "Jordan", "Priya", "Alex", "Sam", "Devon", "Wei", "Noah",
         "Ava", "Liam", "Ken", "Sofia", "Omar", "Grace", "Tariq", "Elena"]

UNITS_COUNTABLE = [("delivery", "deliveries"), ("ticket", "tickets"), ("widget", "widgets"),
                    ("book", "books"), ("mile", "miles"), ("hour", "hours"), ("plant", "plants")]


def blank(section: str, domain: str, skill: str, difficulty: int, prompt: str,
          choices: list[str], answer: int, explanation: str, passage: str = "",
          table: dict | None = None) -> dict:
    return {
        "section": section, "domain": domain, "skill": skill, "difficulty": difficulty,
        "passage": passage, "notes": [], "table": table or {"headers": [], "rows": []},
        "prompt": prompt, "choices": [str(c) for c in choices], "answer": answer,
        "explanation": explanation,
    }


def fmt(x) -> str:
    """Format a number without a trailing .0, and fractions cleanly."""
    if isinstance(x, Fraction):
        if x.denominator == 1:
            return str(x.numerator)
        return f"{x.numerator}/{x.denominator}"
    if isinstance(x, float):
        if x == int(x):
            return str(int(x))
        return f"{x:.2f}".rstrip("0").rstrip(".")
    return str(x)


def build_choices(rng: random.Random, correct, distractors: list) -> tuple[list[str], int]:
    """Shuffle a correct value in among distractors, deduping by displayed text.

    Raises ValueError if fewer than 3 distinct distractors are available — the
    caller (generate_templated) treats that as a failed draw and tries again
    with fresh random parameters, rather than looping forever trying to pad
    with filler that's already been used.
    """
    seen = {fmt(correct)}
    pool = []
    for d in distractors:
        text = fmt(d)
        if text not in seen:
            seen.add(text)
            pool.append(text)
    attempts = 0
    while len(pool) < 3 and isinstance(correct, (int, float, Fraction)) and attempts < 20:
        attempts += 1
        bump = rng.choice([-5, -4, -3, -2, 2, 3, 4, 5])
        candidate = correct + (Fraction(bump, 1) if isinstance(correct, Fraction) else bump)
        filler = fmt(candidate)
        if filler not in seen:
            seen.add(filler)
            pool.append(filler)
    if len(pool) < 3:
        raise ValueError("could not build 3 distinct distractors")
    choices = [fmt(correct)] + pool[:3]
    rng.shuffle(choices)
    return choices, choices.index(fmt(correct))


def pt(k: int, triple: tuple[int, int, int]) -> tuple[int, int, int]:
    a, b, c = triple
    return a * k, b * k, c * k


TRIPLES = [(3, 4, 5), (5, 12, 13), (8, 15, 17), (7, 24, 25), (20, 21, 29), (9, 40, 41)]

# ────────────────────────────────── Algebra ──────────────────────────────────

def t_linear_one_two_step(rng: random.Random) -> dict:
    a = rng.choice([2, 3, 4, 5, 6, 7, 8, 9, 12])
    x = rng.randint(-15, 15)
    b = rng.randint(-25, 25)
    c = a * x + b
    prompt = f"If {a}x {'+ ' + str(b) if b >= 0 else '- ' + str(-b)} = {c}, what is the value of x?"
    distractors = [x + rng.choice([1, -1, 2]), -x, (c - b) if b else x + a, x * -1 + 2]
    choices, ans = build_choices(rng, x, distractors)
    step = f"Subtract {b}" if b >= 0 else f"Add {-b}"
    return blank("math", "Algebra", "Linear equations in one variable", 1, prompt, choices, ans,
                 f"{step} from both sides to get {a}x = {c - b}, then divide by {a} to get x = {x}.")


def t_linear_function_slope(rng: random.Random) -> dict:
    x1, x2 = rng.randint(-8, 8), rng.randint(-8, 8)
    while x2 == x1:
        x2 = rng.randint(-8, 8)
    slope = Fraction(rng.randint(-6, 6), rng.randint(1, 4))
    if slope == 0:
        slope = Fraction(2, 1)
    y1 = rng.randint(-10, 10)
    y2 = y1 + slope * (x2 - x1)
    if y2.denominator != 1:
        # keep the points at integer coordinates for a clean prompt
        y2 = y1 + int(slope) * (x2 - x1) if slope.denominator == 1 else y1 + round(slope) * (x2 - x1)
        slope = Fraction(y2 - y1, x2 - x1) if x2 != x1 else Fraction(0)
    prompt = f"A line passes through ({x1}, {y1}) and ({x2}, {y2}). What is its slope?"
    reciprocal = Fraction(x2 - x1, y2 - y1) if (y2 - y1) != 0 else Fraction(0)
    distractors = [reciprocal, -slope, Fraction(y1 - y2, x2 - x1) if (x2 - x1) else Fraction(1)]
    choices, ans = build_choices(rng, slope, distractors)
    return blank("math", "Algebra", "Linear functions", 1, prompt, choices, ans,
                 f"Slope = (y2 − y1)/(x2 − x1) = ({y2} − {y1})/({x2} − {x1}) = {fmt(slope)}.")


def t_system_two_linear(rng: random.Random) -> dict:
    x = rng.randint(-10, 15)
    y = rng.randint(-10, 15)
    s = x + y
    d = x - y
    ask_x = rng.random() < 0.5
    prompt = f"If x + y = {s} and x − y = {d}, what is the value of {'x' if ask_x else 'y'}?"
    target = x if ask_x else y
    other = y if ask_x else x
    distractors = [other, s, d, target + rng.choice([1, -1, 2, -2])]
    choices, ans = build_choices(rng, target, distractors)
    return blank("math", "Algebra", "Systems of two linear equations", 2, prompt, choices, ans,
                 f"Adding the equations gives 2x = {s + d}, so x = {x}. Substituting back gives y = {y}.")


def t_linear_inequality(rng: random.Random) -> dict:
    a = rng.choice([2, 3, 4, 5, 6])
    b = rng.randint(-15, 15)
    x0 = rng.randint(-10, 10)
    c = a * x0 + b
    prompt = f"If {a}x {'+ ' + str(b) if b >= 0 else '- ' + str(-b)} > {c}, what is the smallest integer value of x?"
    correct = x0 + 1
    distractors = [x0, x0 - 1, x0 + 2]
    choices, ans = build_choices(rng, correct, distractors)
    return blank("math", "Algebra", "Linear inequalities", 2, prompt, choices, ans,
                 f"Subtract {b} then divide by {a}: x > {x0}. The smallest integer greater than {x0} is {correct}.")


def t_linear_model_context(rng: random.Random) -> dict:
    name = rng.choice(NAMES)
    noun, nouns = rng.choice(UNITS_COUNTABLE)
    fee = rng.choice([15, 20, 25, 30, 40, 50])
    rate = rng.choice([3, 4, 5, 6, 8, 10])
    n = rng.randint(4, 20)
    total = fee + rate * n
    prompt = (f"{name} charges a flat fee of ${fee} plus ${rate} per {noun}. "
              f"What is the total charge for {n} {nouns}?")
    distractors = [fee + rate * (n - 1), rate * n, fee * n]
    choices, ans = build_choices(rng, total, distractors)
    return blank("math", "Algebra", "Linear models in context", 1, prompt, choices, ans,
                 f"Total = flat fee + rate × count = {fee} + {rate}×{n} = {total}.")


def t_interpret_linear_model(rng: random.Random) -> dict:
    name = rng.choice(NAMES)
    item = rng.choice(["car", "laptop", "piece of equipment", "delivery van", "generator"])
    v0 = rng.choice([12000, 15000, 20000, 24000, 30000])
    rate = rng.choice([800, 1000, 1200, 1500, 2000])
    prompt = (f"The value in dollars of {name}'s {item}, t years after purchase, is modeled by "
              f"V = {v0} − {rate}t. What does {rate} represent in this model?")
    correct = f"The value decreases by ${rate} each year."
    distractors = [
        f"The {item} was purchased for ${rate}.",
        f"The {item} will be worthless after {rate} years.",
        f"The value increases by ${rate} each year.",
    ]
    choices, ans = build_choices(rng, correct, distractors)
    return blank("math", "Algebra", "Interpreting linear models", 2, prompt, choices, ans,
                 f"In V = V0 − rt, the coefficient of t is the rate of change — here, a ${rate}-per-year decrease.")


# ─────────────────────────────── Advanced Math ───────────────────────────────

def t_quadratic_factorable(rng: random.Random) -> dict:
    r1 = rng.randint(-9, 9)
    r2 = rng.randint(-9, 9)
    while r2 == r1:
        r2 = rng.randint(-9, 9)
    b = -(r1 + r2)
    c = r1 * r2
    lhs = f"x{'² + ' if b >= 0 else '² - '}{abs(b)}x {'+ ' + str(c) if c >= 0 else '- ' + str(-c)} = 0"
    prompt = f"What are the solutions to x{lhs[1:]}"
    correct = f"x = {r1} and {r2}"
    distractors = [f"x = {-r1} and {-r2}", f"x = {r1} and {-r2}", f"x = {r2} and {r2}"]
    choices, ans = build_choices(rng, correct, distractors)
    f1 = f"x + {-r1}" if r1 < 0 else f"x − {r1}"
    f2 = f"x + {-r2}" if r2 < 0 else f"x − {r2}"
    return blank("math", "Advanced Math", "Quadratic equations", 2, prompt, choices, ans,
                 f"The equation factors as ({f1})({f2}) = 0, giving x = {r1} and x = {r2}.")


def t_quadratic_vertex(rng: random.Random) -> dict:
    h = rng.randint(-8, 8)
    k = rng.randint(-10, 10)
    sign = "-" if h >= 0 else "+"
    prompt = f"What is the vertex of the parabola y = (x {sign} {abs(h)})² {'+ ' + str(k) if k >= 0 else '- ' + str(-k)}?"
    correct = f"({h}, {k})"
    distractors = [f"({-h}, {k})", f"({h}, {-k})", f"({k}, {h})"]
    choices, ans = build_choices(rng, correct, distractors)
    return blank("math", "Advanced Math", "Quadratic graphs and vertex form", 1, prompt, choices, ans,
                 f"In vertex form y = (x − h)² + k, the vertex is (h, k) = ({h}, {k}).")


def t_exponential_growth(rng: random.Random) -> dict:
    p0 = rng.choice([100, 200, 250, 400, 500, 1000])
    rate = rng.choice([5, 10, 15, 20, 25])
    t = rng.randint(2, 4)
    correct = round(p0 * (1 + rate / 100) ** t)
    prompt = f"A population of {p0} grows by {rate}% each year. Which is closest to the population after {t} years?"
    linear = round(p0 + p0 * (rate / 100) * t)
    wrong_exp = round(p0 * (1 + rate / 100) ** (t - 1))
    decay = round(p0 * (1 - rate / 100) ** t)
    choices, ans = build_choices(rng, correct, [linear, wrong_exp, decay])
    return blank("math", "Advanced Math", "Exponential growth", 3, prompt, choices, ans,
                 f"Population = {p0}(1 + {rate}/100)^{t} ≈ {correct}.")


def t_radical_equation(rng: random.Random) -> dict:
    b = rng.randint(2, 9)
    a = rng.choice([v for v in range(-10, 11) if v != 0])
    x = b * b - a
    inner = f"x + {a}" if a > 0 else f"x - {abs(a)}"
    prompt = f"If √({inner}) = {b}, what is the value of x?"
    distractors = [b - a, b * b + a, b + a]
    choices, ans = build_choices(rng, x, distractors)
    return blank("math", "Advanced Math", "Radical equations", 2, prompt, choices, ans,
                 f"Square both sides: {inner} = {b}² = {b*b}, so x = {x}. Checking, {inner.replace('x', str(x))} = {b*b} ≥ 0, so this root is valid.")


def t_polynomial_factor_zeros(rng: random.Random) -> dict:
    roots = rng.sample(range(-6, 7), 3)
    factors = " ".join(f"(x {'- ' + str(r) if r >= 0 else '+ ' + str(-r)})" for r in roots)
    prompt = f"What is the sum of the zeros of {factors} = 0?"
    s = sum(roots)
    distractors = [-s, math.prod(roots) if abs(math.prod(roots)) < 500 else s + 3, s + roots[0]]
    choices, ans = build_choices(rng, s, distractors)
    return blank("math", "Advanced Math", "Polynomial factors and zeros", 2, prompt, choices, ans,
                 f"The zeros are x = {roots[0]}, {roots[1]}, {roots[2]} (from each factor set to 0), which sum to {s}.")


def t_exponent_rules(rng: random.Random) -> dict:
    a = rng.randint(2, 8)
    b = rng.randint(2, 8)
    c = rng.randint(1, a + b - 1)
    result = a + b - c
    prompt = f"Which expression is equivalent to (x^{a} · x^{b}) / x^{c}?"
    correct = f"x^{result}"
    distractors = [f"x^{a + b + c}", f"x^{a * b - c}", f"x^{a - b + c}"]
    choices, ans = build_choices(rng, correct, distractors)
    return blank("math", "Advanced Math", "Exponent rules", 1, prompt, choices, ans,
                 f"Multiplying powers adds exponents ({a}+{b}={a+b}); dividing subtracts ({a+b}−{c}={result}).")


def t_rational_equation(rng: random.Random) -> dict:
    x = rng.choice([r for r in range(-12, 13) if r != 0])
    a = rng.randint(2, 10)
    b = Fraction(a, x)
    prompt = f"If {a}/x = {fmt(b)}, what is the value of x?"
    distractors = [a * b, -x, Fraction(1, 1) / b if b != 0 else Fraction(1)]
    choices, ans = build_choices(rng, x, distractors)
    return blank("math", "Advanced Math", "Rational equations", 2, prompt, choices, ans,
                 f"Cross-multiplying: {a} = {fmt(b)} · x, so x = {a} ÷ {fmt(b)} = {x}.")


def t_discriminant(rng: random.Random) -> dict:
    kind = rng.choice(["two", "one", "none"])
    a = rng.randint(1, 4)
    if kind == "two":
        b, c = rng.randint(5, 10), rng.randint(-6, 0)
    elif kind == "one":
        b = rng.randint(2, 8)
        c = Fraction(b * b, 4 * a)
        c = int(c) if c.denominator == 1 else b * b // (4 * a)
        b, c = 2 * a, a  # guarantees discriminant 0: b^2-4ac = 4a^2-4a*a = 0
    else:
        b, c = rng.randint(0, 3), rng.randint(5, 12)
    disc = b * b - 4 * a * c
    label = "two real solutions" if disc > 0 else ("one real solution" if disc == 0 else "no real solutions")
    prompt = f"How many real solutions does {a}x² {'+ ' + str(b) + 'x' if b >= 0 else '- ' + str(-b) + 'x'} {'+ ' + str(c) if c >= 0 else '- ' + str(-c)} = 0 have?"
    all_opts = ["two real solutions", "one real solution", "no real solutions", "infinitely many solutions"]
    distractors = [o for o in all_opts if o != label]
    choices, ans = build_choices(rng, label, distractors)
    return blank("math", "Advanced Math", "Discriminant and number of solutions", 3, prompt, choices, ans,
                 f"The discriminant is b² − 4ac = {b}² − 4({a})({c}) = {disc}, which is "
                 f"{'positive' if disc > 0 else ('zero' if disc == 0 else 'negative')}, giving {label}.")


# ────────────────────────────── Problem-Solving & Data ──────────────────────────────

def t_percentages(rng: random.Random) -> dict:
    n = rng.choice([40, 60, 80, 120, 150, 200, 250, 400])
    p = rng.choice([5, 10, 15, 20, 25, 30, 40, 60, 75])
    result = round(n * p / 100)
    prompt = f"What is {p}% of {n}?"
    distractors = [round(n * (p / 100) * 10), round(n / p) if p else n, n - result]
    choices, ans = build_choices(rng, result, distractors)
    return blank("math", "Problem-Solving & Data", "Percentages", 1, prompt, choices, ans,
                 f"{p}% of {n} = {p}/100 × {n} = {result}.")


def t_percent_change(rng: random.Random) -> dict:
    old = rng.choice([40, 50, 60, 80, 100, 120, 150, 200])
    pct = rng.choice([10, 20, 25, 30, 40, 50])
    up = rng.random() < 0.5
    new = round(old * (1 + pct / 100)) if up else round(old * (1 - pct / 100))
    prompt = f"A value changes from {old} to {new}. What is the percent change?"
    correct = f"{pct}% {'increase' if up else 'decrease'}"
    distractors = [f"{pct}% {'decrease' if up else 'increase'}", f"{round(abs(new-old)/new*100)}% {'increase' if up else 'decrease'}", f"{pct*2}% {'increase' if up else 'decrease'}"]
    choices, ans = build_choices(rng, correct, distractors)
    return blank("math", "Problem-Solving & Data", "Percent change", 2, prompt, choices, ans,
                 f"Percent change = (new − old)/old × 100 = ({new} − {old})/{old} × 100 = {pct}% {'increase' if up else 'decrease'}.")


def t_rates_unit_rate(rng: random.Random) -> dict:
    name = rng.choice(NAMES)
    hours = rng.choice([2, 2.5, 3, 4, 5, 6])
    rate = rng.choice([40, 45, 50, 55, 60, 65, 70])
    dist = hours * rate
    prompt = f"{name} travels {fmt(dist)} miles in {fmt(hours)} hours at a constant speed. What is the speed in miles per hour?"
    distractors = [dist * hours, dist / (hours + 1) if hours + 1 else rate, rate + 5]
    choices, ans = build_choices(rng, rate, distractors)
    return blank("math", "Problem-Solving & Data", "Rates and unit rates", 1, prompt, choices, ans,
                 f"Speed = distance ÷ time = {fmt(dist)} ÷ {fmt(hours)} = {rate} mph.")


def t_ratios_proportions(rng: random.Random) -> dict:
    a, b = rng.choice([(2, 3), (3, 4), (3, 5), (4, 5), (2, 5), (5, 8)])
    k = rng.randint(2, 8)
    given = a * k
    want = b * k
    prompt = f"A recipe uses a ratio of {a} cups flour to {b} cups sugar. How much sugar is needed for {given} cups of flour?"
    distractors = [given, a * k + b, want + a]
    choices, ans = build_choices(rng, want, distractors)
    return blank("math", "Problem-Solving & Data", "Ratios and proportions", 1, prompt, choices, ans,
                 f"The scale factor is {given}/{a} = {k}, so sugar = {b} × {k} = {want} cups.")


def t_mean_center(rng: random.Random) -> dict:
    nums = [rng.randint(1, 40) for _ in range(rng.choice([4, 5, 6]))]
    mean = Fraction(sum(nums), len(nums))
    prompt = f"What is the mean of the data set: {', '.join(map(str, nums))}?"
    sorted_nums = sorted(nums)
    mid = len(nums) // 2
    median = sorted_nums[mid] if len(nums) % 2 else Fraction(sorted_nums[mid - 1] + sorted_nums[mid], 2)
    distractors = [median, Fraction(sum(nums), len(nums) - 1), max(nums)]
    choices, ans = build_choices(rng, mean, distractors)
    mean_str = fmt(mean) if mean.denominator != 1 else str(int(mean))
    return blank("math", "Problem-Solving & Data", "Mean and center", 1, prompt, choices, ans,
                 f"Mean = sum ÷ count = {sum(nums)} ÷ {len(nums)} = {mean_str}.")


def t_two_way_table(rng: random.Random) -> dict:
    a, b = rng.randint(15, 40), rng.randint(15, 40)
    c, d = rng.randint(15, 40), rng.randint(15, 40)
    row1, row2 = a + b, c + d
    col1, col2 = a + c, b + d
    total = row1 + row2
    which = rng.choice(["a", "b", "c", "d"])
    cell = {"a": a, "b": b, "c": c, "d": d}[which]
    row_total = row1 if which in "ab" else row2
    prompt = (f"Of {total} survey respondents, {row1} own a car and {row2} do not. Among car owners, {a} "
              f"also own a bike, and {b} do not. Among non-owners, {c} own a bike and {d} do not. "
              f"What is the probability that a randomly chosen respondent {'owns a car and owns a bike' if which=='a' else ('owns a car and does not own a bike' if which=='b' else ('does not own a car and owns a bike' if which=='c' else 'owns neither'))}?")
    prob = Fraction(cell, total)
    distractors = [Fraction(cell, row_total), Fraction(row_total, total), Fraction(total - cell, total)]
    choices, ans = build_choices(rng, prob, distractors)
    return blank("math", "Problem-Solving & Data", "Two-way tables and probability", 2, prompt, choices, ans,
                 f"That cell has {cell} of the {total} total respondents, so the probability is {cell}/{total}.")


def t_scatterplot_model(rng: random.Random) -> dict:
    name = rng.choice(NAMES)
    x_unit = rng.choice(["study hours per week", "years of experience", "weekly training hours"])
    y_unit = rng.choice(["test score", "salary in thousands", "race time in minutes"])
    slope = rng.choice([2, 3, 4, 5, -2, -3])
    verb = "increases" if slope > 0 else "decreases"
    noun = "increase" if slope > 0 else "decrease"
    prompt = (f"{name} fits a line to data relating {x_unit} (x) to {y_unit} (y) and finds a slope of {slope}. "
              f"What does this slope indicate?")
    correct = f"On average, {y_unit} {verb} by {abs(slope)} for each additional unit of {x_unit}."
    distractors = [
        f"On average, {y_unit} {'decreases' if slope > 0 else 'increases'} by {abs(slope)} for each additional unit of {x_unit}.",
        f"{x_unit.capitalize()} has no effect on {y_unit}.",
        f"Every respondent has the same {y_unit} regardless of {x_unit}.",
    ]
    choices, ans = build_choices(rng, correct, distractors)
    article = "an" if noun == "increase" else "a"
    return blank("math", "Problem-Solving & Data", "Scatterplots and models", 2, prompt, choices, ans,
                 f"A slope of {slope} means y changes by {slope} units for each 1-unit increase in x — {article} {noun} of {abs(slope)}.")


def t_inference_samples(rng: random.Random) -> dict:
    topic = rng.choice(["favorite subject", "commute method", "preferred store hours", "streaming service used"])
    n = rng.choice([150, 200, 300, 500, 800])
    prompt = (f"A researcher wants to estimate the {topic} of all students at a large university. "
              f"Which method would produce the most reliable estimate?")
    correct = f"Survey a random sample of {n} students from the full student body."
    distractors = [
        f"Survey the first {n} students who walk into the library.",
        f"Survey {n} members of a single campus club.",
        f"Survey students who volunteer to respond to an online post about the topic.",
    ]
    choices, ans = build_choices(rng, correct, distractors)
    return blank("math", "Problem-Solving & Data", "Inference from samples", 2, prompt, choices, ans,
                 "A random sample of the whole population avoids the selection bias that volunteer or convenience samples introduce.")


# ────────────────────────────────── Geometry & Trig ──────────────────────────────────

def t_circle(rng: random.Random) -> dict:
    r = rng.randint(2, 15)
    want_area = rng.random() < 0.5
    if want_area:
        prompt = f"What is the area of a circle with radius {r}?"
        correct = f"{r*r}π"
        distractors = [f"{2*r}π", f"{r*r*2}π", f"{r}π"]
    else:
        prompt = f"What is the circumference of a circle with radius {r}?"
        correct = f"{2*r}π"
        distractors = [f"{r*r}π", f"{r}π", f"{4*r}π"]
    choices, ans = build_choices(rng, correct, distractors)
    formula = "A = πr²" if want_area else "C = 2πr"
    return blank("math", "Geometry & Trig", "Circles", 1, prompt, choices, ans, f"Using {formula} with r = {r}: {correct}.")


def t_right_triangle_trig(rng: random.Random) -> dict:
    triple = rng.choice(TRIPLES)
    k = rng.randint(1, 4)
    opp, adj, hyp = pt(k, triple)
    func = rng.choice(["sin", "cos", "tan"])
    value = {"sin": Fraction(opp, hyp), "cos": Fraction(adj, hyp), "tan": Fraction(opp, adj)}[func]
    prompt = f"In a right triangle, the side opposite angle θ has length {opp}, the adjacent side has length {adj}, and the hypotenuse has length {hyp}. What is {func}(θ)?"
    other = {"sin": Fraction(adj, hyp), "cos": Fraction(opp, hyp), "tan": Fraction(adj, opp)}
    distractors = list(other.values())
    choices, ans = build_choices(rng, value, distractors)
    return blank("math", "Geometry & Trig", "Right triangle trigonometry", 2, prompt, choices, ans,
                 f"{func}(θ) = {'opposite/hypotenuse' if func=='sin' else ('adjacent/hypotenuse' if func=='cos' else 'opposite/adjacent')} = {fmt(value)}.")


def t_angle_relationships(rng: random.Random) -> dict:
    a1 = rng.randint(30, 100)
    a2 = rng.randint(20, 179 - a1 - 1)
    a3 = 180 - a1 - a2
    prompt = f"In a triangle, two of the angles measure {a1}° and {a2}°. What is the measure of the third angle?"
    distractors = [180 - a1, 180 - a2, a1 + a2]
    choices, ans = build_choices(rng, a3, distractors)
    return blank("math", "Geometry & Trig", "Angle relationships", 1, prompt, choices, ans,
                 f"A triangle's angles sum to 180°, so the third angle is 180° − {a1}° − {a2}° = {a3}°.")


def t_volume(rng: random.Random) -> dict:
    shape = rng.choice(["box", "cylinder", "cone"])
    if shape == "box":
        l, w, h = rng.randint(2, 12), rng.randint(2, 12), rng.randint(2, 12)
        vol = l * w * h
        prompt = f"What is the volume of a rectangular box with dimensions {l}, {w}, and {h}?"
        distractors = [2 * (l * w + w * h + l * h), l * w + h, l + w + h]
    elif shape == "cylinder":
        r, h = rng.randint(2, 8), rng.randint(3, 12)
        vol = f"{r*r*h}π"
        prompt = f"What is the volume of a cylinder with radius {r} and height {h}?"
        distractors = [f"{2*r*h}π", f"{r*h}π", f"{r*r*h*2}π"]
    else:
        r, h = rng.randint(3, 9), rng.randint(3, 12)
        exact = Fraction(r * r * h, 3)
        vol = f"{fmt(exact)}π"
        prompt = f"What is the volume of a cone with radius {r} and height {h}?"
        distractors = [f"{r*r*h}π", f"{fmt(Fraction(r*h,3))}π", f"{fmt(Fraction(r*r*h,2))}π"]
    choices, ans = build_choices(rng, vol, distractors)
    formula = {"box": "V = l·w·h", "cylinder": "V = πr²h", "cone": "V = (1/3)πr²h"}[shape]
    return blank("math", "Geometry & Trig", "Volume", 2, prompt, choices, ans, f"Using {formula}: V = {vol}.")


def t_similar_triangles(rng: random.Random) -> dict:
    scale = rng.choice([2, 3, 4, 5])
    small_area = rng.choice([2, 3, 4, 5, 6, 8, 10])
    large_area = small_area * scale * scale
    prompt = f"Two similar triangles have a scale factor of {scale}. If the smaller triangle has area {small_area}, what is the area of the larger triangle?"
    distractors = [small_area * scale, small_area * scale ** 3, small_area + scale]
    choices, ans = build_choices(rng, large_area, distractors)
    return blank("math", "Geometry & Trig", "Similar triangles", 2, prompt, choices, ans,
                 f"Area scales by the square of the scale factor: {small_area} × {scale}² = {large_area}.")


# ───────────────────── extra coverage: official Bluebook sub-skill map ─────────────────────
# The templates above already cover most of the College Board's published Math and
# Reading & Writing sub-categories. These fill the specific gaps: equations of lines,
# systems classification, function notation/transformations, factoring, quadratic
# formula/completing the square, complex numbers, parallel/perpendicular slopes,
# compound growth, probability (simple + conditional), median/range, line-of-best-fit
# prediction, special right triangles, and circle equations.

def t_linear_two_var_equation(rng: random.Random) -> dict:
    m = rng.randint(-6, 6)
    if m == 0:
        m = 2
    x0 = rng.randint(-8, 8)
    b = rng.randint(-12, 12)
    y0 = m * x0 + b
    prompt = f"A line has a slope of {m} and passes through ({x0}, {y0}). What is its equation in slope-intercept form?"
    fmt_eq = lambda mm, bb: f"y = {mm}x {'+ ' + str(bb) if bb >= 0 else '- ' + str(-bb)}"
    correct = fmt_eq(m, b)
    distractors = [fmt_eq(m, -b), fmt_eq(m, y0), f"y = {b}x + {m}"]
    choices, ans = build_choices(rng, correct, distractors)
    return blank("math", "Algebra", "Linear equations in two variables", 2, prompt, choices, ans,
                 f"b = y − mx = {y0} − ({m})({x0}) = {b}, so the equation is {correct}.")


def t_system_number_of_solutions(rng: random.Random) -> dict:
    kind = rng.choice(["one", "none", "infinite"])
    m1 = rng.randint(-5, 5) or 2
    b1 = rng.randint(-10, 10)
    if kind == "one":
        m2 = m1
        while m2 == m1:
            m2 = rng.randint(-5, 5) or 2
        b2 = rng.randint(-10, 10)
    elif kind == "none":
        m2 = m1
        b2 = b1
        while b2 == b1:
            b2 = rng.randint(-10, 10)
    else:
        m2, b2 = m1, b1
    fmt_eq = lambda mm, bb: f"y = {mm}x {'+ ' + str(bb) if bb >= 0 else '- ' + str(-bb)}"
    prompt = f"How many solutions does this system have?\n{fmt_eq(m1, b1)}\n{fmt_eq(m2, b2)}"
    label = {"one": "Exactly one solution", "none": "No solution", "infinite": "Infinitely many solutions"}[kind]
    all_opts = ["Exactly one solution", "No solution", "Infinitely many solutions", "Cannot be determined"]
    distractors = [o for o in all_opts if o != label]
    choices, ans = build_choices(rng, label, distractors)
    reason = {
        "one": "different slopes, so the lines cross exactly once",
        "none": "the same slope but different y-intercepts, so the lines are parallel and never meet",
        "infinite": "the same slope and the same y-intercept, so both equations describe the same line",
    }[kind]
    return blank("math", "Algebra", "Systems of two linear equations", 2, prompt, choices, ans,
                 f"The two equations have {reason}.")


def t_function_notation_eval(rng: random.Random) -> dict:
    a = rng.randint(2, 9)
    b = rng.randint(-10, 10)
    k = rng.randint(-8, 8)
    result = a * k + b
    sign = "+ " + str(b) if b >= 0 else "- " + str(-b)
    prompt = f"If f(x) = {a}x {sign}, what is f({k})?"
    distractors = [a + k + b, a * k - b, a * (k + b)]
    choices, ans = build_choices(rng, result, distractors)
    return blank("math", "Algebra", "Linear functions", 1, prompt, choices, ans,
                 f"f({k}) = {a}({k}) {sign} = {result}.")


def t_factor_expand(rng: random.Random) -> dict:
    p = rng.randint(-9, 9)
    q = rng.randint(-9, 9)
    while q == p:
        q = rng.randint(-9, 9)
    b = p + q
    c = p * q
    fp = f"x + {p}" if p >= 0 else f"x - {-p}"
    fq = f"x + {q}" if q >= 0 else f"x - {-q}"
    prompt = f"Which expression is equivalent to ({fp})({fq})?"
    correct = f"x²{' + ' + str(b) + 'x' if b > 0 else (' - ' + str(-b) + 'x' if b < 0 else '')}{' + ' + str(c) if c >= 0 else ' - ' + str(-c)}"
    distractors = [
        f"x²{' + ' + str(-b) + 'x' if -b > 0 else (' - ' + str(b) + 'x' if -b < 0 else '')}{' + ' + str(c) if c >= 0 else ' - ' + str(-c)}",
        f"x²{' + ' + str(b) + 'x' if b > 0 else (' - ' + str(-b) + 'x' if b < 0 else '')}{' + ' + str(-c) if -c >= 0 else ' - ' + str(c)}",
        f"x² {'+ ' + str(p + q) if p+q>=0 else '- ' + str(-(p+q))}",
    ]
    choices, ans = build_choices(rng, correct, distractors)
    p_disp = f"({p})" if p < 0 else str(p)
    q_disp = f"({q})" if q < 0 else str(q)
    return blank("math", "Advanced Math", "Equivalent expressions", 2, prompt, choices, ans,
                 f"FOIL: the x-coefficient is the sum {p_disp} + {q_disp} = {b}, and the constant is the product {p_disp} × {q_disp} = {c}.")


def t_function_transformation(rng: random.Random) -> dict:
    h = rng.randint(1, 8)
    k = rng.randint(1, 8)
    h_dir = rng.choice(["right", "left"])
    k_dir = rng.choice(["up", "down"])
    inner = f"x - {h}" if h_dir == "right" else f"x + {h}"
    outer = f"+ {k}" if k_dir == "up" else f"- {k}"
    prompt = f"The graph of y = f(x) is shifted {h} unit(s) {h_dir} and {k} unit(s) {k_dir}. What is the new function, in terms of f?"
    correct = f"f({inner}) {outer}"
    wrong_inner = f"x + {h}" if h_dir == "right" else f"x - {h}"
    wrong_outer = f"- {k}" if k_dir == "up" else f"+ {k}"
    distractors = [f"f({wrong_inner}) {outer}", f"f({inner}) {wrong_outer}", f"f({wrong_inner}) {wrong_outer}"]
    choices, ans = build_choices(rng, correct, distractors)
    return blank("math", "Advanced Math", "Function transformations", 3, prompt, choices, ans,
                 f"Shifting {h_dir} means replacing x with (x {'−' if h_dir=='right' else '+'} {h}) inside f; shifting {k_dir} means adding {'+' if k_dir=='up' else '−'}{k} outside f.")


def t_quadratic_formula(rng: random.Random) -> dict:
    a = rng.choice([2, 3])
    r1 = rng.choice([Fraction(n, 2) for n in range(-9, 10) if n % 2 != 0] + list(range(-6, 7)))
    r2 = r1
    while r2 == r1:
        r2 = rng.choice([Fraction(n, 2) for n in range(-9, 10) if n % 2 != 0] + list(range(-6, 7)))
    b = -a * (r1 + r2)
    c = a * r1 * r2
    if b.denominator != 1 or c.denominator != 1:
        return t_quadratic_formula(rng)  # unlucky combo; redraw
    b, c = int(b), int(c)
    prompt = f"What are the solutions to {a}x² {'+ ' + str(b) + 'x' if b >= 0 else '- ' + str(-b) + 'x'} {'+ ' + str(c) if c >= 0 else '- ' + str(-c)} = 0?"
    correct = f"x = {fmt(r1)} and {fmt(r2)}"
    distractors = [f"x = {fmt(-r1)} and {fmt(-r2)}", f"x = {fmt(r1)} and {fmt(r2 + 1)}", f"x = {fmt(r1*2)} and {fmt(r2)}"]
    choices, ans = build_choices(rng, correct, distractors)
    return blank("math", "Advanced Math", "Quadratic formula", 3, prompt, choices, ans,
                 f"Using x = (−b ± √(b²−4ac)) / 2a with a={a}, b={b}, c={c} gives x = {fmt(r1)} and x = {fmt(r2)}.")


def t_completing_square(rng: random.Random) -> dict:
    half_b = rng.randint(-9, 9) or 3
    b = 2 * half_b
    c = rng.randint(-15, 15)
    added = half_b * half_b
    prompt = f"To solve x² {'+ ' + str(b) + 'x' if b >= 0 else '- ' + str(-b) + 'x'} {'+ ' + str(c) if c >= 0 else '- ' + str(-c)} = 0 by completing the square, what value should be added to both sides?"
    distractors = [half_b, b * b, -added]
    choices, ans = build_choices(rng, added, distractors)
    half_b_disp = f"({half_b})" if half_b < 0 else str(half_b)
    return blank("math", "Advanced Math", "Completing the square", 2, prompt, choices, ans,
                 f"Take half the x-coefficient ({b}/2 = {half_b}) and square it: {half_b_disp}² = {added}.")


def t_complex_numbers(rng: random.Random) -> dict:
    a, b = rng.randint(-6, 6) or 1, rng.randint(1, 6)
    c, d = rng.randint(-6, 6) or 1, rng.randint(1, 6)
    op = rng.choice(["add", "multiply"])
    fmt_c = lambda re, im: f"{re} {'+' if im >= 0 else '-'} {abs(im)}i"
    if op == "add":
        real, imag = a + c, b + d
        prompt = f"What is ({fmt_c(a,b)}) + ({fmt_c(c,d)})?"
        distractors = [fmt_c(a - c, b - d), fmt_c(a + c, b - d), fmt_c(a * c, b * d)]
    else:
        real, imag = a * c - b * d, a * d + b * c
        prompt = f"What is ({fmt_c(a,b)})({fmt_c(c,d)})?"
        distractors = [fmt_c(a * c + b * d, a * d + b * c), fmt_c(a * c - b * d, a * d - b * c), fmt_c(a * c, b * d)]
    correct = fmt_c(real, imag)
    choices, ans = build_choices(rng, correct, distractors)
    method = "Add real parts and imaginary parts separately." if op == "add" else "FOIL, then use i² = −1 to simplify."
    return blank("math", "Advanced Math", "Operations with complex numbers", 2, prompt, choices, ans,
                 f"{method} Result: {correct}.")


def t_complex_quadratic(rng: random.Random) -> dict:
    p = rng.randint(-6, 6)
    q = rng.randint(1, 6)
    b = -2 * p
    c = p * p + q * q
    prompt = f"What are the solutions to x² {'+ ' + str(b) + 'x' if b >= 0 else '- ' + str(-b) + 'x'} {'+ ' + str(c) if c >= 0 else '- ' + str(-c)} = 0?"
    correct = f"x = {p} ± {q}i"
    distractors = [f"x = {p} ± {q}", f"x = {-p} ± {q}i", f"x = {p} ± {2*q}i"]
    choices, ans = build_choices(rng, correct, distractors)
    return blank("math", "Advanced Math", "Complex solutions to quadratics", 3, prompt, choices, ans,
                 f"The discriminant b² − 4ac = {b*b - 4*c} is negative, so the solutions are complex: x = {p} ± {q}i.")


def t_parallel_perpendicular(rng: random.Random) -> dict:
    m = Fraction(rng.choice([n for n in range(-6, 7) if n != 0]), rng.choice([1, 2, 3]))
    want_parallel = rng.random() < 0.5
    correct = m if want_parallel else -1 / m
    other = -1 / m if want_parallel else m
    prompt = f"A line has a slope of {fmt(m)}. What is the slope of a line {'parallel' if want_parallel else 'perpendicular'} to it?"
    distractors = [other, 1 / m, -m]
    choices, ans = build_choices(rng, correct, distractors)
    rule = "Parallel lines have equal slopes." if want_parallel else "Perpendicular lines have slopes that are negative reciprocals of each other."
    return blank("math", "Algebra", "Parallel and perpendicular lines", 2, prompt, choices, ans, rule)


def t_compound_growth_decay(rng: random.Random) -> dict:
    p = rng.choice([500, 800, 1000, 1500, 2000, 2500])
    r = rng.choice([2, 3, 4, 5, 6, 8])
    t = rng.randint(2, 5)
    grow = rng.random() < 0.5
    value = round(p * (1 + r / 100) ** t) if grow else round(p * (1 - r / 100) ** t)
    verb = "grows" if grow else "depreciates"
    prompt = f"An investment of ${p} {verb} at an annual rate of {r}%, compounded annually. Which is closest to its value after {t} years?"
    linear = round(p * (1 + r / 100 * t)) if grow else round(p * (1 - r / 100 * t))
    off_by_year = round(p * (1 + r / 100) ** (t - 1)) if grow else round(p * (1 - r / 100) ** (t - 1))
    flipped = round(p * (1 - r / 100) ** t) if grow else round(p * (1 + r / 100) ** t)
    choices, ans = build_choices(rng, value, [linear, off_by_year, flipped])
    return blank("math", "Problem-Solving & Data", "Compound growth and decay", 2, prompt, choices, ans,
                 f"Value = {p}(1 {'+' if grow else '-'} {r}/100)^{t} ≈ ${value}.")


def t_simple_probability(rng: random.Random) -> dict:
    colors = rng.sample(["red", "blue", "green", "yellow", "purple"], 3)
    counts = [rng.randint(3, 12) for _ in range(3)]
    total = sum(counts)
    target = rng.randint(0, 2)
    prompt = f"A bag contains {counts[0]} {colors[0]} marbles, {counts[1]} {colors[1]} marbles, and {counts[2]} {colors[2]} marbles. What is the probability of randomly drawing a {colors[target]} marble?"
    prob = Fraction(counts[target], total)
    other_totals = [c for i, c in enumerate(counts) if i != target]
    distractors = [Fraction(counts[target], sum(other_totals)), Fraction(sum(other_totals), total), Fraction(other_totals[0], total)]
    choices, ans = build_choices(rng, prob, distractors)
    return blank("math", "Problem-Solving & Data", "Simple probability", 1, prompt, choices, ans,
                 f"P({colors[target]}) = {colors[target]} count ÷ total = {counts[target]}/{total}.")


def t_conditional_probability(rng: random.Random) -> dict:
    a, b = rng.randint(10, 40), rng.randint(10, 40)
    c, d = rng.randint(10, 40), rng.randint(10, 40)
    row1 = a + b
    total = a + b + c + d
    prompt = (f"Of {total} survey respondents, {row1} own a car; among them, {a} also own a bike and {b} do not. "
              f"Given that a randomly chosen respondent owns a car, what is the probability they also own a bike?")
    prob = Fraction(a, row1)
    distractors = [Fraction(a, total), Fraction(b, row1), Fraction(a + c, total)]
    choices, ans = build_choices(rng, prob, distractors)
    return blank("math", "Problem-Solving & Data", "Conditional probability", 2, prompt, choices, ans,
                 f"Restrict to car owners only ({row1} people); {a} of them own a bike, so P(bike | car) = {a}/{row1}.")


def t_median_range(rng: random.Random) -> dict:
    nums = sorted(rng.sample(range(1, 60), rng.choice([5, 6, 7])))
    want_median = rng.random() < 0.5
    n = len(nums)
    if want_median:
        value = Fraction(nums[n // 2]) if n % 2 else Fraction(nums[n // 2 - 1] + nums[n // 2], 2)
    else:
        value = nums[-1] - nums[0]
    prompt = f"What is the {'median' if want_median else 'range'} of this data set: {', '.join(map(str, nums))}?"
    mean = Fraction(sum(nums), n)
    other_val = (nums[-1] - nums[0]) if want_median else (Fraction(nums[n // 2]) if n % 2 else Fraction(nums[n // 2 - 1] + nums[n // 2], 2))
    distractors = [mean, other_val, nums[0]]
    choices, ans = build_choices(rng, value, distractors)
    method = "Sort the values and take the middle one (average the two middle values for an even count)." if want_median else "Subtract the smallest value from the largest."
    return blank("math", "Problem-Solving & Data", "Median and range", 1, prompt, choices, ans, method)


def t_line_of_best_fit(rng: random.Random) -> dict:
    m = rng.choice([2, 3, 4, 5, -2, -3])
    b = rng.randint(10, 60)
    x0 = rng.randint(2, 15)
    y0 = m * x0 + b
    x_unit = rng.choice(["hours studied", "years of experience", "weekly practice hours"])
    y_unit = rng.choice(["test score", "salary in thousands", "words per minute"])
    prompt = f"A line of best fit relating {x_unit} (x) to {y_unit} (y) is y = {m}x + {b}. Using this model, what is the predicted {y_unit} when {x_unit} is {x0}?"
    distractors = [m * x0, m * (x0 + b), (m + b) * x0]
    choices, ans = build_choices(rng, y0, distractors)
    return blank("math", "Problem-Solving & Data", "Line of best fit", 2, prompt, choices, ans,
                 f"Substitute x = {x0}: y = {m}({x0}) + {b} = {y0}.")


def t_special_right_triangle(rng: random.Random) -> dict:
    kind = rng.choice(["45-45-90", "30-60-90"])
    if kind == "45-45-90":
        leg = rng.randint(2, 12)
        correct = f"{leg}√2"
        prompt = f"In a 45-45-90 triangle, each leg has length {leg}. What is the length of the hypotenuse?"
        distractors = [f"{leg}√3", f"{2*leg}", f"{leg}"]
        explanation = f"In a 45-45-90 triangle, hypotenuse = leg × √2 = {leg}√2."
    else:
        short = rng.randint(2, 12)
        ask_hyp = rng.random() < 0.5
        if ask_hyp:
            correct = f"{2*short}"
            prompt = f"In a 30-60-90 triangle, the side opposite the 30° angle has length {short}. What is the length of the hypotenuse?"
            distractors = [f"{short}", f"{3*short}", f"{short}√3"]
            explanation = f"In a 30-60-90 triangle, hypotenuse = 2 × (short leg) = {2*short}."
        else:
            correct = f"{short}√3"
            prompt = f"In a 30-60-90 triangle, the side opposite the 30° angle has length {short}. What is the length of the side opposite the 60° angle?"
            distractors = [f"{2*short}", f"{short}√2", f"{short}"]
            explanation = f"In a 30-60-90 triangle, the long leg = (short leg) × √3 = {short}√3."
    choices, ans = build_choices(rng, correct, distractors)
    return blank("math", "Geometry & Trig", "Special right triangles", 2, prompt, choices, ans, explanation)


def t_circle_equation(rng: random.Random) -> dict:
    h = rng.randint(-8, 8)
    k = rng.randint(-8, 8)
    r = rng.randint(2, 10)
    h_sign = "-" if h >= 0 else "+"
    k_sign = "-" if k >= 0 else "+"
    prompt = f"What is the equation of a circle with center ({h}, {k}) and radius {r}?"
    correct = f"(x {h_sign} {abs(h)})² + (y {k_sign} {abs(k)})² = {r*r}"
    distractors = [
        f"(x {'+' if h_sign=='-' else '-'} {abs(h)})² + (y {'+' if k_sign=='-' else '-'} {abs(k)})² = {r*r}",
        f"(x {h_sign} {abs(h)})² + (y {k_sign} {abs(k)})² = {r}",
        f"(x {h_sign} {abs(h)}) + (y {k_sign} {abs(k)}) = {r*r}",
    ]
    choices, ans = build_choices(rng, correct, distractors)
    return blank("math", "Geometry & Trig", "Equations of circles", 2, prompt, choices, ans,
                 f"A circle centered at (h, k) with radius r has equation (x − h)² + (y − k)² = r². Here that's {correct}.")


# ────────────────────────── Standard English Conventions ──────────────────────────

SVA_SINGULAR = ["The committee", "Each of the students", "The box of old books", "Neither of the answers",
                "The number of applicants", "My aunt, along with her neighbors,", "The coach", "A stack of papers",
                "Everyone in the class", "The list of requirements", "One of the machines", "The crew of the ship",
                "Either of the options", "The panel of judges", "A collection of rare coins"]
SVA_PLURAL = ["The students", "The boxes of books", "Several of the answers", "The applicants",
              "My aunts and their neighbors", "The coaches", "The papers on the desk", "A few of the machines",
              "The members of the committee", "The requirements on the list", "Both of the options",
              "The judges on the panel", "The coins in the collection", "The crews of the ships"]
SVA_VERBS = [("is", "are"), ("was", "were"), ("has", "have"), ("does", "do"),
             ("runs smoothly", "run smoothly"), ("arrives on time", "arrive on time"),
             ("seems ready", "seem ready"), ("looks complete", "look complete"),
             ("works well", "work well"), ("needs review", "need review")]


def t_subject_verb_agreement(rng: random.Random) -> dict:
    singular = rng.random() < 0.5
    subject = rng.choice(SVA_SINGULAR if singular else SVA_PLURAL)
    sing_v, plur_v = rng.choice(SVA_VERBS)
    correct_v = sing_v if singular else plur_v
    wrong_v = plur_v if singular else sing_v
    prompt = f"Which choice completes the sentence with correct subject-verb agreement?\n\n{subject} ______ every week."
    other_tense = rng.choice([v for pair in SVA_VERBS for v in pair if v not in (sing_v, plur_v)])
    choices, ans = build_choices(rng, correct_v, [wrong_v, other_tense, wrong_v + " often"])
    return blank("rw", "Standard English Conventions", "Subject-verb agreement", 1, prompt, choices, ans,
                 f"The subject \"{subject}\" is {'singular' if singular else 'plural'}, so it takes the {'singular' if singular else 'plural'} verb form \"{correct_v}.\"")


CLAUSE_PAIRS = [
    ("the storm knocked out power", "the whole neighborhood went dark"),
    ("she finished the marathon", "her legs ached for days"),
    ("the museum extended its hours", "more visitors could attend the exhibit"),
    ("the engineers tested the bridge", "it was declared safe for traffic"),
    ("the recipe called for fresh basil", "none was available at the store"),
    ("the flight was delayed for hours", "passengers grew increasingly frustrated"),
    ("the library added new computers", "students could finally print their essays"),
    ("the mayor signed the ordinance", "construction could begin next month"),
    ("the team lost its star player", "the season took an unexpected turn"),
    ("the professor canceled office hours", "students emailed their questions instead"),
    ("the volcano had been dormant for decades", "scientists were caught off guard by the eruption"),
    ("the factory upgraded its equipment", "production doubled within a year"),
    ("the negotiations dragged on for weeks", "both sides grew impatient"),
    ("the orchestra rehearsed late into the night", "the premiere still felt underprepared"),
    ("the app crashed during the demo", "the investors lost confidence"),
]


def t_sentence_boundaries(rng: random.Random) -> dict:
    c1, c2 = rng.choice(CLAUSE_PAIRS)
    c1_cap = c1[0].upper() + c1[1:]
    correct = f"{c1_cap}; {c2}."
    splice = f"{c1_cap}, {c2}."
    run_on = f"{c1_cap} {c2}."
    bad_cap = f"{c1_cap}. {c2}."  # a period, but the next sentence wrongly stays lowercase
    prompt = f"Which choice is punctuated correctly, joining two complete sentences?"
    choices, ans = build_choices(rng, correct, [splice, run_on, bad_cap])
    return blank("rw", "Standard English Conventions", "Sentence boundaries", 2, prompt, choices, ans,
                 "Two independent clauses can be joined with a semicolon (no conjunction needed). A comma alone creates a comma splice, and no punctuation creates a run-on.")


POSS_NOUNS = ["dog", "student", "manager", "teacher", "neighbor", "athlete", "author", "driver",
              "engineer", "artist", "scientist", "customer", "volunteer", "director", "editor", "worker"]


def t_possessives_plurals(rng: random.Random) -> dict:
    noun = rng.choice(POSS_NOUNS)
    singular_owner = rng.random() < 0.5
    if singular_owner:
        correct = f"{noun}'s"
        prompt = f"Which choice correctly completes the sentence?\n\nThe ______ schedule changed at the last minute. (referring to one {noun})"
        distractors = [f"{noun}s", noun, f"{noun}s's"]
    else:
        correct = f"{noun}s'"
        prompt = f"Which choice correctly completes the sentence?\n\nThe ______ schedules all changed at the last minute. (referring to more than one {noun})"
        distractors = [f"{noun}'s", noun, f"{noun}s's"]
    choices, ans = build_choices(rng, correct, distractors)
    return blank("rw", "Standard English Conventions", "Possessives and plurals", 2, prompt, choices, ans,
                 f"A single owner takes 's ({noun}'s); multiple owners of a regular plural noun take s' ({noun}s').")


TENSE_MARKERS = [
    ("Yesterday, she", "walked", ["walks", "will walk", "has walked"]),
    ("Right now, she", "is walking", ["walked", "will walk", "walk"]),
    ("By next summer, she", "will have walked", ["walked", "walks", "is walking"]),
    ("For the past decade, they", "have walked", ["walk", "walked", "will walk"]),
    ("Every day, he", "walks", ["walk", "walked", "will walk"]),
    ("Since Monday, he", "has walked", ["walk", "walked", "will walk"]),
    ("Last week, they", "walked", ["walk", "walks", "will walk"]),
    ("Right now, they", "are walking", ["walked", "will walk", "walks"]),
]


def t_verb_tense(rng: random.Random) -> dict:
    marker, correct, wrongs = rng.choice(TENSE_MARKERS)
    prompt = f"Which choice completes the sentence in a verb tense consistent with the rest of the sentence?\n\n{marker} ______ to the park."
    choices, ans = build_choices(rng, correct, wrongs)
    return blank("rw", "Standard English Conventions", "Verb tense", 2, prompt, choices, ans,
                 f"The time marker \"{marker}\" requires \"{correct}\" to keep the tense consistent.")


COLON_CONTEXTS = [
    ("The team needed one thing to win", "a healthy point guard"),
    ("Her application was missing a single item", "a letter of recommendation"),
    ("The chef listed the ingredients", "flour, butter, sugar, and eggs"),
    ("Only one obstacle remained", "funding for the final phase"),
    ("The trip required careful planning", "flights, lodging, and a rental car"),
    ("The report identified a clear cause", "outdated safety equipment"),
    ("The coach had one rule above all others", "show up on time"),
    ("The museum's new exhibit covers three eras", "ancient, medieval, and modern"),
    ("The survey revealed a surprising trend", "most respondents preferred remote work"),
]


def t_colons_punctuation(rng: random.Random) -> dict:
    lead, tail = rng.choice(COLON_CONTEXTS)
    correct = f"{lead}: {tail}."
    semicolon = f"{lead}; {tail}."
    comma = f"{lead}, {tail}."
    none_ = f"{lead} {tail}."
    prompt = "Which choice uses punctuation correctly to introduce the explanation that follows?"
    choices, ans = build_choices(rng, correct, [semicolon, comma, none_])
    return blank("rw", "Standard English Conventions", "Colons and punctuation", 2, prompt, choices, ans,
                 "A colon after a complete sentence can introduce an explanation or list; a semicolon needs a second independent clause, and a comma alone is too weak here.")


FRAGMENT_SUBJECTS = ["The dog", "Our neighbor", "The old bridge", "A determined intern", "The orchestra",
                     "The new employee", "The hiking club", "My grandfather", "The research team", "The volunteer"]
FRAGMENT_VERBS = [("ran", "running", "to run"), ("finished", "finishing", "to finish"),
                   ("crossed", "crossing", "to cross"), ("performed", "performing", "to perform"),
                   ("arrived", "arriving", "to arrive"), ("completed the task", "completing the task", "to complete the task"),
                   ("solved the problem", "solving the problem", "to solve the problem")]


def t_finite_verbs_fragments(rng: random.Random) -> dict:
    subject = rng.choice(FRAGMENT_SUBJECTS)
    past, gerund, infinitive = rng.choice(FRAGMENT_VERBS)
    obj = rng.choice(["down the street", "the finish line", "for the finals", "without stopping"])
    correct = f"{subject} {past} {obj}."
    frag1 = f"{subject} {gerund} {obj}."
    frag2 = f"{subject} {infinitive} {obj}."
    frag3 = f"{subject} {obj}, {gerund}."
    prompt = "Which choice is a complete sentence?"
    choices, ans = build_choices(rng, correct, [frag1, frag2, frag3])
    return blank("rw", "Standard English Conventions", "Finite verbs and fragments", 2, prompt, choices, ans,
                 f"A sentence needs a finite (conjugated) verb. \"{past}\" is finite; \"{gerund}\" and \"{infinitive}\" alone cannot carry a sentence.")


MODIFIER_SETS = [
    ("Running late for the meeting,", "Maria", "grabbed her keys and rushed out the door."),
    ("Excited about the trip,", "the children", "packed their bags the night before."),
    ("Determined to finish first,", "the runner", "sprinted past the final marker."),
    ("Worried about the deadline,", "the editor", "stayed late to finish the draft."),
    ("Hoping to impress the judges,", "the young chef", "plated the dish with great care."),
    ("Exhausted after the long shift,", "the nurse", "went straight home to sleep."),
    ("Eager to learn the material,", "the new hire", "asked the trainer several questions."),
    ("Nervous before the audition,", "the actor", "rehearsed the lines one more time."),
]
WRONG_MODIFIER_SUBJECTS = ["the meeting", "the audience", "the schedule", "the announcement", "the weather",
                            "the building", "the paperwork", "the traffic", "the ceremony", "the equipment"]


def t_modifier_placement(rng: random.Random) -> dict:
    modifier, subject, rest = rng.choice(MODIFIER_SETS)
    correct = f"{modifier} {subject} {rest}"
    wrongs = [w for w in WRONG_MODIFIER_SUBJECTS if w != subject]
    picked = rng.sample(wrongs, 3)
    distractors = [f"{modifier} {w} {rest}" for w in picked]
    prompt = "Which choice avoids a dangling or misplaced modifier?"
    choices, ans = build_choices(rng, correct, distractors)
    return blank("rw", "Standard English Conventions", "Modifier placement", 3, prompt, choices, ans,
                 f"The opening phrase \"{modifier}\" describes \"{subject}\", so \"{subject}\" must be the very next noun. "
                 f"The other choices attach the phrase to a noun that cannot logically do that action.")


PRONOUN_SETS = [
    ("Maria", "Elena", "had won the scholarship"),
    ("the manager", "the new employee", "needed the report by Friday"),
    ("the coach", "the assistant coach", "was in charge of equipment"),
    ("Devon", "his brother", "had left the keys inside"),
    ("the professor", "the teaching assistant", "would grade the exams"),
    ("Priya", "her roommate", "had paid the electric bill"),
    ("the director", "the producer", "would approve the final cut"),
    ("Omar", "his cousin", "had reserved the campsite"),
    ("the client", "the contractor", "would cover the extra cost"),
]


def t_pronoun_clarity(rng: random.Random) -> dict:
    a, b, tail = rng.choice(PRONOUN_SETS)
    a_cap = a[0].upper() + a[1:]
    correct = f"{a_cap} told {b} that {b} {tail}."
    ambiguous = f"{a_cap} told {b} that they {tail}."
    wrong_pronoun = f"{a_cap} told {b} that it {tail}."
    wrong_case = f"{a_cap} told {b} that them {tail}."
    prompt = "Which choice avoids an ambiguous pronoun reference?"
    choices, ans = build_choices(rng, correct, [ambiguous, wrong_pronoun, wrong_case])
    return blank("rw", "Standard English Conventions", "Pronoun clarity", 3, prompt, choices, ans,
                 f"\"They\" in the ambiguous version could refer to either {a} or {b}; naming \"{b}\" directly removes the ambiguity.")


ACTIVITY_SETS = [
    [("hiking", "to hike", "hike"), ("swimming", "to swim", "swim"), ("camping", "to camp", "camp")],
    [("reading", "to read", "read"), ("writing", "to write", "write"), ("coding", "to code", "code")],
    [("cooking", "to cook", "cook"), ("cleaning", "to clean", "clean"), ("organizing", "to organize", "organize")],
    [("painting", "to paint", "paint"), ("sculpting", "to sculpt", "sculpt"), ("designing", "to design", "design")],
    [("researching", "to research", "research"), ("outlining", "to outline", "outline"), ("editing", "to edit", "edit")],
]


def t_parallelism(rng: random.Random) -> dict:
    subject = rng.choice(["The new intern", "Maria", "The committee", "Our team"])
    verb = rng.choice(["enjoys", "recommends", "practices", "values"])
    items = rng.choice(ACTIVITY_SETS)
    correct = f"{subject} {verb} {items[0][0]}, {items[1][0]}, and {items[2][0]}."
    wrong_last_infinitive = f"{subject} {verb} {items[0][0]}, {items[1][0]}, and {items[2][1]}."
    wrong_middle_infinitive = f"{subject} {verb} {items[0][0]}, {items[1][1]}, and {items[2][0]}."
    wrong_last_plain = f"{subject} {verb} {items[0][0]}, {items[1][0]}, and {items[2][2]}."
    prompt = "Which choice maintains parallel structure in the sentence?"
    choices, ans = build_choices(rng, correct, [wrong_last_infinitive, wrong_middle_infinitive, wrong_last_plain])
    return blank("rw", "Standard English Conventions", "Parallelism", 2, prompt, choices, ans,
                 f"Every item in a series should share the same grammatical form — here, the gerund form throughout: {items[0][0]}, {items[1][0]}, and {items[2][0]}.")


DASH_CONTEXTS = [
    ("The recipe", "a family favorite for decades", "calls for three kinds of cheese."),
    ("The bridge", "completed just last year", "already needs repairs."),
    ("Her presentation", "surprisingly candid", "impressed the entire board."),
    ("The novel", "originally rejected by six publishers", "went on to sell a million copies."),
    ("The proposal", "backed by three council members", "will be voted on next week."),
]


def t_dash_usage(rng: random.Random) -> dict:
    a, aside, b = rng.choice(DASH_CONTEXTS)
    correct = f"{a} — {aside} — {b}"
    mismatched1 = f"{a} — {aside}, {b}"
    mismatched2 = f"{a}, {aside} — {b}"
    none_ = f"{a} {aside} {b}"
    prompt = "Which choice correctly punctuates the interrupting phrase in the middle of the sentence?"
    choices, ans = build_choices(rng, correct, [mismatched1, mismatched2, none_])
    return blank("rw", "Standard English Conventions", "Dashes", 2, prompt, choices, ans,
                 "An interrupting phrase set off in the middle of a sentence needs matching punctuation on both sides — a pair of dashes, not one dash and one comma.")


# ────────────────────────────────── Expression of Ideas ──────────────────────────────────

TRANSITION_BANK = {
    "contrast": ["However,", "Nevertheless,", "On the other hand,"],
    "cause_effect": ["As a result,", "Therefore,", "Consequently,"],
    "example": ["For example,", "For instance,"],
    "addition": ["In addition,", "Moreover,", "Furthermore,"],
}

TRANSITION_PAIRS = [
    ("The company invested heavily in new equipment.", "production still declined that quarter.", "contrast"),
    ("The bridge was closed for repairs for six months.", "commuters faced significant delays every morning.", "cause_effect"),
    ("Many countries have adopted renewable energy incentives.", "Germany now generates over 40% of its electricity from wind and solar.", "example"),
    ("The museum extended its weekend hours.", "it introduced a discounted membership program for students.", "addition"),
    ("Sales dropped sharply in the first quarter.", "the board replaced the head of marketing.", "cause_effect"),
    ("The novelist rarely gives interviews.", "she agreed to speak at three universities this fall.", "contrast"),
    ("Several major retailers have shortened their return windows.", "one chain now allows returns for only 14 days after purchase.", "example"),
    ("The lab upgraded its imaging equipment last year.", "it hired two additional research technicians.", "addition"),
    ("The city repaved every major road downtown.", "traffic noise complaints dropped noticeably in nearby neighborhoods.", "cause_effect"),
    ("The startup had never turned a profit in its first five years.", "investors continued funding its expansion.", "contrast"),
    ("Several airlines have begun charging for overhead bin space.", "one budget carrier now charges separately for any carry-on bag at all.", "example"),
    ("The library digitized its rare manuscript collection.", "it launched a public online archive for researchers.", "addition"),
    ("The factory's output had been flat for three years.", "management projects a sharp increase for the coming year.", "contrast"),
    ("Regulators tightened emissions standards for new vehicles.", "several manufacturers announced plans to redesign their engines.", "cause_effect"),
    ("The airline canceled dozens of flights due to a system outage.", "thousands of passengers were left stranded overnight.", "cause_effect"),
    ("The film received harsh reviews from critics.", "it became the highest-grossing movie of the year.", "contrast"),
    ("Several tech companies have shifted to a four-day work week.", "one firm reported no drop in overall output after the switch.", "example"),
    ("The clinic expanded its hours to include weekends.", "it added a telehealth option for follow-up visits.", "addition"),
    ("The reservoir's water level dropped to a record low.", "the city imposed mandatory outdoor watering restrictions.", "cause_effect"),
    ("The startup's product had almost no marketing budget.", "it grew to a million users within a year through word of mouth alone.", "contrast"),
]


def t_transitions(rng: random.Random) -> dict:
    s1, s2, relation = rng.choice(TRANSITION_PAIRS)
    correct = rng.choice(TRANSITION_BANK[relation])
    other_relations = [r for r in TRANSITION_BANK if r != relation]
    distractors = [rng.choice(TRANSITION_BANK[r]) for r in other_relations]
    prompt = f"Which choice completes the text with the most logical transition?\n\n{s1} ______ {s2}"
    choices, ans = build_choices(rng, correct, distractors)
    relation_name = {"contrast": "a contrast", "cause_effect": "a cause-and-effect relationship",
                      "example": "an example", "addition": "an additional, similar point"}[relation]
    return blank("rw", "Expression of Ideas", "Transitions", 2, prompt, choices, ans,
                 f"The second sentence presents {relation_name} relative to the first, which calls for a transition like \"{correct}\"")


NOTE_SETS = [
    {
        "topic": "coral reefs", "goal": "emphasize how ecologically valuable coral reefs are relative to their size",
        "notes": ["Coral reefs cover less than 1% of the ocean floor.", "Reefs support roughly 25% of all known marine species.",
                   "Many coastal communities rely on reef fisheries for food.", "Rising ocean temperatures have caused widespread coral bleaching."],
        "correct": "Coral reefs support roughly 25% of all known marine species despite covering less than 1% of the ocean floor.",
        "wrong": ["Rising ocean temperatures have caused widespread coral bleaching in recent years.",
                   "Many coastal communities depend on reef fisheries for food.",
                   "Coral reefs are typically found in warm, shallow ocean waters."],
    },
    {
        "topic": "a city's public transit system", "goal": "highlight the impact of a specific policy change",
        "notes": ["The city introduced free bus fares for riders under 18 in 2022.", "Youth ridership rose by 35% within a year of the change.",
                   "The subway system was built in the 1950s.", "The city's population has grown by 8% since 2015."],
        "correct": "After the city introduced free bus fares for riders under 18 in 2022, youth ridership rose by 35% within a year.",
        "wrong": ["The city's subway system was built in the 1950s and has been renovated twice.",
                   "The city's population has grown by 8% since 2015.",
                   "Free bus fares for riders under 18 began in 2022."],
    },
    {
        "topic": "an author's early career", "goal": "explain why the author's first novel was initially overlooked",
        "notes": ["The author's first novel was published by a small regional press with limited distribution.",
                   "The novel received only two reviews in its first year.", "The author later won a national award for a second novel.",
                   "The author grew up in a small coastal town."],
        "correct": "Because the author's first novel was published by a small regional press with limited distribution, it received only two reviews in its first year.",
        "wrong": ["The author later won a national award for a second novel.",
                   "The author grew up in a small coastal town.",
                   "The author's first novel was published by a small press."],
    },
    {
        "topic": "a species' population recovery", "goal": "show a cause-and-effect relationship between a policy and a population change",
        "notes": ["Hunting of the species was banned in 1985.", "The population has grown from 1,200 to over 9,000 since the ban.",
                   "The species primarily eats small fish and crustaceans.", "The species can live up to 25 years in the wild."],
        "correct": "Since hunting of the species was banned in 1985, its population has grown from 1,200 to over 9,000.",
        "wrong": ["The species primarily eats small fish and crustaceans.",
                   "The species can live up to 25 years in the wild.",
                   "The population has grown substantially since 1985."],
    },
    {
        "topic": "a company's factory upgrade", "goal": "quantify the effect of new equipment on production efficiency",
        "notes": ["The factory installed automated assembly equipment in 2021.", "Production output per worker increased by 22% after installation.",
                   "The factory employs about 400 workers.", "The company was founded in 1978."],
        "correct": "After the factory installed automated assembly equipment in 2021, production output per worker increased by 22%.",
        "wrong": ["The factory employs about 400 workers across two shifts.",
                   "The company was founded in 1978 and has grown steadily.",
                   "The factory installed new equipment in 2021."],
    },
    {
        "topic": "a study on sleep and memory", "goal": "present specific evidence supporting the study's main finding",
        "notes": ["Researchers tracked 200 participants over eight weeks.", "Participants who slept fewer than 6 hours scored 18% lower on memory tests.",
                   "The study was conducted at a university sleep lab.", "Participants ranged in age from 19 to 45."],
        "correct": "Participants who slept fewer than 6 hours scored 18% lower on memory tests than those who slept more.",
        "wrong": ["The study was conducted at a university sleep lab over eight weeks.",
                   "Participants ranged in age from 19 to 45.",
                   "Researchers tracked 200 participants for the study."],
    },
    {
        "topic": "a small business's growth", "goal": "explain the specific reason the business expanded to a second location",
        "notes": ["The original shop consistently sold out of inventory by early afternoon.", "The owner opened a second location across town in 2020.",
                   "The shop specializes in handmade furniture.", "The owner previously worked as a carpenter."],
        "correct": "Because the original shop consistently sold out of inventory by early afternoon, the owner opened a second location across town.",
        "wrong": ["The shop specializes in handmade furniture and home goods.",
                   "The owner previously worked as a carpenter for over a decade.",
                   "The owner opened a second location in 2020."],
    },
    {
        "topic": "a city's air quality initiative", "goal": "connect a specific regulation to a measurable outcome",
        "notes": ["The city restricted diesel trucks from the downtown core in 2019.", "Average particulate pollution downtown fell by 30% over the next two years.",
                   "The city has a population of about 600,000.", "The initiative was proposed by the city's environmental board."],
        "correct": "After the city restricted diesel trucks from the downtown core in 2019, average particulate pollution fell by 30% over the next two years.",
        "wrong": ["The city has a population of about 600,000 residents.",
                   "The initiative was proposed by the city's environmental board.",
                   "The city restricted diesel trucks from downtown in 2019."],
    },
    {
        "topic": "a hospital's staffing changes", "goal": "connect a specific staffing change to a patient-outcome measure",
        "notes": ["The hospital increased its nurse-to-patient ratio in its ICU in 2021.", "Reported medication errors in the ICU fell by 40% over the following year.",
                   "The hospital was founded in 1962.", "The hospital added a new parking structure in 2021."],
        "correct": "After the hospital increased its nurse-to-patient ratio in its ICU in 2021, reported medication errors fell by 40% over the following year.",
        "wrong": ["The hospital was founded in 1962 and has expanded several times.",
                   "The hospital added a new parking structure in 2021.",
                   "The hospital increased its nurse-to-patient ratio in 2021."],
    },
    {
        "topic": "a national park's visitor management", "goal": "explain the specific reason the park introduced a reservation system",
        "notes": ["Visitor numbers at the park had tripled over the previous decade.", "Popular trails were experiencing significant erosion from overcrowding.",
                   "The park introduced a timed-entry reservation system in 2022.", "The park covers roughly 400 square miles."],
        "correct": "Because visitor numbers had tripled and popular trails were eroding from overcrowding, the park introduced a timed-entry reservation system in 2022.",
        "wrong": ["The park covers roughly 400 square miles of protected land.",
                   "The park introduced a reservation system in 2022.",
                   "Visitor numbers at the park had tripled over the previous decade."],
    },
    {
        "topic": "a university's course redesign", "goal": "present specific evidence that a teaching change improved outcomes",
        "notes": ["A large introductory course switched from lectures to small group problem-solving sessions in 2020.", "Course failure rates dropped from 22% to 9% over the next two years.",
                   "The course is required for several engineering majors.", "The redesign was led by a faculty committee."],
        "correct": "After a large introductory course switched to small group problem-solving sessions in 2020, failure rates dropped from 22% to 9% over the next two years.",
        "wrong": ["The course is required for several engineering majors.",
                   "The redesign was led by a faculty committee over several months.",
                   "The course switched formats in 2020."],
    },
    {
        "topic": "a river restoration project", "goal": "connect a specific intervention to an ecological recovery",
        "notes": ["An old dam on the river was removed in 2015.", "Salmon returning to spawn upstream increased from a few hundred to over 10,000 within five years.",
                   "The river flows through three counties.", "The removal project cost $15 million."],
        "correct": "After an old dam on the river was removed in 2015, the number of salmon returning to spawn upstream rose from a few hundred to over 10,000 within five years.",
        "wrong": ["The river flows through three counties before reaching the coast.",
                   "The removal project cost $15 million to complete.",
                   "An old dam on the river was removed in 2015."],
    },
    {
        "topic": "a retail chain's checkout redesign", "goal": "present specific evidence that a store redesign reduced wait times",
        "notes": ["A retail chain replaced traditional checkout lines with a mixed self-checkout and staffed layout in 2021.", "Average wait time fell from 9 minutes to under 3 minutes at redesigned stores.",
                   "The chain operates in twelve states.", "The redesign also included new store lighting."],
        "correct": "After a retail chain redesigned its checkout layout in 2021, average wait time fell from 9 minutes to under 3 minutes at those stores.",
        "wrong": ["The chain operates stores in twelve states.",
                   "The redesign also included new store lighting.",
                   "The chain redesigned its checkout layout in 2021."],
    },
    {
        "topic": "a manufacturing plant's safety program", "goal": "connect a specific policy to a change in workplace injuries",
        "notes": ["A plant introduced mandatory daily safety briefings in 2019.", "Reported workplace injuries fell by more than half over the next three years.",
                   "The plant employs around 900 workers.", "The plant manufactures automotive parts."],
        "correct": "After the plant introduced mandatory daily safety briefings in 2019, reported workplace injuries fell by more than half over the next three years.",
        "wrong": ["The plant employs around 900 workers across two shifts.",
                   "The plant manufactures automotive parts for several major brands.",
                   "The plant introduced daily safety briefings in 2019."],
    },
    {
        "topic": "a bike-share program", "goal": "explain why a city expanded its bike-share program to new neighborhoods",
        "notes": ["The city launched a bike-share pilot in its downtown core in 2019.", "Ridership in the pilot area exceeded projections within six months.",
                   "The program uses electric-assist bikes.", "The city has hosted a cycling festival since 2010."],
        "correct": "Because ridership in the pilot area exceeded projections within six months, the city expanded the bike-share program to new neighborhoods.",
        "wrong": ["The program uses electric-assist bikes at every station.",
                   "The city has hosted a cycling festival since 2010.",
                   "The city launched a bike-share pilot in 2019."],
    },
    {
        "topic": "a vaccination campaign", "goal": "present evidence that a vaccination campaign reduced disease cases",
        "notes": ["A region launched a free vaccination campaign for a specific illness in 2020.", "Reported cases of the illness fell by 70% over the following two years.",
                   "The campaign was funded by a combination of public and private grants.", "The illness is most common in children under five."],
        "correct": "After a region launched a free vaccination campaign in 2020, reported cases of the illness fell by 70% over the following two years.",
        "wrong": ["The campaign was funded by a combination of public and private grants.",
                   "The illness is most common in children under five.",
                   "The region launched a vaccination campaign in 2020."],
    },
    {
        "topic": "a company's remote-work policy", "goal": "explain the specific reason a company reversed its remote-work policy",
        "notes": ["A company allowed fully remote work for all employees starting in 2020.", "Internal surveys showed new hires felt disconnected from team culture after a year of remote work.",
                   "The company is headquartered in a large office building.", "The company was founded in 2005."],
        "correct": "Because internal surveys showed new hires felt disconnected from team culture, the company reversed its fully remote work policy.",
        "wrong": ["The company is headquartered in a large office building downtown.",
                   "The company was founded in 2005.",
                   "The company allowed fully remote work starting in 2020."],
    },
    {
        "topic": "a stadium's energy use", "goal": "quantify the effect of a specific upgrade on a stadium's energy consumption",
        "notes": ["A stadium installed solar panels across its roof in 2021.", "Its annual electricity costs fell by 35% over the next two years.",
                   "The stadium seats about 60,000 people.", "The stadium hosts roughly 40 events per year."],
        "correct": "After a stadium installed solar panels across its roof in 2021, its annual electricity costs fell by 35% over the next two years.",
        "wrong": ["The stadium seats about 60,000 people for major events.",
                   "The stadium hosts roughly 40 events per year.",
                   "The stadium installed solar panels in 2021."],
    },
    {
        "topic": "a farming cooperative's crop yields", "goal": "connect a specific practice change to an increase in crop yields",
        "notes": ["A farming cooperative switched to a no-till planting method in 2018.", "Average yields across member farms rose by 15% over the next four years.",
                   "The cooperative includes about 50 member farms.", "The cooperative was established in 1974."],
        "correct": "After a farming cooperative switched to a no-till planting method in 2018, average yields across member farms rose by 15% over the next four years.",
        "wrong": ["The cooperative includes about 50 member farms.",
                   "The cooperative was established in 1974.",
                   "The cooperative switched to a no-till method in 2018."],
    },
    {
        "topic": "a public library's technology program", "goal": "present evidence that a new program increased library visits among teenagers",
        "notes": ["A public library opened a makerspace with 3D printers and design software in 2021.", "Visits by teenagers rose by 60% over the following year.",
                   "The library also expanded its weekend hours in 2019.", "The library was built in 1965."],
        "correct": "After a public library opened a makerspace in 2021, visits by teenagers rose by 60% over the following year.",
        "wrong": ["The library also expanded its weekend hours in 2019.",
                   "The library was built in 1965.",
                   "The library opened a makerspace in 2021."],
    },
]


def t_rhetorical_synthesis(rng: random.Random) -> dict:
    entry = rng.choice(NOTE_SETS)
    notes_text = "\n".join(f"• {n}" for n in entry["notes"])
    prompt = (f"While researching {entry['topic']}, a student has taken the following notes:\n\n{notes_text}\n\n"
              f"The student wants to {entry['goal']}. Which choice most effectively uses relevant information "
              f"from the notes to accomplish this goal?")
    choices, ans = build_choices(rng, entry["correct"], entry["wrong"])
    return blank("rw", "Expression of Ideas", "Rhetorical synthesis", 3, prompt, choices, ans,
                 "The correct choice combines the specific notes that directly support the stated goal. The other choices either state an irrelevant note, or restate only part of what's needed.")


# ────────────────────────────────── Information & Ideas ──────────────────────────────────
# Real passage-based comprehension can't be safely templated with random parameters —
# a randomized "passage" reads as nonsense, and a nonsense passage makes every
# question about it either trivial or unanswerable. So this is curated, original
# content instead: each entry is one hand-written short passage, split into
# sentences so a "which sentence best supports this claim" question can reuse the
# passage's own text as answer choices rather than needing separately hand-written
# wrong answers for every question type.

PASSAGES = [
    {
        "topic": "bioluminescent deep-sea life",
        "sentences": [
            "Below roughly 1,000 meters, sunlight no longer penetrates the ocean, yet the water is far from dark.",
            "More than three-quarters of deep-sea species are estimated to produce their own light through bioluminescence.",
            "Some anglerfish use a glowing lure to attract prey directly to their jaws.",
            "Other species flash light in patterns that appear to function as a form of signaling between individuals.",
            "Researchers still do not fully understand how the chemical reactions behind this light production first evolved.",
        ],
        "main_idea": "Bioluminescence is a widespread and varied adaptation among deep-sea organisms.",
        "main_idea_wrong": [
            "Anglerfish are the only deep-sea species known to produce light.",
            "Scientists have fully explained the evolutionary origins of bioluminescence.",
            "Sunlight is the primary source of light in the deep ocean.",
        ],
        "inference": "Bioluminescence likely serves more than one biological purpose across different species.",
        "inference_wrong": [
            "All bioluminescent species use their light for the same purpose.",
            "Bioluminescence will eventually be replaced by other adaptations.",
            "Species without bioluminescence cannot survive below 1,000 meters.",
        ],
        "evidence_claim": "bioluminescence can function as a hunting strategy",
        "evidence_correct_idx": 2,
    },
    {
        "topic": "congestion pricing in cities",
        "sentences": [
            "Several major cities now charge drivers a fee to enter their busiest downtown districts during peak hours.",
            "In the years after London introduced its charge, average traffic speeds downtown rose noticeably.",
            "Critics argue the fee places a disproportionate burden on lower-income commuters who cannot easily switch to other transport.",
            "Cities that adopt the policy typically use the revenue to fund public transit improvements.",
            "Supporters contend that faster bus service from the added funding offsets the cost for many of those same commuters.",
        ],
        "main_idea": "Congestion pricing has measurable traffic benefits but remains debated over its fairness.",
        "main_idea_wrong": [
            "Congestion pricing has been rejected by every city that has considered it.",
            "Congestion pricing revenue is never used for public transit.",
            "Traffic speeds are unaffected by congestion pricing.",
        ],
        "inference": "Whether congestion pricing feels fair may depend on how well a city's public transit improves afterward.",
        "inference_wrong": [
            "Congestion pricing has no effect on any commuter's daily costs.",
            "Every city that adopts congestion pricing sees identical results.",
            "Lower-income commuters universally support congestion pricing.",
        ],
        "evidence_claim": "congestion pricing can improve traffic flow",
        "evidence_correct_idx": 1,
    },
    {
        "topic": "Roman aqueduct engineering",
        "sentences": [
            "Roman aqueducts relied almost entirely on gravity, requiring a precise and gradual downward slope over long distances.",
            "Engineers used tools like the chorobates, a leveling instrument, to maintain that slope across dozens of miles.",
            "Where valleys interrupted the path, builders constructed towering arched bridges to carry the water channel across.",
            "Some aqueducts also used inverted siphons, sealed pipes that let water flow downhill and back up the other side of a valley.",
            "Many of these structures remained partially functional over a thousand years after they were built.",
        ],
        "main_idea": "Roman aqueduct builders used a range of precise engineering techniques to move water across difficult terrain.",
        "main_idea_wrong": [
            "Roman aqueducts were simple ditches that required no specialized tools.",
            "Inverted siphons were the only method Romans used to cross valleys.",
            "Aqueducts collapsed within a few decades of construction.",
        ],
        "inference": "Maintaining a consistent slope was central to how well a Roman aqueduct functioned.",
        "inference_wrong": [
            "Roman engineers preferred steep, irregular slopes for aqueducts.",
            "The chorobates was used only for measuring building height.",
            "Aqueducts functioned equally well regardless of terrain.",
        ],
        "evidence_claim": "Roman engineers had a specific tool for maintaining a precise slope",
        "evidence_correct_idx": 1,
    },
    {
        "topic": "detecting exoplanets", "sentences": [
            "Most known exoplanets have never been directly photographed.",
            "Instead, astronomers often detect them by watching a star's brightness dim slightly as a planet passes in front of it.",
            "This dimming pattern, called a transit, can reveal a planet's size and orbital period.",
            "A second method tracks tiny wobbles in a star's position caused by the gravitational pull of an orbiting planet.",
            "Combining both methods lets researchers estimate a planet's mass as well as its size.",
        ],
        "main_idea": "Astronomers primarily detect exoplanets through indirect effects on their host stars rather than direct imaging.",
        "main_idea_wrong": [
            "Most exoplanets are discovered through direct photographs.",
            "The transit method reveals a planet's mass but not its size.",
            "Only one method exists for detecting exoplanets.",
        ],
        "inference": "Using multiple detection methods together provides more complete information about a planet than either method alone.",
        "inference_wrong": [
            "The wobble method has replaced the transit method entirely.",
            "A planet's orbital period cannot be determined by any current method.",
            "Direct photography is the most common detection method.",
        ],
        "evidence_claim": "a star's brightness can indicate the presence of an orbiting planet",
        "evidence_correct_idx": 1,
    },
    {
        "topic": "endangered languages", "sentences": [
            "Linguists estimate that roughly 40% of the world's roughly 7,000 languages are at risk of falling out of use this century.",
            "A language is generally considered endangered when children in a community stop learning it as a first language.",
            "Some communities have launched immersion programs specifically to teach the language to a new generation.",
            "When a language disappears, so does the specific knowledge and worldview embedded in it, such as unique terms for local plants or navigation.",
            "Documentation projects now use audio and video recordings to preserve languages even if daily use declines.",
        ],
        "main_idea": "Language endangerment is a widespread phenomenon with cultural consequences, though some communities are actively responding to it.",
        "main_idea_wrong": [
            "Nearly all of the world's languages are currently endangered.",
            "Language documentation projects have stopped all language loss.",
            "Children learning a language as a first language causes it to become endangered.",
        ],
        "inference": "The loss of a language can mean the loss of knowledge that isn't easily translated into another language.",
        "inference_wrong": [
            "All knowledge from an endangered language survives automatically in translation.",
            "Immersion programs have proven ineffective in every community that has tried them.",
            "Endangered languages are always successfully revived.",
        ],
        "evidence_claim": "communities are taking direct action to prevent a language from disappearing",
        "evidence_correct_idx": 2,
    },
    {
        "topic": "altitude training in athletics", "sentences": [
            "Endurance athletes sometimes train at high altitude, where lower oxygen levels prompt the body to produce more red blood cells.",
            "This adaptation, built up over several weeks, can improve how efficiently the body delivers oxygen to muscles.",
            "The effect fades within a few weeks of returning to sea level, so athletes often time their training close to competition.",
            "Some athletes instead sleep in low-oxygen tents at sea level while training normally, aiming for a similar effect.",
            "Not every athlete responds to altitude training the same way; individual variation in the response is well documented.",
        ],
        "main_idea": "Altitude training can boost endurance performance through a temporary physiological adaptation, though results vary by athlete.",
        "main_idea_wrong": [
            "Altitude training permanently increases red blood cell production.",
            "All athletes respond to altitude training identically.",
            "Sea-level training tents have no relationship to altitude training.",
        ],
        "inference": "The timing of altitude training relative to a competition likely matters for its benefits to be useful.",
        "inference_wrong": [
            "Altitude training's effects last indefinitely after returning to sea level.",
            "Low-oxygen tents work by a completely different mechanism than altitude.",
            "Red blood cell production decreases at high altitude.",
        ],
        "evidence_claim": "athletes have found an alternative to training at high elevation",
        "evidence_correct_idx": 3,
    },
    {
        "topic": "the reception of Impressionist painting", "sentences": [
            "When Impressionist painters first exhibited in Paris in 1874, many critics dismissed their work as unfinished or careless.",
            "One reviewer mockingly borrowed the title of a Monet painting to name the entire group \"Impressionists,\" intending it as an insult.",
            "The artists embraced the term rather than rejecting it.",
            "Within a few decades, the same techniques once criticized as sloppy were being taught in major art academies.",
            "Today, Impressionist paintings are among the most visited works in museums worldwide.",
        ],
        "main_idea": "Impressionism was initially mocked by critics but eventually became widely accepted and celebrated.",
        "main_idea_wrong": [
            "Impressionist painters rejected the name given to their movement.",
            "Impressionism was immediately praised by critics in 1874.",
            "Art academies never accepted Impressionist techniques.",
        ],
        "inference": "Public and critical opinion of an artistic style can shift dramatically over time.",
        "inference_wrong": [
            "Critical opinion of Impressionism has remained constant since 1874.",
            "The term \"Impressionist\" was originally meant as praise.",
            "Museums did not display Impressionist work until the present day.",
        ],
        "evidence_claim": "the name of the movement came from a critical, not admiring, source",
        "evidence_correct_idx": 1,
    },
    {
        "topic": "the placebo effect in medicine", "sentences": [
            "In clinical trials, some patients who receive an inactive treatment still report real improvement in their symptoms.",
            "This is known as the placebo effect, and it can involve measurable changes, not just a patient's perception.",
            "Researchers believe expectation plays a major role: believing a treatment will work can trigger the brain to release its own pain-relieving chemicals.",
            "Because of this effect, new treatments are typically tested against a placebo rather than against no treatment at all.",
            "The size of the placebo effect can vary depending on the condition being treated and even the color of the pill given.",
        ],
        "main_idea": "The placebo effect is a real, measurable phenomenon that shapes how medical treatments are tested.",
        "main_idea_wrong": [
            "The placebo effect is purely imaginary and produces no physical changes.",
            "New treatments are never compared against a placebo.",
            "The placebo effect is identical in size across all conditions.",
        ],
        "inference": "A patient's belief about a treatment can influence their body's biological response to it.",
        "inference_wrong": [
            "Only inactive treatments can trigger a placebo response.",
            "The placebo effect proves that a condition was never real.",
            "Pill color has no documented relationship to the placebo effect.",
        ],
        "evidence_claim": "expectation may trigger an actual biological response",
        "evidence_correct_idx": 2,
    },
    {
        "topic": "crop rotation in agriculture", "sentences": [
            "Farmers have long alternated which crops they plant in a given field from one season to the next.",
            "Growing the same crop repeatedly can deplete specific nutrients from the soil and allow pests suited to that crop to build up.",
            "Legumes such as beans and peas are often included in a rotation because they add nitrogen back into the soil.",
            "A well-planned rotation can reduce the need for synthetic fertilizer and chemical pest control.",
            "Some modern farms use rotations spanning four or more years to maximize these benefits.",
        ],
        "main_idea": "Crop rotation helps maintain soil health and reduce reliance on chemical inputs.",
        "main_idea_wrong": [
            "Crop rotation was invented by modern industrial farms.",
            "Growing the same crop repeatedly always improves soil quality.",
            "Legumes deplete nitrogen from the soil.",
        ],
        "inference": "The specific crops chosen for a rotation are likely selected for their effect on the soil, not just for profit.",
        "inference_wrong": [
            "Crop choice in a rotation has no effect on soil nutrients.",
            "Pests are unaffected by which crop is planted in a field.",
            "All crop rotations last exactly one year.",
        ],
        "evidence_claim": "a specific type of crop can restore a nutrient to depleted soil",
        "evidence_correct_idx": 2,
    },
    {
        "topic": "evidence for plate tectonics", "sentences": [
            "Scientists once debated whether Earth's continents had ever moved relative to one another.",
            "One clue came from matching fossil species found on continents now separated by wide oceans.",
            "Another came from magnetic stripes on the ocean floor that show a symmetrical pattern on either side of mid-ocean ridges.",
            "These stripes record reversals in Earth's magnetic field as new ocean floor formed and spread outward over time.",
            "Together, this evidence helped convince most geologists that continents drift atop moving tectonic plates.",
        ],
        "main_idea": "Multiple independent lines of evidence led scientists to accept that continents move via plate tectonics.",
        "main_idea_wrong": [
            "Fossil evidence alone was sufficient to prove plate tectonics.",
            "Magnetic stripes on the ocean floor show a random, unpredictable pattern.",
            "Geologists rejected plate tectonics despite the evidence.",
        ],
        "inference": "Evidence from very different scientific fields can converge to support the same conclusion.",
        "inference_wrong": [
            "Fossil evidence and magnetic evidence contradict each other.",
            "Only one type of evidence has ever supported plate tectonics.",
            "Earth's magnetic field has never reversed.",
        ],
        "evidence_claim": "the ocean floor's magnetic patterns are not random",
        "evidence_correct_idx": 2,
    },
    {
        "topic": "absolute pitch in musicians", "sentences": [
            "A small percentage of people can identify or produce a musical note without any reference tone, an ability called absolute pitch.",
            "The ability appears far more often in people who began musical training before about age six.",
            "Some researchers believe this points to a critical window in early childhood for developing the skill.",
            "Absolute pitch is also more common among speakers of tonal languages, where pitch changes a word's meaning.",
            "Even so, some people seem to have a natural predisposition toward the ability regardless of training or language.",
        ],
        "main_idea": "Absolute pitch appears linked to both early training and a possible natural predisposition.",
        "main_idea_wrong": [
            "Absolute pitch is entirely determined by genetics with no environmental influence.",
            "Absolute pitch is equally common regardless of when musical training begins.",
            "Only speakers of tonal languages can develop absolute pitch.",
        ],
        "inference": "Both early environment and individual biology likely play a role in who develops absolute pitch.",
        "inference_wrong": [
            "Absolute pitch cannot be influenced by language background.",
            "Musical training after age six produces absolute pitch at the same rate as earlier training.",
            "Absolute pitch has no connection to childhood development.",
        ],
        "evidence_claim": "the language someone grows up speaking may relate to their odds of developing absolute pitch",
        "evidence_correct_idx": 3,
    },
    {
        "topic": "tool use among animals", "sentences": [
            "Tool use was once considered a uniquely human trait.",
            "Researchers have since observed crows bending wire into hooks to retrieve food from narrow tubes.",
            "Some octopuses carry coconut shells to use as portable shelters later.",
            "Chimpanzees in several regions strip leaves from twigs to fish termites out of their mounds.",
            "These findings have led many scientists to view tool use as a capacity shared, to different degrees, across several species.",
        ],
        "main_idea": "Tool use, once thought unique to humans, has been documented across a range of animal species.",
        "main_idea_wrong": [
            "Only chimpanzees have been observed using tools besides humans.",
            "Tool use has never been documented outside of laboratory settings.",
            "Octopuses were the first animals found to use tools.",
        ],
        "inference": "The capacity for tool use may not require the level of intelligence once assumed necessary for it.",
        "inference_wrong": [
            "All animals are equally capable of complex tool use.",
            "Crows learned tool use directly from humans.",
            "Tool use has been observed in every animal species studied.",
        ],
        "evidence_claim": "an animal has been observed shaping an object to solve a specific problem",
        "evidence_correct_idx": 1,
    },
    {
        "topic": "the honeybee waggle dance", "sentences": [
            "When a forager honeybee finds a good source of nectar, it returns to the hive and performs a figure-eight movement known as the waggle dance.",
            "The angle of the dance relative to vertical indicates the direction of the food source relative to the sun.",
            "The duration of the waggle portion of the dance indicates roughly how far away the source is.",
            "Other bees that follow along the dance often fly out and find the same source with little searching.",
            "Researchers only confirmed this decoding of the dance's meaning through careful experiments in the twentieth century.",
        ],
        "main_idea": "Honeybees communicate the location of food sources to each other through a specific, decodable movement pattern.",
        "main_idea_wrong": ["Honeybees locate food sources purely by random searching.", "The waggle dance indicates a food source's quality but never its location.",
                              "Scientists have always understood the meaning of the waggle dance."],
        "inference": "The waggle dance likely improves a hive's overall foraging efficiency by reducing unnecessary searching.",
        "inference_wrong": ["Every bee in the hive performs the waggle dance equally often.", "The waggle dance has no measurable effect on other bees' behavior.",
                              "Bees that follow the dance never find the advertised food source."],
        "evidence_claim": "bees that observe the dance benefit from it directly",
        "evidence_correct_idx": 3,
    },
    {
        "topic": "urban heat islands", "sentences": [
            "Cities are often several degrees warmer than surrounding rural areas, a phenomenon known as the urban heat island effect.",
            "Dark surfaces like asphalt and rooftops absorb more solar radiation than natural vegetation does.",
            "Tall buildings can also trap heat by blocking wind that would otherwise help cool the air.",
            "Some cities have begun requiring reflective or light-colored roofing on new buildings to counter the effect.",
            "Adding urban tree cover has also been shown to lower nearby surface temperatures measurably.",
        ],
        "main_idea": "Urban heat islands result from specific features of city design, and some cities are now addressing them directly.",
        "main_idea_wrong": ["Cities are always cooler than surrounding rural areas.", "Urban heat islands are caused only by high population density.",
                              "No city has attempted to reduce the urban heat island effect."],
        "inference": "Changing the materials and vegetation used in a city could meaningfully affect its temperature.",
        "inference_wrong": ["Building height has no relationship to urban temperature.", "Reflective roofing has been proven ineffective at cooling buildings.",
                              "Urban heat islands are unrelated to surface material."],
        "evidence_claim": "a change to city infrastructure has been used to counter rising temperatures",
        "evidence_correct_idx": 3,
    },
    {
        "topic": "the printing press and literacy", "sentences": [
            "Before the mid-1400s, books in Europe were copied by hand, a slow process that kept them rare and expensive.",
            "The introduction of the movable-type printing press dramatically reduced the time and cost of producing a book.",
            "Within decades, the number of books in circulation across Europe grew from the thousands into the millions.",
            "Wider availability of books is thought to have contributed to rising literacy rates over the following century.",
            "The press also allowed ideas to spread between regions far more quickly than before.",
        ],
        "main_idea": "The printing press made books dramatically more available, with lasting effects on literacy and the spread of ideas.",
        "main_idea_wrong": ["Books were equally available before and after the printing press.", "The printing press had no effect on literacy rates.",
                              "Handwritten copying remained faster than printing."],
        "inference": "Access to books was likely a meaningful barrier to literacy before the printing press existed.",
        "inference_wrong": ["Literacy rates were already high before the printing press.", "The spread of ideas slowed down after the printing press was introduced.",
                              "Books became more expensive after the press was introduced."],
        "evidence_claim": "book production increased dramatically after the press was introduced",
        "evidence_correct_idx": 2,
    },
    {
        "topic": "octopus camouflage", "sentences": [
            "Octopuses can change both the color and the texture of their skin within a fraction of a second.",
            "Specialized cells called chromatophores expand and contract to shift the skin's color almost instantly.",
            "Separate muscles beneath the skin can raise small bumps to mimic the texture of coral or rock.",
            "Remarkably, octopuses are colorblind, so scientists are still investigating how they choose the correct colors to match their surroundings.",
            "Some researchers suspect that light-sensitive cells in the octopus's skin itself may help guide the response.",
        ],
        "main_idea": "Octopuses camouflage through a fast, multi-part process that isn't yet fully understood, despite the animals being colorblind.",
        "main_idea_wrong": ["Octopuses change only their skin texture, not their color.", "Octopuses camouflage exclusively using their eyes to detect color.",
                              "Scientists have fully explained how colorblind octopuses match colors."],
        "inference": "Octopus camouflage may rely on senses other than the kind of color vision most animals use.",
        "inference_wrong": ["Octopus camouflage requires no sensory input at all.", "Chromatophores control texture rather than color.",
                              "Octopus skin cannot detect light of any kind."],
        "evidence_claim": "the octopus's own skin might play a direct role in sensing its surroundings",
        "evidence_correct_idx": 4,
    },
    {
        "topic": "universal basic income pilot programs", "sentences": [
            "Several cities have run pilot programs giving residents a fixed monthly cash payment with no conditions attached.",
            "One frequently cited pilot found that recipients were more likely to secure full-time employment within a year than a comparison group.",
            "Critics note that most pilots have run for only one to three years, too short to reveal long-term effects.",
            "Supporters counter that even short-term pilots can reveal whether recipients spend the money responsibly.",
            "Researchers generally agree that pilot results vary depending on the local cost of living and job market.",
        ],
        "main_idea": "Basic income pilot programs have shown some promising short-term results, but questions remain about their long-term effects.",
        "main_idea_wrong": ["Every basic income pilot has shown identical results.", "Basic income pilots have consistently reduced employment.",
                              "No researcher has studied the effects of basic income pilots."],
        "inference": "The outcome of a basic income pilot may depend significantly on where it takes place.",
        "inference_wrong": ["Local economic conditions have no bearing on pilot outcomes.", "All pilot programs have run for at least a decade.",
                              "Critics and supporters agree on every aspect of the pilots."],
        "evidence_claim": "a basic income pilot had a measurable effect on employment",
        "evidence_correct_idx": 1,
    },
    {
        "topic": "the domestication of dogs", "sentences": [
            "Genetic evidence suggests dogs began diverging from wild wolves at least 15,000 years ago.",
            "One leading theory holds that wolves less fearful of humans lingered near early settlements to scavenge food scraps.",
            "Over many generations, these bolder, more tolerant wolves may have been selected for, gradually becoming distinct from their wild relatives.",
            "Skeletal remains show early dogs had smaller teeth and skulls than wolves, changes often associated with domestication.",
            "Exactly where this process first began remains debated, with evidence pointing to multiple possible regions.",
        ],
        "main_idea": "Dog domestication likely occurred gradually through natural selection favoring wolves tolerant of humans, though key details remain unsettled.",
        "main_idea_wrong": ["Dogs were domesticated deliberately by early humans in a single event.", "Dogs and wolves show no measurable skeletal differences.",
                              "Scientists agree on the exact location where dogs were first domesticated."],
        "inference": "Physical traits, not just behavior, changed as a result of the domestication process.",
        "inference_wrong": ["Domestication had no effect on the physical structure of dogs.", "Wolves and early dogs are genetically identical.",
                              "Domestication happened within a single generation."],
        "evidence_claim": "domestication left a physical mark on early dogs' skeletons",
        "evidence_correct_idx": 3,
    },
    {
        "topic": "grid-scale battery storage", "sentences": [
            "Solar and wind power generate electricity only when the sun shines or the wind blows, creating a mismatch with steady demand.",
            "Large battery installations can store excess renewable energy generated during peak production for use later.",
            "Some grid operators have used these batteries to respond to sudden demand spikes within seconds, faster than traditional power plants can.",
            "The cost of grid-scale batteries has fallen sharply over the past decade as manufacturing has scaled up.",
            "Even so, current battery capacity remains far short of what would be needed to store a full day's worth of a large city's electricity use.",
        ],
        "main_idea": "Grid-scale batteries help address the intermittency of renewable energy, though their capacity is still limited relative to demand.",
        "main_idea_wrong": ["Battery storage has fully solved the problem of renewable energy intermittency.", "Battery costs have risen steadily over the past decade.",
                              "Solar and wind power generate electricity at a constant, predictable rate."],
        "inference": "Further improvements in battery capacity would likely make renewable energy more reliable as a primary power source.",
        "inference_wrong": ["Battery capacity has no relationship to renewable energy reliability.", "Traditional power plants respond to demand spikes faster than batteries do.",
                              "Battery costs are expected to rise sharply in coming years."],
        "evidence_claim": "batteries can respond to changes in electricity demand unusually quickly",
        "evidence_correct_idx": 2,
    },
    {
        "topic": "the durability of Roman concrete", "sentences": [
            "Many Roman concrete structures, including sea walls, have remained intact for roughly two thousand years.",
            "Modern concrete, by contrast, often shows significant wear within a century, especially in seawater.",
            "Researchers found that Roman concrete contains small mineral deposits that form when seawater reacts with volcanic ash in the mixture.",
            "These deposits appear to fill in small cracks over time, a self-healing process modern concrete generally lacks.",
            "Engineers are now studying the ancient formula to help design longer-lasting concrete for modern coastal structures.",
        ],
        "main_idea": "Roman concrete has outlasted modern concrete in seawater because of a self-healing chemical process, which engineers are now studying.",
        "main_idea_wrong": ["Modern concrete lasts far longer than Roman concrete in seawater.", "Roman concrete contains no volcanic materials.",
                              "Engineers have found no practical use for studying Roman concrete."],
        "inference": "The specific ingredients used in a concrete mixture can significantly affect its long-term durability.",
        "inference_wrong": ["All concrete mixtures perform identically regardless of ingredients.", "Volcanic ash has no chemical interaction with seawater.",
                              "Roman concrete degrades faster than modern concrete."],
        "evidence_claim": "Roman concrete has an ability to repair itself over time",
        "evidence_correct_idx": 3,
    },
    {
        "topic": "bird migration navigation", "sentences": [
            "Many migratory bird species travel thousands of miles between breeding and wintering grounds each year.",
            "Some species appear to use the position of the sun during the day and star patterns at night to maintain direction.",
            "Other evidence suggests birds can sense Earth's magnetic field, possibly through specialized cells or light-sensitive proteins in their eyes.",
            "Young birds on their first migration often complete the journey successfully even without an experienced adult to follow.",
            "This suggests that at least part of the navigational ability is present from birth rather than fully learned.",
        ],
        "main_idea": "Migratory birds appear to rely on multiple, partly innate senses to navigate long distances.",
        "main_idea_wrong": ["Birds navigate exclusively by following experienced adults.", "Migratory birds cannot sense Earth's magnetic field.",
                              "Young birds are unable to complete a migration on their first attempt."],
        "inference": "Bird navigation likely does not depend entirely on learned experience.",
        "inference_wrong": ["All aspects of bird navigation must be learned from adults.", "Star patterns play no role in any species' navigation.",
                              "Migratory distance has no relationship to navigational ability."],
        "evidence_claim": "some navigational ability appears to be present without prior experience",
        "evidence_correct_idx": 3,
    },
    {
        "topic": "microplastic pollution in oceans", "sentences": [
            "Plastic debris in the ocean gradually breaks down into fragments smaller than five millimeters, known as microplastics.",
            "These particles have been found in ocean water at every depth studied, from the surface to deep-sea trenches.",
            "Small marine organisms sometimes mistake microplastics for food, allowing the particles to enter the food chain.",
            "Researchers have since detected microplastics in fish and shellfish commonly eaten by humans.",
            "Several countries have banned microbeads, a common source of microplastics once used in cosmetic products.",
        ],
        "main_idea": "Microplastics have spread throughout the ocean and entered the food chain, prompting some regulatory responses.",
        "main_idea_wrong": ["Microplastics are found only at the ocean's surface.", "No country has taken regulatory action on microplastic sources.",
                              "Marine organisms never mistake microplastics for food."],
        "inference": "Microplastic contamination in the food chain may eventually affect human diets.",
        "inference_wrong": ["Microplastics cannot enter the human food supply under any circumstances.", "Microbeads were banned before microplastics were discovered in the ocean.",
                              "Microplastics remain concentrated only in shallow coastal waters."],
        "evidence_claim": "microplastics have been detected in food that humans commonly eat",
        "evidence_correct_idx": 3,
    },
    {
        "topic": "four-day work week trials", "sentences": [
            "Several companies have piloted a four-day work week with no reduction in employee pay.",
            "One widely reported trial found that most participating companies maintained similar revenue over the trial period.",
            "Surveyed employees in these trials frequently reported lower stress and improved work-life balance.",
            "Some roles, particularly those requiring continuous coverage like customer support, proved harder to adapt to the shorter schedule.",
            "Most companies that completed a trial chose to continue the four-day schedule afterward.",
        ],
        "main_idea": "Four-day work week trials have generally shown positive results for both companies and employees, though not every role adapts easily.",
        "main_idea_wrong": ["Every company that tried a four-day week saw revenue decline sharply.", "Employees reported no change in stress levels during the trials.",
                              "All job roles adapted equally well to a four-day schedule."],
        "inference": "The four-day work week may be easier to implement in some kinds of jobs than others.",
        "inference_wrong": ["A four-day week works equally well for every type of job.", "Customer support roles were the easiest to adapt to a shorter week.",
                              "No company has continued a four-day week after a trial."],
        "evidence_claim": "companies were satisfied enough with the trial to keep the new schedule",
        "evidence_correct_idx": 4,
    },
    {
        "topic": "antibiotic resistance in bacteria", "sentences": [
            "Bacteria can develop resistance to an antibiotic through random genetic mutations that happen to survive the drug's effects.",
            "When an antibiotic kills off non-resistant bacteria, the surviving resistant ones can multiply without competition.",
            "Overuse of antibiotics, including for illnesses they cannot treat, is believed to accelerate this process.",
            "Some resistant bacteria can even transfer their resistance genes directly to other, unrelated bacteria.",
            "Public health agencies now recommend prescribing antibiotics only when a bacterial infection is confirmed.",
        ],
        "main_idea": "Antibiotic resistance spreads through natural selection and gene transfer, and overuse of antibiotics is believed to speed up the process.",
        "main_idea_wrong": ["Antibiotic resistance can only be inherited from a bacterium's direct parent.", "Overusing antibiotics has no effect on resistance rates.",
                              "Public health agencies recommend prescribing antibiotics for all illnesses."],
        "inference": "Reducing unnecessary antibiotic use could help slow the spread of resistant bacteria.",
        "inference_wrong": ["Antibiotic use has no relationship to how quickly resistance spreads.", "Resistant bacteria cannot multiply once non-resistant bacteria are killed.",
                              "Gene transfer between bacteria species has never been observed."],
        "evidence_claim": "resistant bacteria can spread their resistance beyond their own direct offspring",
        "evidence_correct_idx": 3,
    },
    {
        "topic": "the Silk Road's economic role", "sentences": [
            "The Silk Road was not a single road but a network of trade routes connecting East Asia to the Mediterranean.",
            "Merchants along the routes exchanged not only silk but also spices, precious metals, and glassware.",
            "Ideas, religious practices, and technologies spread alongside these goods as travelers moved between regions.",
            "Few merchants traveled the entire route themselves; instead, goods typically passed through many hands along the way.",
            "The network declined in importance after sea routes offered a faster, cheaper way to move goods over long distances.",
        ],
        "main_idea": "The Silk Road was a network that facilitated the exchange of goods and ideas across Eurasia until sea trade made it less essential.",
        "main_idea_wrong": ["The Silk Road was a single continuous road traveled start to finish by individual merchants.", "Only silk was traded along the Silk Road.",
                              "The Silk Road remained the dominant trade route after sea routes were established."],
        "inference": "Cultural exchange along the Silk Road likely happened gradually, through many intermediaries rather than direct long-distance contact.",
        "inference_wrong": ["Every merchant on the Silk Road traveled its full length.", "The Silk Road had no effect on the spread of ideas.",
                              "Sea routes were slower and more expensive than the Silk Road."],
        "evidence_claim": "goods on the Silk Road were typically exchanged through a chain of traders rather than one continuous journey",
        "evidence_correct_idx": 3,
    },
    {
        "topic": "memory consolidation during sleep", "sentences": [
            "Researchers have found that people who sleep after learning new information tend to recall it better than those who stay awake for the same period.",
            "Brain imaging during sleep shows patterns of activity resembling those recorded while the information was first learned.",
            "This replay is thought to help move memories from short-term to more stable long-term storage.",
            "Deep sleep, rather than lighter stages of sleep, appears to play the largest role in this process.",
            "Sleep deprivation, correspondingly, has been linked to poorer performance on memory-based tasks.",
        ],
        "main_idea": "Sleep, particularly deep sleep, appears to play an active role in converting new information into lasting memory.",
        "main_idea_wrong": ["Sleep has no measurable effect on memory recall.", "Light sleep contributes more to memory consolidation than deep sleep does.",
                              "Sleep deprivation improves performance on memory tasks."],
        "inference": "The brain may reprocess recent experiences during sleep rather than being fully inactive.",
        "inference_wrong": ["Brain activity stops entirely during sleep.", "Memory consolidation happens exclusively while a person is awake.",
                              "All stages of sleep contribute equally to memory consolidation."],
        "evidence_claim": "the brain replays patterns from earlier learning while a person sleeps",
        "evidence_correct_idx": 1,
    },
    {
        "topic": "managing invasive species", "sentences": [
            "An invasive species is one introduced, often by humans, to an environment where it did not naturally occur.",
            "Without natural predators, invasive species can multiply rapidly and outcompete native wildlife for resources.",
            "Some regions have introduced natural predators of the invasive species as a control method, though this carries its own risks.",
            "Other programs rely on manual removal or trapping, which is labor-intensive but more predictable in its effects.",
            "Prevention, such as inspecting cargo for stowaway organisms, is generally considered more effective than removal after the fact.",
        ],
        "main_idea": "Invasive species pose ecological risks once established, and prevention is generally more effective than the available removal methods.",
        "main_idea_wrong": ["Invasive species always have natural predators in their new environment.", "Manual removal is considered more effective than prevention.",
                              "Introducing new predators to control invasive species carries no risk."],
        "inference": "Stopping an invasive species before it establishes itself is likely easier than controlling it afterward.",
        "inference_wrong": ["Prevention methods are less effective than every removal method.", "Invasive species never compete with native wildlife for resources.",
                              "All control methods for invasive species carry identical levels of risk."],
        "evidence_claim": "attempting to control an invasive species with another species carries its own downsides",
        "evidence_correct_idx": 2,
    },
    {
        "topic": "the rise of telemedicine", "sentences": [
            "Remote medical consultations were a small part of healthcare before 2020, used mainly in rural areas with limited access to specialists.",
            "Usage expanded rapidly once in-person visits became harder to arrange, with many clinics offering video appointments for the first time.",
            "Studies since then have found telemedicine effective for many routine follow-ups and prescription renewals.",
            "Certain conditions, particularly ones requiring physical examination or lab work, still generally require an in-person visit.",
            "Even after in-person visits became easier again, many patients continued to choose telemedicine appointments when appropriate.",
        ],
        "main_idea": "Telemedicine expanded rapidly and has remained popular for the kinds of visits it suits, even though some care still requires an in-person appointment.",
        "main_idea_wrong": ["Telemedicine has fully replaced in-person medical visits.", "Telemedicine was equally common before and after 2020.",
                              "No patients continued using telemedicine once in-person visits became available again."],
        "inference": "Patient preference, not just necessity, has helped sustain telemedicine's popularity.",
        "inference_wrong": ["Telemedicine usage depends entirely on whether in-person visits are possible.", "All medical conditions can be diagnosed remotely.",
                              "Telemedicine was rejected by patients once in-person care became available."],
        "evidence_claim": "some patients kept choosing telemedicine even when it was no longer their only option",
        "evidence_correct_idx": 4,
    },
    {
        "topic": "the science of sourdough fermentation", "sentences": [
            "Sourdough bread rises without commercial yeast, relying instead on a starter culture of wild yeast and bacteria.",
            "The bacteria in the starter produce lactic and acetic acid, which give sourdough its characteristic tang.",
            "These acids also lower the dough's pH enough to slow the growth of mold, helping the bread stay fresh longer than bread made with commercial yeast alone.",
            "A starter must be fed regularly with fresh flour and water to keep its microbial population active.",
            "Bakers in different regions often maintain starters with distinct microbial populations, which can produce noticeably different flavors from the same basic recipe.",
        ],
        "main_idea": "Sourdough's distinct qualities come from the specific microbial activity in its starter culture, not just the basic recipe.",
        "main_idea_wrong": ["Sourdough bread requires commercial yeast to rise properly.", "All sourdough starters produce identical results regardless of location.",
                              "The acids in sourdough starter accelerate mold growth."],
        "inference": "The way a starter is maintained can meaningfully affect the bread it produces.",
        "inference_wrong": ["A starter's microbial population has no effect on bread flavor.", "Sourdough starters do not require regular feeding.",
                              "All bread relies on the same fermentation process as sourdough."],
        "evidence_claim": "sourdough's acidity helps it resist spoilage",
        "evidence_correct_idx": 2,
    },
    {
        "topic": "lightning detection networks", "sentences": [
            "Every lightning strike emits a burst of radio waves that can travel thousands of miles.",
            "Networks of ground-based sensors detect these radio bursts and use the tiny differences in arrival time between stations to calculate where a strike occurred.",
            "This method can pinpoint a strike's location to within a few hundred meters in areas with good sensor coverage.",
            "Meteorologists use this real-time strike data to track how a storm is intensifying, often before radar alone would show it.",
            "Some airports use the same data to decide when to pause ground operations for lightning safety.",
        ],
        "main_idea": "Lightning detection networks use the timing of radio signals to locate strikes precisely and support real-time decisions.",
        "main_idea_wrong": ["Lightning strikes cannot be detected until a storm has already passed.", "Radio bursts from lightning are too weak to detect from a distance.",
                              "Only radar, not radio detection, is used to track lightning."],
        "inference": "Precise, real-time lightning data can support safety decisions that would otherwise rely on less immediate information.",
        "inference_wrong": ["Airports never use lightning data to make operational decisions.", "Strike location can only be estimated after a storm ends.",
                              "Radar makes lightning detection networks unnecessary."],
        "evidence_claim": "the detection method can locate a strike with meaningful precision",
        "evidence_correct_idx": 2,
    },
    {
        "topic": "the invention of the zipper", "sentences": [
            "Early versions of a slide fastener in the 1890s were unreliable and prone to popping open.",
            "A 1913 redesign added interlocking teeth with a scoop shape that gripped more securely than earlier hook-based designs.",
            "Even with the improved design, clothing manufacturers were slow to adopt it, initially using it mainly on boots and tobacco pouches.",
            "Widespread use in clothing did not take off until decades later, after a major fashion designer featured it prominently.",
            "Today the same basic tooth-and-slider mechanism remains largely unchanged from that early design.",
        ],
        "main_idea": "The zipper's core mechanism was developed decades before it became widely used in clothing.",
        "main_idea_wrong": ["The zipper was immediately adopted by clothing manufacturers after its invention.", "The zipper's design has changed dramatically since 1913.",
                              "The first slide fasteners were more reliable than later versions."],
        "inference": "A technically successful invention does not necessarily gain widespread use right away.",
        "inference_wrong": ["Every successful invention is adopted immediately upon release.", "The zipper was rejected by all industries until modern times.",
                              "Fashion designers had no influence on the zipper's adoption."],
        "evidence_claim": "early adoption of the zipper was limited to a narrow set of uses",
        "evidence_correct_idx": 2,
    },
    {
        "topic": "ocean acidification", "sentences": [
            "The ocean absorbs roughly a quarter of the carbon dioxide humans release into the atmosphere.",
            "When carbon dioxide dissolves in seawater, it forms carbonic acid, gradually lowering the water's pH.",
            "This shift makes it harder for organisms like corals and some shellfish to build their calcium carbonate shells and skeletons.",
            "Laboratory studies show that some shellfish larvae raised in more acidic water develop thinner, weaker shells.",
            "Because these organisms sit near the base of many marine food webs, their decline could affect species that depend on them.",
        ],
        "main_idea": "Ocean acidification, driven by absorbed carbon dioxide, threatens shell-building marine organisms and the food webs built on them.",
        "main_idea_wrong": ["The ocean absorbs no carbon dioxide from the atmosphere.", "Acidification makes it easier for shellfish to build shells.",
                              "Ocean pH has remained completely stable despite rising carbon dioxide levels."],
        "inference": "A change affecting organisms at the base of a food web could have effects reaching beyond those organisms alone.",
        "inference_wrong": ["Only shellfish are affected by any change in ocean chemistry.", "Food webs are unaffected by changes to the species within them.",
                              "Carbonic acid has no relationship to seawater pH."],
        "evidence_claim": "more acidic water can directly weaken a shellfish's physical development",
        "evidence_correct_idx": 3,
    },
    {
        "topic": "urban beekeeping", "sentences": [
            "In the past two decades, many cities have lifted restrictions on keeping beehives on rooftops and in backyards.",
            "Some researchers have found that urban bee colonies can be as healthy as rural ones, thanks to the variety of flowering plants in city parks and gardens.",
            "Urban beekeeping has also been promoted as a way to raise public awareness of pollinator health.",
            "Critics note that a high density of hives in one area can strain the local nectar supply, potentially harming wild native bee populations.",
            "Some cities now recommend a maximum number of hives per area to balance these competing concerns.",
        ],
        "main_idea": "Urban beekeeping offers real benefits but also raises concerns about competition with wild bee populations.",
        "main_idea_wrong": ["Urban bee colonies are always less healthy than rural ones.", "No city has ever restricted the number of hives allowed in an area.",
                              "Urban beekeeping has no effect on public awareness of pollinators."],
        "inference": "Managing urban beekeeping well may require balancing its benefits against risks to other species.",
        "inference_wrong": ["Wild native bee populations are never affected by managed hives.", "There is no upper limit to how many hives an area can support.",
                              "Urban beekeeping provides no benefit to public awareness."],
        "evidence_claim": "too many hives in one place can create a problem for other pollinators",
        "evidence_correct_idx": 3,
    },
    {
        "topic": "the Antikythera mechanism", "sentences": [
            "In 1901, divers recovered a corroded bronze device from an ancient shipwreck near a small Greek island.",
            "For decades, the device's true purpose remained unclear because of how badly it had corroded.",
            "Modern X-ray imaging eventually revealed over thirty interlocking bronze gears inside the device.",
            "Researchers determined the mechanism could track the positions of the sun and moon and predict eclipses years in advance.",
            "No comparably complex geared device is known to have existed again for well over a thousand years afterward.",
        ],
        "main_idea": "The Antikythera mechanism was a surprisingly advanced ancient device for astronomical prediction, understood only after modern imaging.",
        "main_idea_wrong": ["The device's purpose was obvious as soon as it was recovered in 1901.", "The mechanism contained only a single gear.",
                              "Similarly complex devices were common for centuries after it was built."],
        "inference": "Ancient engineering may have reached a level of complexity not matched again for a very long time afterward.",
        "inference_wrong": ["Devices of similar complexity were common throughout ancient history.", "The mechanism's gears were added long after it was originally built.",
                              "X-ray imaging revealed the device to be simpler than initially believed."],
        "evidence_claim": "modern technology was necessary to understand the device's construction",
        "evidence_correct_idx": 2,
    },
    {
        "topic": "noise-canceling headphone technology", "sentences": [
            "Active noise-canceling headphones use a microphone to sample the sound around the listener.",
            "A built-in processor then generates a sound wave that is the inverse of that incoming noise.",
            "When the two waves combine, they largely cancel each other out, reducing what the listener hears.",
            "This method works especially well on steady, low-frequency sounds like engine hum, but less well on sudden or high-pitched noises.",
            "Because of this limitation, many designs also rely on physical padding to block higher-frequency sound separately.",
        ],
        "main_idea": "Active noise cancellation works by generating an inverse sound wave, but it needs to be paired with physical blocking for full effectiveness.",
        "main_idea_wrong": ["Active noise cancellation blocks all types of sound equally well.", "Noise-canceling headphones work by amplifying incoming sound.",
                              "Physical padding is unnecessary in noise-canceling headphone design."],
        "inference": "No single noise-reduction method may be sufficient on its own for a fully quiet listening experience.",
        "inference_wrong": ["Active cancellation alone is sufficient for every type of noise.", "Physical padding works better than active cancellation for all sounds.",
                              "Steady, low-frequency sounds are the hardest type for active cancellation to reduce."],
        "evidence_claim": "active noise cancellation has a specific weakness that another method must address",
        "evidence_correct_idx": 3,
    },
    {
        "topic": "the discovery of penicillin", "sentences": [
            "In 1928, a researcher returned from vacation to find that mold had contaminated one of his bacterial culture plates.",
            "He noticed that bacteria near the mold had died, while colonies farther away continued to grow normally.",
            "This observation led him to isolate a substance produced by the mold that could kill certain bacteria.",
            "It took over a decade, and the work of several other researchers, to purify the substance enough for practical medical use.",
            "By the 1940s, the resulting antibiotic was being mass-produced to treat wounded soldiers.",
        ],
        "main_idea": "Penicillin's discovery began with a chance observation but required years of further work before becoming a usable medicine.",
        "main_idea_wrong": ["Penicillin was ready for medical use immediately after its discovery in 1928.", "The mold had no effect on the bacteria in the culture plate.",
                              "Only one researcher was involved in making penicillin usable."],
        "inference": "An important scientific discovery can depend on both a chance observation and years of subsequent effort.",
        "inference_wrong": ["Chance observations never lead to significant scientific discoveries.", "Purifying penicillin required no additional research after 1928.",
                              "Mass production of penicillin began before it was fully purified."],
        "evidence_claim": "additional researchers were needed to make the discovery medically useful",
        "evidence_correct_idx": 3,
    },
    {
        "topic": "wildfire smoke forecasting", "sentences": [
            "Wildfire smoke can travel hundreds of miles from its source, affecting air quality far from the actual fire.",
            "Forecasters combine satellite imagery, wind data, and fire behavior models to predict where smoke will spread over the next few days.",
            "These forecasts are far from perfect, since a fire's intensity and the smoke it produces can change quickly.",
            "Public health agencies use the forecasts to issue air quality warnings before smoke actually arrives in a given area.",
            "Some regions have started distributing air purifiers in advance of high-risk fire seasons based on these predictive models.",
        ],
        "main_idea": "Wildfire smoke forecasting combines several data sources to give communities advance warning, despite real limits on accuracy.",
        "main_idea_wrong": ["Wildfire smoke never travels beyond the immediate area of a fire.", "Smoke forecasts are always perfectly accurate.",
                              "Public health agencies wait until smoke arrives before issuing any warnings."],
        "inference": "Even an imperfect forecast can still provide practical value if it arrives before conditions worsen.",
        "inference_wrong": ["A forecast must be perfectly accurate to be useful to public health agencies.", "Fire intensity never changes quickly enough to affect a forecast.",
                              "Wind data has no role in predicting where smoke will travel."],
        "evidence_claim": "communities take preparatory action based on predictions rather than waiting for smoke to arrive",
        "evidence_correct_idx": 4,
    },
    {
        "topic": "standardizing railroad track gauge", "sentences": [
            "In the early days of railroads, different companies built lines using different track widths, or gauges.",
            "This meant that a train built for one company's tracks often could not run on a neighboring company's line.",
            "Goods traveling across multiple rail networks sometimes had to be unloaded and reloaded onto a different train at each gauge change.",
            "Over the second half of the nineteenth century, many countries gradually converged on a single standard gauge.",
            "The change allowed a single train to travel much longer distances without stopping to switch cars.",
        ],
        "main_idea": "Inconsistent railroad gauges once limited long-distance rail travel until standardization solved the problem.",
        "main_idea_wrong": ["All railroads used the same track gauge from the very beginning.", "Standardizing gauge made long-distance travel more difficult.",
                              "Goods never needed to be transferred between trains before standardization."],
        "inference": "A lack of shared technical standards can create real practical costs even when each individual system works fine on its own.",
        "inference_wrong": ["Differing gauges had no effect on the efficiency of rail transport.", "Standardization efforts failed to change how trains were used.",
                              "Each railroad company's system worked equally well regardless of gauge differences."],
        "evidence_claim": "differing gauges created extra labor when goods crossed between rail networks",
        "evidence_correct_idx": 2,
    },
    {
        "topic": "virtual reality in medical training", "sentences": [
            "Some medical schools now use virtual reality simulations to let students practice procedures before working on real patients.",
            "These simulations can recreate rare complications that a student might otherwise never encounter during training.",
            "Studies comparing VR-trained students to traditionally trained students have found mixed results depending on the specific skill being measured.",
            "VR training is also significantly cheaper than using cadavers or live animals for every practice session.",
            "Most programs currently use VR simulation to supplement, rather than replace, hands-on clinical training.",
        ],
        "main_idea": "Virtual reality offers a cost-effective way to expose medical students to rare scenarios, though it currently supplements rather than replaces hands-on training.",
        "main_idea_wrong": ["VR training has completely replaced hands-on clinical training in medical schools.", "VR simulations cannot recreate rare medical complications.",
                              "Studies have found VR training to be worse than traditional training in every measured skill."],
        "inference": "The value of VR training may depend on which specific skill is being taught.",
        "inference_wrong": ["VR training produces identical results for every medical skill.", "Cost has no bearing on whether a training method is adopted.",
                              "Rare complications cannot be simulated using any current technology."],
        "evidence_claim": "VR training offers a financial advantage over some traditional training methods",
        "evidence_correct_idx": 3,
    },
    {
        "topic": "deciphering the Rosetta Stone", "sentences": [
            "The Rosetta Stone, discovered in 1799, contains the same decree written in three scripts: hieroglyphics, a simpler Egyptian script, and ancient Greek.",
            "Scholars could already read the Greek text, but ancient Egyptian hieroglyphics had not been understood for centuries.",
            "By comparing repeated names and words across the three versions, researchers gradually matched hieroglyphic symbols to their meanings.",
            "One researcher's breakthrough was recognizing that some hieroglyphs represented sounds, not just whole ideas or objects.",
            "Full decipherment took over twenty years of comparative work after the stone's discovery.",
        ],
        "main_idea": "The Rosetta Stone allowed scholars to decode hieroglyphics through years of careful comparison across its three parallel texts.",
        "main_idea_wrong": ["Hieroglyphics were already fully understood before the Rosetta Stone was found.", "The stone contains only a single script.",
                              "Decipherment was completed within a few days of the stone's discovery."],
        "inference": "Having a known translation alongside an unknown text can make it possible to decode the unknown text over time.",
        "inference_wrong": ["The Greek text on the stone was just as mysterious as the hieroglyphics.", "Repeated names across the texts provided no useful information.",
                              "Hieroglyphs exclusively represent whole ideas, never sounds."],
        "evidence_claim": "recognizing hieroglyphs could represent sounds was a turning point in the decoding process",
        "evidence_correct_idx": 3,
    },
    {
        "topic": "urban vertical farming", "sentences": [
            "Vertical farms grow crops in stacked layers indoors, often under LED lighting rather than sunlight.",
            "This approach can produce far more food per square foot of land than a traditional outdoor farm.",
            "Because the growing environment is enclosed, vertical farms can operate year-round regardless of outdoor weather or season.",
            "The high cost of electricity for lighting and climate control remains a major barrier to profitability for many operations.",
            "Some vertical farms have focused on high-value crops like leafy greens and herbs, where the higher price can offset the added energy cost.",
        ],
        "main_idea": "Vertical farming offers land and weather advantages but faces a significant energy-cost barrier that shapes which crops it grows.",
        "main_idea_wrong": ["Vertical farms use less land-efficient methods than traditional outdoor farms.", "Vertical farms are affected by outdoor weather just as much as traditional farms.",
                              "Energy costs are not a concern for vertical farming operations."],
        "inference": "The economics of vertical farming may favor certain types of crops over others.",
        "inference_wrong": ["Every crop is equally profitable to grow in a vertical farm.", "Vertical farms cannot operate during any particular season.",
                              "Land efficiency has no bearing on a farm's overall output."],
        "evidence_claim": "some growers have found a way to make the higher energy costs worthwhile",
        "evidence_correct_idx": 4,
    },
    {
        "topic": "the psychology of choice overload", "sentences": [
            "A well-known study found that shoppers presented with a smaller selection of jam flavors were more likely to make a purchase than those given a much larger selection.",
            "Researchers describe this as choice overload: too many options can make a decision feel more effortful rather than more satisfying.",
            "Later studies attempting to replicate the effect have found it depends heavily on context, such as how much the chooser already knows about the options.",
            "Some retailers have used this research to justify curating a smaller set of options rather than offering everything available.",
            "Other researchers caution that reducing options can also limit genuine variety that some customers value.",
        ],
        "main_idea": "Choice overload research suggests more options can sometimes reduce satisfaction, but the effect is context-dependent and contested.",
        "main_idea_wrong": ["Every study has found that more choices always increase satisfaction.", "Choice overload has been proven to occur in every context studied.",
                              "Retailers universally reject the idea of limiting product selection."],
        "inference": "How familiar someone is with their options may influence whether having more choices helps or hurts their decision.",
        "inference_wrong": ["Prior knowledge of options has no bearing on decision-making.", "The original jam study has been perfectly replicated in every later attempt.",
                              "Limiting options never has any drawback for customers."],
        "evidence_claim": "the choice-overload effect does not appear consistently across different studies",
        "evidence_correct_idx": 2,
    },
    {
        "topic": "desalination technology", "sentences": [
            "Desalination plants remove salt from seawater to produce fresh water for drinking or irrigation.",
            "The most common modern method, reverse osmosis, forces seawater through a membrane that blocks salt molecules while letting water pass through.",
            "This process requires significant amounts of energy, which has historically made desalinated water more expensive than water from rivers or groundwater.",
            "The leftover concentrated saltwater, called brine, must be disposed of carefully to avoid harming marine ecosystems near the outflow point.",
            "Some coastal regions with limited freshwater sources have invested heavily in desalination despite these costs, treating it as a necessary tradeoff.",
        ],
        "main_idea": "Desalination provides a valuable freshwater source for water-scarce regions, despite real energy costs and environmental tradeoffs.",
        "main_idea_wrong": ["Desalination produces no waste byproduct of any kind.", "Reverse osmosis works by adding salt to fresh water.",
                              "Desalinated water is always cheaper than water from rivers or groundwater."],
        "inference": "Some regions may consider desalination worthwhile even when it is not the cheapest available option.",
        "inference_wrong": ["No region has ever chosen desalination despite its higher cost.", "Brine disposal has no potential effect on marine ecosystems.",
                              "Reverse osmosis requires no energy to operate."],
        "evidence_claim": "the leftover byproduct of desalination requires careful handling",
        "evidence_correct_idx": 3,
    },
]


def t_central_idea(rng: random.Random) -> dict:
    entry = rng.choice(PASSAGES)
    passage = " ".join(entry["sentences"])
    prompt = "Which choice best states the main idea of the text?"
    choices, ans = build_choices(rng, entry["main_idea"], entry["main_idea_wrong"])
    return blank("rw", "Information & Ideas", "Central ideas and details", 2, prompt, choices, ans,
                 "The main idea has to be broad enough to cover the whole passage but specific enough to be supported by it — not a single detail, and not an unsupported leap.",
                 passage=passage)


def t_inference(rng: random.Random) -> dict:
    entry = rng.choice(PASSAGES)
    passage = " ".join(entry["sentences"])
    prompt = "Which choice is most strongly supported by the text as an inference (not stated directly)?"
    choices, ans = build_choices(rng, entry["inference"], entry["inference_wrong"])
    return blank("rw", "Information & Ideas", "Inferences", 3, prompt, choices, ans,
                 "A sound inference follows logically from what the text states without being stated outright, and it can't contradict any detail in the passage.",
                 passage=passage)


def t_evidence_textual(rng: random.Random) -> dict:
    entry = rng.choice(PASSAGES)
    passage = " ".join(entry["sentences"])
    correct_idx = entry["evidence_correct_idx"]
    correct = entry["sentences"][correct_idx]
    other_sentences = [s for i, s in enumerate(entry["sentences"]) if i != correct_idx]
    distractors = rng.sample(other_sentences, min(3, len(other_sentences)))
    prompt = f"Which sentence from the text most directly supports the claim that {entry['evidence_claim']}?"
    choices, ans = build_choices(rng, correct, distractors)
    return blank("rw", "Information & Ideas", "Command of evidence", 3, prompt, choices, ans,
                 f"The claim is specifically that {entry['evidence_claim']} — only one sentence in the text directly addresses that.",
                 passage=passage)


QUANT_SCENARIOS = [
    {"intro": "A researcher tracked average commute times (in minutes) in a city for five years after a new light-rail line opened.",
     "row_label": "Year", "value_label": "Average commute time (minutes)", "direction": "decreased"},
    {"intro": "A wildlife biologist tracked the estimated population of a recovering species over five years after a hunting ban.",
     "row_label": "Year", "value_label": "Estimated population", "direction": "increased"},
    {"intro": "A school tracked average daily attendance (in percent) over five years after introducing a new tutoring program.",
     "row_label": "Year", "value_label": "Average attendance (%)", "direction": "increased"},
    {"intro": "An orchard tracked average yield (in tons per acre) over five years after adopting a new irrigation method.",
     "row_label": "Year", "value_label": "Average yield (tons/acre)", "direction": "increased"},
]


def t_evidence_quantitative(rng: random.Random) -> dict:
    scenario = rng.choice(QUANT_SCENARIOS)
    years = [2018 + i for i in range(5)]
    start_val = rng.randint(40, 90)
    step = rng.randint(3, 8)
    sign = 1 if scenario["direction"] == "increased" else -1
    values = [start_val + sign * step * i + rng.choice([-1, 0, 1]) for i in range(5)]
    table = {"headers": [scenario["row_label"], scenario["value_label"]],
              "rows": [[str(y), str(v)] for y, v in zip(years, values)]}
    diff = abs(values[-1] - values[0])
    prompt = (f"{scenario['intro']} Based on the table, from {years[0]} to {years[-1]}, the "
              f"{scenario['value_label'].lower()} {scenario['direction']} by approximately how much?")
    distractors = [diff + rng.choice([2, 3, -2, -3]) if diff + 2 != 0 else diff + 4, values[-1], values[0]]
    choices, ans = build_choices(rng, diff, distractors)
    return blank("rw", "Information & Ideas", "Command of evidence", 2, prompt, choices, ans,
                 f"{years[0]}'s value was {values[0]} and {years[-1]}'s value was {values[-1]}, a difference of {diff}.",
                 table=table)


# ────────────────────────────────── Text structure, purpose & cross-text ──────────────────────────────────

TEXT_STRUCTURE_SETS = [
    {"passage_idx": 0,  # bioluminescent deep-sea life
     "target_idx": 4, "correct": "To acknowledge a limit in current scientific understanding of the topic.",
     "wrong": ["To contradict the claim made in the first sentence.", "To introduce a completely new subject unrelated to bioluminescence.",
                "To summarize every detail mentioned earlier in the passage."]},
    {"passage_idx": 1,  # congestion pricing
     "target_idx": 4, "correct": "To present a response to the criticism raised earlier in the text.",
     "wrong": ["To introduce the passage's main topic for the first time.", "To provide a historical timeline of congestion pricing.",
                "To dismiss the idea that congestion pricing has any benefits."]},
    {"passage_idx": 2,  # Roman aqueducts
     "target_idx": 2, "correct": "To give a specific example of how engineers dealt with a particular obstacle.",
     "wrong": ["To argue that aqueducts rarely crossed valleys.", "To contradict the previous sentence's claim about leveling tools.",
                "To conclude the passage with a summary of Roman engineering."]},
    {"passage_idx": 3,  # exoplanets
     "target_idx": 4, "correct": "To explain the added value of using more than one detection method.",
     "wrong": ["To introduce the transit method for the first time.", "To argue that the wobble method is unreliable.",
                "To describe a method unrelated to detecting exoplanets."]},
    {"passage_idx": 7,  # placebo effect
     "target_idx": 3, "correct": "To explain a practical consequence of the phenomenon described earlier.",
     "wrong": ["To introduce a new, unrelated medical phenomenon.", "To contradict the claim that the placebo effect is measurable.",
                "To describe how placebos are manufactured."]},
    {"passage_idx": 9,  # plate tectonics
     "target_idx": 3, "correct": "To explain what the evidence described in the previous sentence actually shows.",
     "wrong": ["To introduce a completely separate piece of evidence.", "To argue against the existence of plate tectonics.",
                "To describe how fossils are dated."]},
    {"passage_idx": 12,  # honeybee waggle dance
     "target_idx": 4, "correct": "To note when scientific confirmation of the dance's meaning was actually established.",
     "wrong": ["To contradict the claim that the dance indicates direction.", "To introduce an entirely unrelated insect behavior.",
                "To argue that the dance has no real communicative function."]},
    {"passage_idx": 15,  # octopus camouflage
     "target_idx": 3, "correct": "To introduce a puzzle that complicates the explanation given earlier in the text.",
     "wrong": ["To summarize the mechanism described in the previous two sentences.", "To argue that octopuses cannot camouflage effectively.",
                "To introduce a completely different animal for comparison."]},
    {"passage_idx": 19,  # Roman concrete
     "target_idx": 3, "correct": "To explain the effect of the mineral deposits described in the previous sentence.",
     "wrong": ["To contradict the claim that Roman concrete is durable.", "To introduce a new, unrelated building material.",
                "To argue that modern concrete is superior overall."]},
    {"passage_idx": 23,  # antibiotic resistance
     "target_idx": 3, "correct": "To describe an additional way resistance can spread beyond what was already discussed.",
     "wrong": ["To contradict the claim that overuse accelerates resistance.", "To introduce a completely unrelated medical topic.",
                "To argue that antibiotic resistance cannot spread between bacteria."]},
    {"passage_idx": 28,  # sourdough fermentation
     "target_idx": 2, "correct": "To explain an additional benefit of the acidity introduced in the previous sentence.",
     "wrong": ["To contradict the claim that sourdough's acids create tang.", "To introduce a type of bread unrelated to sourdough.",
                "To argue that acidity has no effect on bread at all."]},
    {"passage_idx": 30,  # invention of the zipper
     "target_idx": 3, "correct": "To explain that broader adoption still took time even after the design had improved.",
     "wrong": ["To contradict the claim that the 1913 redesign was more secure.", "To introduce an entirely different invention.",
                "To argue that the redesign was never adopted by any industry."]},
    {"passage_idx": 33,  # urban beekeeping
     "target_idx": 3, "correct": "To introduce a potential drawback that complicates the benefits described earlier in the text.",
     "wrong": ["To confirm that urban hives never affect wild bee populations.", "To introduce a topic unrelated to beekeeping.",
                "To argue that cities should ban beekeeping outright."]},
    {"passage_idx": 36,  # wildfire smoke forecasting
     "target_idx": 2, "correct": "To acknowledge a limitation of the forecasting method described in the previous sentence.",
     "wrong": ["To contradict the claim that forecasters use satellite and wind data.", "To introduce a completely unrelated weather phenomenon.",
                "To argue that wildfire smoke forecasting is never useful."]},
    {"passage_idx": 40,  # deciphering the Rosetta Stone
     "target_idx": 3, "correct": "To identify a specific insight that advanced the decoding process described earlier.",
     "wrong": ["To contradict the claim that researchers compared repeated words across scripts.", "To introduce a document unrelated to the Rosetta Stone.",
                "To argue that hieroglyphs were never deciphered."]},
]


def t_text_structure_purpose(rng: random.Random) -> dict:
    entry = rng.choice(TEXT_STRUCTURE_SETS)
    source = PASSAGES[entry["passage_idx"]]
    passage = " ".join(source["sentences"])
    target_sentence = source["sentences"][entry["target_idx"]]
    prompt = f"Which choice best describes the function of the sentence \"{target_sentence}\" in the text?"
    choices, ans = build_choices(rng, entry["correct"], entry["wrong"])
    return blank("rw", "Craft & Structure", "Text structure and purpose", 3, prompt, choices, ans,
                 "Look at what the sentence does relative to the sentence right before it — introduce, support, explain, contrast, or conclude — not just what topic it mentions.",
                 passage=passage)


CROSS_TEXT_PAIRS = [
    {"topic": "screen time and children's development",
     "text1": "Text 1: Several studies have linked heavy screen use in early childhood to shorter attention spans in later years. Pediatric guidelines now recommend strict daily limits on recreational screen time for children under six.",
     "text2": "Text 2: Critics of screen-time research point out that most studies rely on parent-reported estimates, which are notoriously imprecise. Until screen use can be measured more objectively, they argue, strong causal claims about its effects remain premature.",
     "correct": "Text 1 presents screen-time research as a basis for clear guidelines, while Text 2 questions the reliability of that same research.",
     "wrong": ["Both texts agree that screen-time research is methodologically sound.", "Text 1 questions the research that Text 2 defends.",
                "Neither text takes a position on the reliability of screen-time studies."]},
    {"topic": "a historical figure's reputation",
     "text1": "Text 1: Contemporary accounts describe the inventor as reclusive and difficult to work with, often dismissing collaborators' ideas outright.",
     "text2": "Text 2: Letters discovered decades later reveal a more collaborative figure, one who credited assistants by name and revised his own designs based on their feedback.",
     "correct": "Text 2 offers evidence that complicates the portrayal of the inventor presented in Text 1.",
     "wrong": ["Text 2 simply repeats the claims made in Text 1.", "Text 1 was written after Text 2 and responds directly to it.",
                "Both texts describe the inventor in exactly the same way."]},
    {"topic": "a proposed economic policy",
     "text1": "Text 1: Proponents argue the policy would raise wages for the lowest-paid workers without meaningfully increasing unemployment, citing regions where similar measures had little negative effect on hiring.",
     "text2": "Text 2: Opponents counter that results vary widely by local labor market, and that regions with different industries have seen measurable job losses following similar policies.",
     "correct": "Text 1 emphasizes cases where the policy caused little harm, while Text 2 emphasizes cases where it caused measurable harm.",
     "wrong": ["Text 1 and Text 2 rely on identical evidence to reach the same conclusion.", "Text 2 argues the policy has no effect on wages at all.",
                "Text 1 focuses on job losses while Text 2 focuses on wage increases."]},
    {"topic": "the extinction of a species",
     "text1": "Text 1: Some researchers argue that a rapid change in climate was the primary driver of the species' extinction, pointing to a sharp shift in fossilized pollen records at the same time.",
     "text2": "Text 2: Other researchers argue that competition from a newly arrived species was the more direct cause, noting that the decline began before the climate records show major change.",
     "correct": "The two texts propose different primary causes for the same extinction event.",
     "wrong": ["Both texts agree that competition was the main cause of extinction.", "Text 1 argues that no single cause can be identified.",
                "Text 2 supports the climate-based explanation given in Text 1."]},
    {"topic": "a city's approach to affordable housing",
     "text1": "Text 1: One city built thousands of new subsidized units directly, arguing that public construction was the fastest way to increase supply.",
     "text2": "Text 2: A neighboring city instead offered tax incentives to private developers who included affordable units in new buildings, arguing the approach would scale faster with less public cost.",
     "correct": "The two cities pursued different strategies for the same underlying goal of increasing affordable housing.",
     "wrong": ["Both cities relied entirely on private developers.", "Text 2 describes a city that built no new housing at all.",
                "The two texts describe identical housing policies."]},
    {"topic": "the safety of a food additive",
     "text1": "Text 1: A large long-term study found no significant difference in health outcomes between regular consumers of the additive and non-consumers, leading regulators in several countries to maintain its approved status.",
     "text2": "Text 2: A smaller study using higher doses than typically consumed found measurable effects on lab animals, leading some researchers to call for stricter limits pending further human research.",
     "correct": "Text 1 reports findings that support current regulation, while Text 2 reports findings that raise doubts about it.",
     "wrong": ["Both texts conclude the additive should be banned immediately.", "Text 2 confirms the exact findings reported in Text 1.",
                "Text 1 is based on animal research while Text 2 is based on human research."]},
    {"topic": "remote work productivity",
     "text1": "Text 1: A survey of software companies found that fully remote teams shipped projects on a similar timeline to in-office teams, with employees reporting higher satisfaction.",
     "text2": "Text 2: A separate study of the same industry found that fully remote new hires took noticeably longer to reach full productivity, likely due to fewer informal opportunities to ask questions.",
     "correct": "Text 1 focuses on overall team output, while Text 2 focuses on a specific challenge for new employees working remotely.",
     "wrong": ["Text 1 and Text 2 studied identical outcomes and reached identical conclusions.", "Text 2 argues remote work has no drawbacks whatsoever.",
                "Text 1 concludes that remote work reduces employee satisfaction."]},
    {"topic": "a proposed dam removal",
     "text1": "Text 1: Environmental groups argue that removing the aging dam would restore fish migration routes and improve water quality, citing similar projects elsewhere that succeeded.",
     "text2": "Text 2: Local farmers argue the dam's reservoir is essential for irrigation during dry months, and that removal would threaten crops without a proven replacement water source.",
     "correct": "The two texts represent different stakeholder priorities regarding the same proposed dam removal.",
     "wrong": ["Both texts agree the dam should be removed immediately.", "Text 2 focuses on fish migration rather than irrigation.",
                "The two texts describe entirely unrelated dams."]},
    {"topic": "an ancient civilization's decline",
     "text1": "Text 1: Some archaeologists point to a decades-long drought, evidenced by tree-ring data, as the primary factor behind the civilization's collapse.",
     "text2": "Text 2: Others emphasize internal political fragmentation, noting that regional centers show signs of conflict predating the drought evidence by several decades.",
     "correct": "The two texts emphasize different timelines and causes for the same historical collapse.",
     "wrong": ["Both texts rely on identical tree-ring evidence.", "Text 2 argues that no conflict occurred before the civilization's collapse.",
                "Text 1 and Text 2 agree entirely on the cause of the collapse."]},
    {"topic": "urban tree-planting programs",
     "text1": "Text 1: Advocates argue that large-scale tree planting lowers summer temperatures in cities and cite neighborhoods where planting programs measurably reduced heat compared to untreated blocks.",
     "text2": "Text 2: Skeptics note that many young trees die within a few years due to poor soil and inconsistent watering, arguing that survival rates matter more than the number of trees initially planted.",
     "correct": "Text 1 emphasizes the cooling benefits of tree planting, while Text 2 emphasizes a practical obstacle to realizing those benefits.",
     "wrong": ["Both texts agree that tree survival rates are irrelevant.", "Text 2 confirms every claim made in Text 1 without qualification.",
                "Text 1 argues that tree planting has no measurable effect on temperature."]},
    {"topic": "standardized testing in college admissions",
     "text1": "Text 1: Some universities that dropped standardized testing requirements report more diverse applicant pools without any decline in first-year academic performance.",
     "text2": "Text 2: Other researchers argue that without test scores, admissions officers rely more heavily on subjective factors like essays, which can favor applicants with more access to coaching and resources.",
     "correct": "Text 1 presents dropping testing requirements as broadly beneficial, while Text 2 raises a concern about an unintended effect of doing so.",
     "wrong": ["Both texts conclude that standardized testing should be mandatory everywhere.", "Text 2 provides the same evidence used in Text 1.",
                "Text 1 argues that essays are a more reliable measure than test scores."]},
    {"topic": "electric vehicle battery recycling",
     "text1": "Text 1: Battery manufacturers argue that new recycling processes can recover over 90% of the valuable metals in an old electric vehicle battery, reducing the need for new mining.",
     "text2": "Text 2: Environmental researchers counter that current recycling capacity is far too small to handle the wave of batteries expected to reach end of life within the next decade.",
     "correct": "Text 1 focuses on what recycling technology can achieve, while Text 2 focuses on whether current infrastructure can keep pace with demand.",
     "wrong": ["Both texts agree that recycling capacity is already sufficient.", "Text 2 disputes that any metals can be recovered from old batteries.",
                "Text 1 and Text 2 describe the same recycling process in identical terms."]},
    {"topic": "reintroducing predators to an ecosystem",
     "text1": "Text 1: Ecologists who studied a region after wolves were reintroduced found that deer populations declined and previously overgrazed vegetation began to recover.",
     "text2": "Text 2: Ranchers in the same region report increased losses of livestock and argue that the ecological benefits do not offset the economic cost to local farms.",
     "correct": "Text 1 highlights an ecological benefit of the reintroduction, while Text 2 highlights an economic cost borne by a different group.",
     "wrong": ["Both texts agree the reintroduction had no drawbacks.", "Text 2 confirms the same ecological findings reported in Text 1.",
                "Text 1 argues that wolf reintroduction harmed local vegetation."]},
    {"topic": "trials of a four-day work week",
     "text1": "Text 1: Companies that piloted a four-day work week reported that employee-measured productivity per hour increased enough to offset the reduced hours, with no loss in total output.",
     "text2": "Text 2: A separate analysis of similar pilots found that results varied significantly by industry, with output declining at firms that depend on tightly scheduled client-facing hours.",
     "correct": "Text 1 presents a generally positive outcome, while Text 2 complicates that picture by pointing to industry-specific exceptions.",
     "wrong": ["Both texts agree the four-day week fails in every industry.", "Text 2 relies on identical data to reach the same conclusion as Text 1.",
                "Text 1 focuses on client-facing industries specifically."]},
]


def t_cross_text_connections(rng: random.Random) -> dict:
    entry = rng.choice(CROSS_TEXT_PAIRS)
    passage = f"{entry['text1']}\n\n{entry['text2']}"
    prompt = f"Based on the texts, which choice best describes the relationship between Text 1 and Text 2 regarding {entry['topic']}?"
    choices, ans = build_choices(rng, entry["correct"], entry["wrong"])
    return blank("rw", "Craft & Structure", "Cross-text connections", 3, prompt, choices, ans,
                 "Identify what each text specifically claims, then compare those claims directly rather than assuming the texts must agree or disagree wholesale.",
                 passage=passage)


# ────────────────────────────────── Vocabulary ──────────────────────────────────

VOCAB = [
    ("volatile", "unstable and likely to change suddenly", ["predictable", "long-lasting", "widely accepted"]),
    ("candid", "openly honest and direct", ["evasive", "formal", "cautious"]),
    ("meticulous", "extremely careful about details", ["careless", "hurried", "indifferent"]),
    ("pragmatic", "focused on practical results", ["idealistic", "sentimental", "theoretical"]),
    ("ambiguous", "open to more than one interpretation", ["precise", "obvious", "conclusive"]),
    ("skeptical", "having doubts about a claim", ["trusting", "enthusiastic", "convinced"]),
    ("resilient", "able to recover quickly from difficulty", ["fragile", "exhausted", "indifferent"]),
    ("concise", "expressing much in few words", ["wordy", "vague", "repetitive"]),
    ("plausible", "reasonable or believable", ["absurd", "confirmed", "impossible"]),
    ("candor", "the quality of being open and honest", ["deception", "formality", "hesitation"]),
    ("mitigate", "to make less severe", ["intensify", "ignore", "prolong"]),
    ("ubiquitous", "present everywhere", ["rare", "hidden", "temporary"]),
    ("innovative", "introducing new ideas or methods", ["outdated", "conventional", "derivative"]),
    ("volatile", "prone to sudden change or violence", ["stable", "gentle", "consistent"]),
    ("prudent", "acting with careful judgment", ["reckless", "impulsive", "careless"]),
    ("tenuous", "weak or flimsy", ["strong", "certain", "obvious"]),
    ("empirical", "based on observation or experiment", ["theoretical", "imaginary", "traditional"]),
    ("redundant", "no longer needed; repetitive", ["essential", "original", "scarce"]),
    ("subtle", "not immediately obvious", ["blatant", "loud", "extreme"]),
    ("coherent", "logical and consistent", ["disjointed", "chaotic", "irrelevant"]),
    ("diligent", "showing careful, persistent effort", ["lazy", "careless", "distracted"]),
    ("comprehensive", "complete and including everything", ["partial", "narrow", "superficial"]),
    ("credible", "able to be believed", ["dubious", "fictional", "irrelevant"]),
    ("objective", "not influenced by personal feelings", ["biased", "emotional", "uncertain"]),
    ("succinct", "brief and clearly expressed", ["rambling", "confusing", "elaborate"]),
    ("arbitrary", "based on random choice, not reason", ["justified", "logical", "consistent"]),
    ("dubious", "not likely to be true; doubtful", ["certain", "proven", "trustworthy"]),
    ("elusive", "difficult to find or achieve", ["obvious", "guaranteed", "straightforward"]),
    ("robust", "strong and healthy; not easily broken", ["fragile", "minimal", "temporary"]),
    ("candid photo", "unposed and taken naturally", ["a staged photo", "an edited photo", "a formal portrait"]),
    ("erratic", "unpredictable and inconsistent", ["steady", "reliable", "uniform"]),
    ("frugal", "careful about spending money", ["wasteful", "generous to excess", "indifferent to cost"]),
    ("lucid", "clear and easy to understand", ["confusing", "vague", "incoherent"]),
    ("magnanimous", "generous and forgiving toward others", ["petty", "vindictive", "stingy"]),
    ("novel", "new and original", ["conventional", "outdated", "borrowed"]),
    ("obsolete", "no longer in use; outdated", ["current", "cutting-edge", "popular"]),
    ("partisan", "strongly favoring one side", ["neutral", "balanced", "impartial"]),
    ("quell", "to suppress or put an end to", ["provoke", "encourage", "ignore"]),
    ("reticent", "reluctant to speak about something", ["talkative", "forthcoming", "candid"]),
    ("scrutinize", "to examine closely and critically", ["ignore", "glance at", "approve without review"]),
    ("terse", "brief to the point of rudeness", ["elaborate", "friendly", "verbose"]),
    ("unprecedented", "never done or known before", ["routine", "expected", "familiar"]),
    ("vindicate", "to clear of blame or suspicion", ["condemn", "accuse", "implicate"]),
    ("wary", "cautious about possible danger", ["careless", "trusting blindly", "oblivious"]),
    ("zealous", "showing great energy for a cause", ["apathetic", "indifferent", "reluctant"]),
    ("adverse", "harmful or unfavorable", ["beneficial", "favorable", "helpful"]),
    ("benevolent", "kind and well-meaning", ["cruel", "malicious", "selfish"]),
    ("cynical", "distrustful of people's motives", ["trusting", "naive", "optimistic"]),
    ("deft", "skillful and quick in action", ["clumsy", "slow", "awkward"]),
    ("exacerbate", "to make a problem worse", ["improve", "resolve", "soothe"]),
    ("fastidious", "very attentive to detail and accuracy", ["sloppy", "careless", "indifferent"]),
    ("gregarious", "fond of company; sociable", ["withdrawn", "solitary", "shy"]),
    ("hackneyed", "overused and unoriginal", ["fresh", "original", "inventive"]),
    ("impartial", "not favoring one side over another", ["biased", "one-sided", "prejudiced"]),
    ("judicious", "having good judgment; sensible", ["reckless", "rash", "careless"]),
    ("keen interest", "an eager and enthusiastic interest", ["a passing interest", "no interest", "a reluctant interest"]),
    ("lament", "to express sorrow or regret about", ["celebrate", "dismiss", "ignore"]),
    ("myriad", "a very great number of", ["a handful of", "a single", "a rare"]),
    ("nuanced", "having subtle shades of meaning", ["oversimplified", "blunt", "one-dimensional"]),
    ("opulent", "grand and luxurious", ["modest", "plain", "sparse"]),
]

SENTENCE_FRAMES = [
    "The critic's review described the new policy as {word}, a characterization that sparked debate.",
    "In her closing argument, the lawyer's {word} approach to the evidence impressed the jury.",
    "Researchers noted that the results were {word}, prompting further study before any conclusion.",
    "The committee's decision was widely seen as {word} by those who had followed the negotiations.",
    "Colleagues often described the new director's management style as {word}, for better or worse.",
    "The historian's account of the era was praised as {word} by readers unfamiliar with the period.",
    "Investors grew uneasy after analysts labeled the startup's finances {word}.",
    "The editorial's tone struck many subscribers as unusually {word} for the newspaper.",
]


def t_words_in_context(rng: random.Random) -> dict:
    word, correct, wrongs = rng.choice(VOCAB)
    frame = rng.choice(SENTENCE_FRAMES)
    sentence = frame.format(word=word)
    prompt = f"{sentence}\n\nAs used in the text, the word \"{word.split()[0]}\" most nearly means:"
    choices, ans = build_choices(rng, correct, wrongs)
    return blank("rw", "Craft & Structure", "Words in context", 1, prompt, choices, ans,
                 f"In this context, \"{word.split()[0]}\" is used to mean \"{correct}.\"")


# ────────────────────────────────── registry ──────────────────────────────────

TEMPLATES = {
    "Algebra": [t_linear_one_two_step, t_linear_function_slope, t_system_two_linear,
                t_linear_inequality, t_linear_model_context, t_interpret_linear_model,
                t_linear_two_var_equation, t_system_number_of_solutions, t_function_notation_eval,
                t_parallel_perpendicular],
    "Advanced Math": [t_quadratic_factorable, t_quadratic_vertex, t_exponential_growth,
                       t_radical_equation, t_polynomial_factor_zeros, t_exponent_rules,
                       t_rational_equation, t_discriminant,
                       t_factor_expand, t_function_transformation, t_quadratic_formula,
                       t_completing_square, t_complex_numbers, t_complex_quadratic],
    "Problem-Solving & Data": [t_percentages, t_percent_change, t_rates_unit_rate,
                                 t_ratios_proportions, t_mean_center, t_two_way_table,
                                 t_scatterplot_model, t_inference_samples,
                                 t_compound_growth_decay, t_simple_probability, t_conditional_probability,
                                 t_median_range, t_line_of_best_fit],
    "Geometry & Trig": [t_circle, t_right_triangle_trig, t_angle_relationships, t_volume, t_similar_triangles,
                         t_special_right_triangle, t_circle_equation],
    "Standard English Conventions": [t_subject_verb_agreement, t_sentence_boundaries, t_possessives_plurals,
                                       t_verb_tense, t_colons_punctuation, t_finite_verbs_fragments,
                                       t_modifier_placement, t_pronoun_clarity, t_parallelism, t_dash_usage],
    "Craft & Structure": [t_words_in_context, t_text_structure_purpose, t_cross_text_connections],
    "Expression of Ideas": [t_transitions, t_rhetorical_synthesis],
    "Information & Ideas": [t_central_idea, t_inference, t_evidence_textual, t_evidence_quantitative],
}


def domains_for(section: str | None, domain: str | None) -> list[str]:
    if domain:
        if domain not in TEMPLATES:
            raise SystemExit(f"No templates for domain {domain!r}. Available: {', '.join(TEMPLATES)}")
        return [domain]
    if section:
        pool = sg.DOMAINS.get(section, [])
        return [d for d in pool if d in TEMPLATES]
    return list(TEMPLATES.keys())


def generate_templated(count: int, section: str | None = None, domain: str | None = None,
                        progress=None) -> sg.GenerationReport:
    say = progress or (lambda _msg: None)
    domains = domains_for(section, domain)
    if not domains:
        raise SystemExit("No templated domains match that filter.")

    rng = random.Random()
    report = sg.GenerationReport(requested=count)
    seen = sg.existing_prompts()
    accepted: list[dict] = []
    attempts = 0
    max_attempts = count * 40 + 200

    while len(accepted) < count and attempts < max_attempts:
        attempts += 1
        d = rng.choice(domains)
        template = rng.choice(TEMPLATES[d])
        try:
            q = template(rng)
        except Exception as exc:  # a bad random draw in one template shouldn't kill the run
            report.note(f"template error: {exc}", {"prompt": ""})
            continue
        if sg.validate(q, report, seen):
            accepted.append(q)
            if len(accepted) % 200 == 0:
                say(f"{len(accepted)}/{count} generated…")

    report.accepted = accepted
    sg._assign_ids(report.accepted, sg.load_generated())
    for q in report.accepted:
        q["id"] = "tpl-" + q["id"].split("gen-", 1)[-1] if q["id"].startswith("gen-") else q["id"]
    return report


def generate_templated_and_save(**kwargs) -> sg.GenerationReport:
    report = generate_templated(**kwargs)
    if report.accepted:
        sg.save_generated(sg.load_generated() + report.accepted)
    return report


def show_stats() -> int:
    questions = sg.load_generated()
    templated = [q for q in questions if q.get("id", "").startswith("tpl-")]
    print(f"{len(questions)} total generated question(s) in data/generated.json ({len(templated)} from templates).")
    by_domain = Counter(q["domain"] for q in templated)
    for d in TEMPLATES:
        if by_domain[d]:
            print(f"  {d:<30} {by_domain[d]:>5}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-n", "--count", type=int, default=1000, help="how many to generate (default 1000)")
    parser.add_argument("--section", choices=["math", "rw"], help="restrict to one section")
    parser.add_argument("--domain", help=f"restrict to one domain: {', '.join(TEMPLATES)}")
    parser.add_argument("--stats", action="store_true", help="summarize templated questions in the bank and exit")
    args = parser.parse_args()

    if args.stats:
        return show_stats()
    if args.count < 1:
        parser.error("--count must be at least 1")

    def progress(msg: str) -> None:
        print(f"  · {msg}", flush=True)

    print(f"Generating {args.count} templated question(s)…")
    report = generate_templated_and_save(count=args.count, section=args.section, domain=args.domain, progress=progress)
    print(f"\nAccepted {len(report.accepted)} of {report.requested} requested.")
    if report.rejected:
        reasons = Counter(r["reason"].split(":")[0] for r in report.rejected)
        print(f"Skipped {len(report.rejected)} (mostly duplicates as the pool fills up):")
        for reason, n in reasons.most_common(5):
            print(f"  {reason}: {n}")
    if report.accepted:
        print(f"\nWrote to data/generated.json. Reload the app to pick them up.")
    return 0 if report.accepted else 1


if __name__ == "__main__":
    sys.exit(main())
