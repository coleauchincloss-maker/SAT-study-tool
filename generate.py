#!/usr/bin/env python3
"""Bulk-generate SAT Quest practice questions and append them to the bank.

    export ANTHROPIC_API_KEY=sk-ant-...

    python3 generate.py --count 20                     # spread across everything
    python3 generate.py --count 12 --section math      # one section
    python3 generate.py --count 8 --domain "Geometry & Trig"
    python3 generate.py --count 10 --no-verify         # skip the answer-key check
    python3 generate.py --stats                        # what's in the bank already

Questions land in data/generated.json, which the app merges with the built-in bank
on load. Nothing else needs to change — new skills show up in the dashboard's
weak-spot tracking automatically.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

import satquest_gen as gen


def show_stats() -> int:
    questions = gen.load_generated()
    if not questions:
        print("data/generated.json is empty — the app is running on the 49 built-in questions.")
        return 0

    print(f"{len(questions)} generated question(s) in data/generated.json\n")
    by_domain = Counter(q["domain"] for q in questions)
    for domain in gen.ALL_DOMAINS:
        if by_domain[domain]:
            print(f"  {domain:<28} {by_domain[domain]:>3}")
    difficulty = Counter(q["difficulty"] for q in questions)
    print("\n  difficulty  " + "  ".join(f"{d}:{difficulty[d]}" for d in (1, 2, 3)))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate original SAT practice questions with Claude.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("-n", "--count", type=int, default=10, help="how many to generate (default 10)")
    parser.add_argument("--section", choices=["math", "rw"], help="restrict to one section")
    parser.add_argument("--domain", help=f"restrict to one domain: {', '.join(gen.ALL_DOMAINS)}")
    parser.add_argument("--skill", action="append", dest="skills", help="steer toward a skill (repeatable)")
    parser.add_argument(
        "--effort",
        choices=["low", "medium", "high", "xhigh", "max"],
        default="high",
        help="reasoning effort (default high; 'xhigh' for harder math items)",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="skip the independent answer-key check (faster and cheaper, but unchecked keys)",
    )
    parser.add_argument("--dry-run", action="store_true", help="print results without writing to the bank")
    parser.add_argument("--stats", action="store_true", help="summarize the generated bank and exit")
    args = parser.parse_args()

    if args.stats:
        return show_stats()
    if args.count < 1:
        parser.error("--count must be at least 1")

    def progress(message: str) -> None:
        print(f"  · {message}", flush=True)

    print(f"Generating {args.count} question(s) with {gen.MODEL} (effort={args.effort})…")
    if args.no_verify:
        print("  ! verification disabled — answer keys are unchecked", flush=True)

    try:
        run = gen.generate_and_save if not args.dry_run else gen.generate
        report = run(
            count=args.count,
            section=args.section,
            domain=args.domain,
            skills=args.skills,
            verify=not args.no_verify,
            effort=args.effort,
            progress=progress,
        )
    except gen.GenerationError as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted — nothing written", file=sys.stderr)
        return 130

    print(f"\nAccepted {len(report.accepted)} of {report.requested} requested.")
    for question in report.accepted:
        print(f"  ✓ [{question['difficulty']}] {question['domain']} · {question['skill']}")
        print(f"      {question['prompt'].splitlines()[-1][:96]}")

    if report.rejected:
        print(f"\nDropped {len(report.rejected)}:")
        for item in report.rejected:
            print(f"  ✗ {item['reason']}")
            if item["prompt"]:
                print(f"      {item['prompt']}")

    if args.dry_run:
        print("\n(dry run — data/generated.json unchanged)")
    elif report.accepted:
        print(f"\nWrote to {gen.GENERATED_PATH.relative_to(gen.ROOT)}. Reload the app to pick them up.")

    return 0 if report.accepted else 1


if __name__ == "__main__":
    sys.exit(main())
