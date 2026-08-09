"""Authoritative 1v1 match engine for SAT Quest.

The server owns the truth: which question is live, when time runs out, who buzzed
first, and which answer is correct. Clients render state and send intents. That
means a player can't win by editing JavaScript, and both screens agree on the
clock even if one machine is slow.

Transport is plain HTTP: POST for intents, Server-Sent Events for state. No
WebSockets, so the exact same process works behind any host that can serve HTTP —
your laptop for LAN play, or a deployed container for online play.

Four formats, all built on one round loop:
  buzzer  Same question for both. First correct takes the point; a wrong answer
          locks you out while your opponent answers freely.
  steal   The question belongs to one player. Miss it and the other player gets a
          short window to steal.
  draft   Players draft SAT domains, then fight for them. Two correct answers in
          a domain claims it; most domains wins.
  wager   Both see the domain and difficulty, secretly bet points, then race.
          Correct wins your bet, wrong loses it.
"""

from __future__ import annotations

import json
import os
import random
import secrets
import threading
import time
from dataclasses import dataclass, field

import satquest_gen as gen

# Codes people read aloud, so no characters that sound or look alike.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 4

ROOM_IDLE_SECONDS = 60 * 60  # reap abandoned rooms after an hour


def _tunable(name: str, default: float) -> float:
    """Pacing knob, overridable by env so tests can run without real waits."""
    try:
        return float(os.environ.get(f"SATQUEST_{name}", default))
    except ValueError:
        return default


REVEAL_SECONDS = _tunable("REVEAL_SECONDS", 4.0)
COUNTDOWN_SECONDS = _tunable("COUNTDOWN_SECONDS", 3.0)
MAX_ROUNDS = int(_tunable("MAX_ROUNDS", 14))

MODES = {
    "buzzer": {
        "id": "buzzer",
        "label": "Buzzer Race",
        "blurb": "Same question. First correct answer takes the point; a wrong answer locks you out.",
        "questionSeconds": _tunable("QUESTION_SECONDS", 30.0),
        "target": 5,
    },
    "steal": {
        "id": "steal",
        "label": "Steal",
        "blurb": "Your question first. Miss it and your opponent can steal the point.",
        "questionSeconds": _tunable("QUESTION_SECONDS", 25.0),
        "stealSeconds": _tunable("STEAL_SECONDS", 12.0),
        "target": 5,
    },
    "draft": {
        "id": "draft",
        "label": "Category Draft",
        "blurb": "Draft SAT domains, then fight for them. Two answers claims a domain.",
        "questionSeconds": _tunable("QUESTION_SECONDS", 30.0),
        "pickSeconds": _tunable("PICK_SECONDS", 20.0),
        "flagsToClaim": 2,
    },
    "wager": {
        "id": "wager",
        "label": "Wager Rounds",
        "blurb": "See the domain, bet your points, then race. Win your bet or lose it.",
        "questionSeconds": _tunable("QUESTION_SECONDS", 30.0),
        "wagerSeconds": _tunable("WAGER_SECONDS", 15.0),
        "maxWager": 3,
        "target": 8,
    },
}

SECTION_LABELS = {"math": "Math", "rw": "Reading & Writing", None: "Both sections"}


class MatchError(Exception):
    """A bad intent from a client — surfaced as a 4xx, not a crash."""


def now() -> float:
    return time.time()


# ─────────────────────────────── question pool ───────────────────────────────

class QuestionPool:
    """A bank, reloaded from disk when it changes so generation/import takes effect."""

    def __init__(self, loader=None) -> None:
        self._loader = loader or gen.load_all
        self._questions: list[dict] = []
        self._loaded_at = 0.0
        self._lock = threading.Lock()

    def all(self) -> list[dict]:
        with self._lock:
            if now() - self._loaded_at > 5.0:
                loaded = [q for q in self._loader() if self._usable(q)]
                self._questions = loaded  # unlike the shared bank, an empty custom set is valid
                self._loaded_at = now()
            return self._questions

    @staticmethod
    def _usable(question: dict) -> bool:
        return (
            isinstance(question.get("id"), str)
            and isinstance(question.get("prompt"), str)
            and isinstance(question.get("choices"), list)
            and len(question["choices"]) == 4
            and isinstance(question.get("answer"), int)
            and 0 <= question["answer"] <= 3
            and question.get("section") in ("math", "rw")
        )

    def counts(self) -> dict:
        questions = self.all()
        return {
            "total": len(questions),
            "math": sum(1 for q in questions if q["section"] == "math"),
            "rw": sum(1 for q in questions if q["section"] == "rw"),
        }


POOL = QuestionPool(gen.load_all)
IMPORTED_POOL = QuestionPool(gen.load_imported)


def pool_for(source: str) -> QuestionPool:
    return IMPORTED_POOL if source == "imported" else POOL


# ─────────────────────────────── model ───────────────────────────────

@dataclass
class Player:
    pid: str
    name: str
    score: int = 0
    correct: int = 0
    answered: int = 0
    fastest_ms: int | None = None
    ready: bool = False
    connected: bool = True
    # Bumped each time this player opens a state stream. A stream that closes only
    # marks the player away if it is still the current one — otherwise an
    # EventSource reconnect would have its teardown clobber the new connection.
    conn_epoch: int = 0
    streak: int = 0
    best_streak: int = 0
    wager: int | None = None
    domains: list[str] = field(default_factory=list)   # draft: drafted domains
    claims: list[str] = field(default_factory=list)    # draft: claimed domains

    def public(self) -> dict:
        return {
            "id": self.pid,
            "name": self.name,
            "score": self.score,
            "correct": self.correct,
            "answered": self.answered,
            "fastestMs": self.fastest_ms,
            "ready": self.ready,
            "connected": self.connected,
            "streak": self.streak,
            "bestStreak": self.best_streak,
            "domains": self.domains,
            "claims": self.claims,
        }


@dataclass
class Room:
    code: str
    mode: str
    section: str | None
    host_pid: str
    players: dict[str, Player] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)  # stable seating order

    phase: str = "lobby"  # lobby|countdown|draft|wager|question|steal|reveal|over
    target_override: int | None = None
    question_seconds_override: float | None = None  # None = mode default; -1 = unlimited; >0 = custom
    question_source: str = "all"  # "all" (built-in + generated) | "imported" (bring-your-own)
    focus_mode: bool = False
    distractions: dict[str, int] = field(default_factory=dict)  # pid -> tab-switch/fullscreen-exit count
    seq: int = 0
    round_no: int = 0
    deadline: float | None = None
    created_at: float = field(default_factory=now)
    touched_at: float = field(default_factory=now)

    question: dict | None = None
    asked_ids: set[str] = field(default_factory=set)
    answers: dict[str, dict] = field(default_factory=dict)  # pid -> {choice, at, correct}
    locked: set[str] = field(default_factory=set)
    question_started_at: float = 0.0

    turn_pid: str | None = None          # steal / draft pick order
    outcome: dict | None = None          # what the reveal screen explains
    winner_pid: str | None = None
    flags: dict[str, dict[str, int]] = field(default_factory=dict)  # draft: domain -> pid -> flags
    draft_pool: list[str] = field(default_factory=list)
    log: list[dict] = field(default_factory=list)

    @property
    def spec(self) -> dict:
        return MODES[self.mode]

    @property
    def question_seconds(self) -> float | None:
        """Effective per-question time limit: None means no clock at all."""
        override = self.question_seconds_override
        if override is None:
            return self.spec["questionSeconds"]
        return None if override < 0 else override

    def opponent_of(self, pid: str) -> Player | None:
        for other in self.order:
            if other != pid:
                return self.players.get(other)
        return None


# ─────────────────────────────── engine ───────────────────────────────

class MatchServer:
    """Holds every live room. All mutation happens under `self.lock`."""

    def __init__(self) -> None:
        self.rooms: dict[str, Room] = {}
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self._ticker = threading.Thread(target=self._tick_forever, daemon=True)
        self._ticker.start()

    # ── lifecycle ──
    def _new_code(self) -> str:
        for _ in range(500):
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            if code not in self.rooms:
                return code
        raise MatchError("no room codes available; try again")

    def create(
        self,
        name: str,
        mode: str,
        section: str | None,
        target: int | None = None,
        question_seconds: float | None = None,
        focus_mode: bool = False,
        source: str = "all",
    ) -> tuple[Room, Player]:
        if mode not in MODES:
            raise MatchError(f"unknown mode {mode!r}")
        if section not in (None, "math", "rw"):
            raise MatchError(f"unknown section {section!r}")
        if source not in ("all", "imported"):
            raise MatchError(f"unknown question source {source!r}")

        available = pool_for(source).counts()
        needed = 6
        have = available["total"] if section is None else available[section]
        if have < needed:
            hint = (
                "Import more from the Duel page's question importer."
                if source == "imported"
                else "Generate more with generate.py."
            )
            raise MatchError(
                f"only {have} question(s) available for {SECTION_LABELS[section]} "
                f"{'(imported set)' if source == 'imported' else ''} — need at least {needed}. {hint}"
            )

        with self.lock:
            self._reap()
            player = Player(pid=secrets.token_urlsafe(9), name=_clean_name(name))
            room = Room(code=self._new_code(), mode=mode, section=section, host_pid=player.pid)
            if target:
                room.target_override = max(1, min(int(target), 20))
            if question_seconds is not None:
                try:
                    qs = float(question_seconds)
                except (TypeError, ValueError):
                    qs = None
                if qs is not None:
                    room.question_seconds_override = -1.0 if qs <= 0 else max(10.0, min(qs, 180.0))
            room.focus_mode = bool(focus_mode)
            room.question_source = source
            room.players[player.pid] = player
            room.order.append(player.pid)
            self.rooms[room.code] = room
            self._bump(room)
            return room, player

    def join(self, code: str, name: str) -> tuple[Room, Player]:
        with self.lock:
            room = self._room(code)
            if len(room.players) >= 2:
                # Rejoining your own seat after a refresh is handled by playerId;
                # a third person is simply turned away.
                raise MatchError("that match already has two players")
            if room.phase not in ("lobby", "over"):
                raise MatchError("that match is already in progress")

            player = Player(pid=secrets.token_urlsafe(9), name=_clean_name(name))
            room.players[player.pid] = player
            room.order.append(player.pid)
            room.phase = "lobby"
            for existing in room.players.values():
                existing.ready = False
            self._bump(room)
            return room, player

    def _room(self, code: str) -> Room:
        room = self.rooms.get((code or "").strip().upper())
        if not room:
            raise MatchError("no match with that code")
        return room

    def _reap(self) -> None:
        stale = [code for code, room in self.rooms.items() if now() - room.touched_at > ROOM_IDLE_SECONDS]
        for code in stale:
            del self.rooms[code]

    def _bump(self, room: Room) -> None:
        room.seq += 1
        room.touched_at = now()
        self.changed.notify_all()

    # ── intents ──
    def action(self, code: str, pid: str, kind: str, payload: dict) -> None:
        with self.lock:
            room = self._room(code)
            player = room.players.get(pid)
            if not player:
                raise MatchError("you are not in this match")

            handler = {
                "ready": self._on_ready,
                "answer": self._on_answer,
                "wager": self._on_wager,
                "pick": self._on_pick,
                "rematch": self._on_rematch,
                "leave": self._on_leave,
                "skip": self._on_skip,
                "distract": self._on_distract,
            }.get(kind)
            if not handler:
                raise MatchError(f"unknown action {kind!r}")

            handler(room, player, payload or {})
            self._bump(room)

    def _on_ready(self, room: Room, player: Player, _payload: dict) -> None:
        if room.phase not in ("lobby", "over"):
            return
        player.ready = True
        if len(room.players) == 2 and all(p.ready for p in room.players.values()):
            self._start_match(room)

    def _on_rematch(self, room: Room, player: Player, _payload: dict) -> None:
        """Run it back. Scores reset in _start_match once both players are ready."""
        if room.phase not in ("over", "lobby"):
            return
        if room.phase == "over":
            room.phase = "lobby"
            room.question = None
            room.outcome = None
            room.deadline = None
            for other in room.players.values():
                other.ready = False
        player.ready = True
        if len(room.players) == 2 and all(p.ready for p in room.players.values()):
            self._start_match(room)

    def _on_leave(self, room: Room, player: Player, _payload: dict) -> None:
        room.players.pop(player.pid, None)
        if player.pid in room.order:
            room.order.remove(player.pid)
        if not room.players:
            self.rooms.pop(room.code, None)
            return
        room.phase = "lobby"
        room.question = None
        room.deadline = None
        for remaining in room.players.values():
            remaining.ready = False

    def _on_skip(self, room: Room, player: Player, _payload: dict) -> None:
        """Host can cut a reveal short so a match doesn't stall on a slow reader."""
        if room.phase == "reveal" and player.pid == room.host_pid:
            room.deadline = now()

    def _on_distract(self, room: Room, player: Player, _payload: dict) -> None:
        """Focus Mode: the client reports it lost visibility or left fullscreen.

        This is detection, not prevention — a browser cannot block tab-switching
        or a second device. It just makes a lapse visible to both players live,
        instead of silently trusting the honor system.
        """
        if not room.focus_mode:
            return
        if room.phase in ("question", "steal", "wager"):
            room.distractions[player.pid] = room.distractions.get(player.pid, 0) + 1

    def _on_answer(self, room: Room, player: Player, payload: dict) -> None:
        if room.phase not in ("question", "steal"):
            raise MatchError("no question is live")
        if player.pid in room.answers:
            return  # already answered; ignore duplicate clicks
        if player.pid in room.locked:
            raise MatchError("you are locked out of this question")
        if room.phase == "steal" and player.pid != room.turn_pid:
            raise MatchError("it is not your steal")
        if room.mode == "steal" and room.phase == "question" and player.pid != room.turn_pid:
            raise MatchError("this question belongs to your opponent")

        try:
            choice = int(payload.get("choice"))
        except (TypeError, ValueError):
            raise MatchError("choice must be 0-3") from None
        if not 0 <= choice <= 3:
            raise MatchError("choice must be 0-3")

        elapsed_ms = int((now() - room.question_started_at) * 1000)
        correct = choice == room.question["answer"]
        room.answers[player.pid] = {"choice": choice, "atMs": elapsed_ms, "correct": correct}
        player.answered += 1
        if correct:
            player.correct += 1
            player.fastest_ms = elapsed_ms if player.fastest_ms is None else min(player.fastest_ms, elapsed_ms)
        else:
            room.locked.add(player.pid)

        self._maybe_resolve(room)

    def _on_wager(self, room: Room, player: Player, payload: dict) -> None:
        if room.phase != "wager":
            raise MatchError("not a wagering phase")
        try:
            amount = int(payload.get("amount"))
        except (TypeError, ValueError):
            raise MatchError("amount must be a number") from None
        ceiling = room.spec["maxWager"]
        player.wager = max(1, min(amount, ceiling))
        if all(p.wager is not None for p in room.players.values()):
            self._begin_question(room)

    def _on_pick(self, room: Room, player: Player, payload: dict) -> None:
        if room.phase != "draft":
            raise MatchError("not a drafting phase")
        if player.pid != room.turn_pid:
            raise MatchError("it is not your pick")
        domain = payload.get("domain")
        if domain not in room.draft_pool:
            raise MatchError("that domain is not available")
        room.draft_pool.remove(domain)
        player.domains.append(domain)
        room.flags[domain] = {pid: 0 for pid in room.order}
        self._advance_draft(room)

    # ── match flow ──
    def _start_match(self, room: Room) -> None:
        for player in room.players.values():
            player.score = 0
            player.correct = 0
            player.answered = 0
            player.streak = 0
            player.best_streak = 0
            player.fastest_ms = None
            player.wager = None
            player.domains = []
            player.claims = []
        room.round_no = 0
        room.asked_ids = set()
        room.log = []
        room.winner_pid = None
        room.outcome = None
        room.flags = {}
        room.turn_pid = room.order[0]

        if room.mode == "draft":
            room.draft_pool = self._domain_pool(room)
            room.phase = "draft"
            room.deadline = now() + room.spec["pickSeconds"]
        else:
            room.phase = "countdown"
            room.deadline = now() + COUNTDOWN_SECONDS

    def _domain_pool(self, room: Room) -> list[str]:
        questions = self._eligible(room, ignore_asked=True)
        by_domain: dict[str, int] = {}
        for question in questions:
            by_domain[question["domain"]] = by_domain.get(question["domain"], 0) + 1
        # Only offer domains with enough questions to actually fight over.
        pool = [d for d, count in by_domain.items() if count >= 3]
        random.shuffle(pool)
        return pool[:6]

    def _advance_draft(self, room: Room) -> None:
        picks = sum(len(p.domains) for p in room.players.values())
        capacity = min(4, picks + len(room.draft_pool))
        if picks >= capacity or not room.draft_pool:
            room.phase = "countdown"
            room.deadline = now() + COUNTDOWN_SECONDS
            room.turn_pid = room.order[0]
            return
        # Snake order so the second picker isn't permanently behind.
        room.turn_pid = room.order[1] if picks % 4 in (1, 2) else room.order[0]
        room.deadline = now() + room.spec["pickSeconds"]

    def _eligible(self, room: Room, ignore_asked: bool = False) -> list[dict]:
        questions = pool_for(room.question_source).all()
        if room.section:
            questions = [q for q in questions if q["section"] == room.section]
        if room.mode == "draft":
            claimed = {d for d in room.flags}
            if claimed:
                questions = [q for q in questions if q["domain"] in claimed]
        if not ignore_asked:
            fresh = [q for q in questions if q["id"] not in room.asked_ids]
            if fresh:
                return fresh
            room.asked_ids = set()  # bank exhausted: allow repeats rather than stall
        return questions

    def _next_question(self, room: Room) -> dict | None:
        pool = self._eligible(room)
        if not pool:
            return None

        if room.mode == "draft":
            open_domains = [d for d, f in room.flags.items() if not self._claimant(room, d)]
            if open_domains:
                target = min(open_domains, key=lambda d: sum(room.flags[d].values()))
                scoped = [q for q in pool if q["domain"] == target]
                if scoped:
                    pool = scoped

        # Ramp difficulty a little as the match goes on.
        wanted = 1 if room.round_no < 2 else (2 if room.round_no < 6 else 3)
        preferred = [q for q in pool if q["difficulty"] == wanted]
        return random.choice(preferred or pool)

    def _begin_question(self, room: Room) -> None:
        question = self._next_question(room)
        if question is None:
            self._finish(room, reason="out of questions")
            return

        room.round_no += 1
        room.question = question
        room.asked_ids.add(question["id"])
        room.answers = {}
        room.locked = set()
        room.outcome = None
        room.phase = "question"
        room.question_started_at = now()
        qs = room.question_seconds
        room.deadline = (now() + qs) if qs is not None else None

        if room.mode == "steal":
            # Alternate who owns the question.
            room.turn_pid = room.order[(room.round_no - 1) % len(room.order)]

    def _begin_round(self, room: Room) -> None:
        """Start whatever comes before the question for this mode."""
        if room.mode == "wager":
            for player in room.players.values():
                player.wager = None
            room.phase = "wager"
            room.question = self._next_question(room)
            if room.question is None:
                self._finish(room, reason="out of questions")
                return
            # The question is chosen now so the wager screen can show its domain,
            # but it is not sent to clients until the question phase begins.
            room.deadline = now() + room.spec["wagerSeconds"]
        else:
            self._begin_question(room)

    def _maybe_resolve(self, room: Room) -> None:
        """Resolve the round early when nothing more can happen."""
        if room.phase not in ("question", "steal"):
            return

        if room.mode == "steal":
            owner = room.players.get(room.turn_pid)
            answer = room.answers.get(room.turn_pid)
            if answer and answer["correct"]:
                self._score_round(room)
            elif answer and room.phase == "question":
                opponent = room.opponent_of(room.turn_pid) if owner else None
                if opponent:
                    room.phase = "steal"
                    room.turn_pid = opponent.pid
                    room.question_started_at = now()
                    room.deadline = now() + room.spec["stealSeconds"]
                else:
                    self._score_round(room)
            elif answer:
                self._score_round(room)
            return

        # buzzer / draft / wager: first correct ends it, as does everyone locked out
        if any(a["correct"] for a in room.answers.values()):
            self._score_round(room)
        elif len(room.locked) >= len(room.players):
            self._score_round(room)

    def _winner_of_round(self, room: Room) -> str | None:
        scorers = [(pid, a["atMs"]) for pid, a in room.answers.items() if a["correct"]]
        if not scorers:
            return None
        scorers.sort(key=lambda pair: pair[1])
        return scorers[0][0]

    def _score_round(self, room: Room) -> None:
        winner_pid = self._winner_of_round(room)
        detail: dict = {"winnerPid": winner_pid, "mode": room.mode}

        for pid, player in room.players.items():
            answered = room.answers.get(pid)
            if answered and answered["correct"]:
                player.streak += 1
                player.best_streak = max(player.best_streak, player.streak)
            else:
                player.streak = 0

        if room.mode == "wager":
            for pid, player in room.players.items():
                stake = player.wager or 1
                answered = room.answers.get(pid)
                if pid == winner_pid:
                    player.score += stake
                    detail.setdefault("deltas", {})[pid] = stake
                elif answered and not answered["correct"]:
                    player.score = max(0, player.score - stake)
                    detail.setdefault("deltas", {})[pid] = -stake
                else:
                    detail.setdefault("deltas", {})[pid] = 0
        elif room.mode == "draft":
            domain = room.question["domain"]
            if winner_pid and domain in room.flags:
                room.flags[domain][winner_pid] = room.flags[domain].get(winner_pid, 0) + 1
                detail["domain"] = domain
                claimant = self._claimant(room, domain)
                if claimant:
                    player = room.players[claimant]
                    if domain not in player.claims:
                        player.claims.append(domain)
                    detail["claimed"] = domain
            for pid, player in room.players.items():
                player.score = len(player.claims)
        else:
            if winner_pid:
                room.players[winner_pid].score += 1
                detail.setdefault("deltas", {})[winner_pid] = 1

        room.outcome = detail
        room.log.append(
            {
                "round": room.round_no,
                "questionId": room.question["id"],
                "domain": room.question["domain"],
                "skill": room.question["skill"],
                "difficulty": room.question["difficulty"],
                "answer": room.question["answer"],
                "winnerPid": winner_pid,
                "answers": {pid: dict(a) for pid, a in room.answers.items()},
            }
        )

        room.phase = "reveal"
        room.deadline = now() + REVEAL_SECONDS

    def _claimant(self, room: Room, domain: str) -> str | None:
        need = room.spec["flagsToClaim"]
        for pid, flags in room.flags.get(domain, {}).items():
            if flags >= need:
                return pid
        return None

    def _match_over(self, room: Room) -> bool:
        if room.mode == "draft":
            return all(self._claimant(room, d) for d in room.flags) if room.flags else True
        target = room.target_override or room.spec["target"]
        if any(p.score >= target for p in room.players.values()):
            return True
        return room.round_no >= MAX_ROUNDS

    def _finish(self, room: Room, reason: str = "complete") -> None:
        room.phase = "over"
        room.deadline = None
        room.question = None
        ranked = sorted(room.players.values(), key=lambda p: (-p.score, -p.correct, p.fastest_ms or 10**9))
        if len(ranked) >= 2 and ranked[0].score == ranked[1].score and ranked[0].correct == ranked[1].correct:
            room.winner_pid = None  # a genuine draw
        else:
            room.winner_pid = ranked[0].pid if ranked else None
        room.outcome = {"reason": reason}
        for player in room.players.values():
            player.ready = False

    # ── clock ──
    def _tick_forever(self) -> None:
        while True:
            time.sleep(0.1)
            try:
                self._tick()
            except Exception:  # a tick must never kill the thread
                pass

    def _tick(self) -> None:
        with self.lock:
            for room in list(self.rooms.values()):
                if room.deadline is None or now() < room.deadline:
                    continue
                self._on_deadline(room)
                self._bump(room)
            self._reap()

    def _on_deadline(self, room: Room) -> None:
        if room.phase == "countdown":
            self._begin_round(room)
        elif room.phase == "draft":
            # Auto-pick for a player who let the clock run out.
            if room.draft_pool and room.turn_pid:
                domain = room.draft_pool.pop(0)
                room.players[room.turn_pid].domains.append(domain)
                room.flags[domain] = {pid: 0 for pid in room.order}
            self._advance_draft(room)
        elif room.phase == "wager":
            for player in room.players.values():
                if player.wager is None:
                    player.wager = 1
            self._begin_question(room)
        elif room.phase == "question":
            if room.mode == "steal" and room.turn_pid not in room.answers:
                opponent = room.opponent_of(room.turn_pid)
                room.locked.add(room.turn_pid)
                if opponent and opponent.pid not in room.answers:
                    room.phase = "steal"
                    room.turn_pid = opponent.pid
                    room.question_started_at = now()
                    room.deadline = now() + room.spec["stealSeconds"]
                    return
            self._score_round(room)
        elif room.phase == "steal":
            self._score_round(room)
        elif room.phase == "reveal":
            if self._match_over(room):
                self._finish(room)
            else:
                room.phase = "countdown"
                room.deadline = now() + 1.2
        else:
            room.deadline = None

    # ── snapshots ──
    def snapshot(self, code: str, pid: str | None) -> dict:
        with self.lock:
            room = self._room(code)
            return self._snapshot(room, pid)

    def _snapshot(self, room: Room, pid: str | None) -> dict:
        revealing = room.phase in ("reveal", "over")
        question = None
        if room.question and room.phase in ("question", "steal", "reveal"):
            question = {
                "id": room.question["id"],
                "section": room.question["section"],
                "domain": room.question["domain"],
                "skill": room.question["skill"],
                "difficulty": room.question["difficulty"],
                "prompt": room.question["prompt"],
                "choices": room.question["choices"],
                "passage": room.question.get("passage", ""),
                "notes": room.question.get("notes", []),
                "table": room.question.get("table") or {"headers": [], "rows": []},
            }
            if revealing:
                question["answer"] = room.question["answer"]
                question["explanation"] = room.question.get("explanation", "")
        elif room.question and room.phase == "wager":
            # Wagering happens knowing only the shape of what's coming.
            question = {
                "domain": room.question["domain"],
                "difficulty": room.question["difficulty"],
                "section": room.question["section"],
                "teaser": True,
            }

        players = []
        for other_pid in room.order:
            player = room.players.get(other_pid)
            if not player:
                continue
            view = player.public()
            answered = room.answers.get(other_pid)
            view["hasAnswered"] = answered is not None
            view["lockedOut"] = other_pid in room.locked
            # A wager and a choice stay secret until the reveal.
            view["wager"] = player.wager if (revealing or other_pid == pid) else (None if player.wager is None else 0)
            view["wagerLocked"] = player.wager is not None
            if answered and (revealing or other_pid == pid):
                view["choice"] = answered["choice"]
                # Deliberately not "correct": that key is the player's running
                # count of correct answers, and overwriting it with this round's
                # boolean made the final screen report "true correct for you".
                view["answerCorrect"] = answered["correct"]
                view["atMs"] = answered["atMs"]
            players.append(view)

        return {
            "code": room.code,
            "seq": room.seq,
            "mode": room.mode,
            "modeLabel": room.spec["label"],
            "section": room.section,
            "sectionLabel": SECTION_LABELS[room.section],
            "phase": room.phase,
            "round": room.round_no,
            "maxRounds": MAX_ROUNDS,
            "target": room.target_override or room.spec.get("target"),
            "questionSeconds": room.question_seconds,
            "focusMode": room.focus_mode,
            "distractions": dict(room.distractions),
            "deadline": room.deadline,
            "serverTime": now(),
            "you": pid,
            "hostPid": room.host_pid,
            "turnPid": room.turn_pid,
            "players": players,
            "question": question,
            "outcome": room.outcome,
            "winnerPid": room.winner_pid,
            "draftPool": room.draft_pool if room.mode == "draft" else [],
            "flags": room.flags if room.mode == "draft" else {},
            "flagsToClaim": room.spec.get("flagsToClaim"),
            "maxWager": room.spec.get("maxWager"),
            "log": room.log if room.phase == "over" else [],
        }

    def wait_for_change(self, code: str, pid: str | None, since: int, timeout: float = 20.0) -> dict | None:
        """Block until the room's state moves past `since`, then return it."""
        deadline = now() + timeout
        with self.lock:
            room = self._room(code)
            while room.seq <= since:
                remaining = deadline - now()
                if remaining <= 0:
                    return None
                self.changed.wait(min(remaining, 0.5))
                room = self.rooms.get(code)
                if room is None:
                    raise MatchError("the match ended")
            return self._snapshot(room, pid)

    def open_stream(self, code: str, pid: str) -> int:
        """Mark a player present. Returns the epoch to pass back to close_stream."""
        with self.lock:
            room = self.rooms.get(code)
            player = room.players.get(pid) if room else None
            if not player:
                return 0
            player.conn_epoch += 1
            if not player.connected:
                player.connected = True
                self._bump(room)
            return player.conn_epoch

    def close_stream(self, code: str, pid: str, epoch: int) -> None:
        """Mark a player away, unless they have already opened a newer stream."""
        with self.lock:
            room = self.rooms.get(code)
            player = room.players.get(pid) if room else None
            if not player or player.conn_epoch != epoch:
                return
            if player.connected:
                player.connected = False
                self._bump(room)

    def lobby_info(self) -> dict:
        with self.lock:
            return {
                "modes": MODES,
                "rooms": len(self.rooms),
                "pool": POOL.counts(),
                "importedPool": IMPORTED_POOL.counts(),
            }


def _clean_name(name: str) -> str:
    cleaned = (name or "").strip()[:16]
    return cleaned or f"Player{random.randint(10, 99)}"


SERVER = MatchServer()
