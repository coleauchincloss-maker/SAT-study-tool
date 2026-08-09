"""A persistent, cross-player leaderboard.

Unlike match state (in-memory, gone on restart), this lives in
data/leaderboard.json so rankings survive a redeploy. There is no login, so
every field here is exactly as trustworthy as whoever's browser sent it —
same trust model as bring-your-own questions. Treat it as a fun scoreboard,
not a verified one.

Each browser gets a random id (see rivals.js:myPlayerId) and "submits" its
own current stats, which upserts its one row. There's no way to impersonate
someone else's row without their id, but nothing stops a browser from lying
about its own stats.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

ROOT = Path(os.path.dirname(os.path.abspath(__file__)))
PATH = ROOT / "data" / "leaderboard.json"

MAX_NAME_LEN = 24
MAX_LOCATION_LEN = 40
MAX_PLAYERS = 20_000  # generous cap so this can't grow without bound

_lock = threading.Lock()

# ─────────────────────────── seed accounts ───────────────────────────
# An empty leaderboard is a worse first impression than a populated one, so
# these fictional accounts fill it in until real players do. None of these
# names refer to an actual person — they're generic handles in the same
# style the app's old "demo" leaderboard used. Every field is marked
# "bot": True in the API response so a client could label them if it wants
# to; nothing here claims to be a real submitted score.
BOT_SEED = [
    {"name": "Maya R.", "location": "London", "xp": 5820, "level": 15, "accuracy": 0.96, "totalAnswered": 940, "wins": 41, "bestCombo": 34, "badgeCount": 22},
    {"name": "TheoPark", "location": "", "xp": 5340, "level": 14, "accuracy": 0.94, "totalAnswered": 860, "wins": 37, "bestCombo": 29, "badgeCount": 20},
    {"name": "calc_wizard", "location": "New York", "xp": 4980, "level": 13, "accuracy": 0.93, "totalAnswered": 810, "wins": 34, "bestCombo": 27, "badgeCount": 19},
    {"name": "Zara T.", "location": "", "xp": 4510, "level": 12, "accuracy": 0.91, "totalAnswered": 730, "wins": 30, "bestCombo": 25, "badgeCount": 18},
    {"name": "NoahBuilds", "location": "Toronto", "xp": 4120, "level": 12, "accuracy": 0.90, "totalAnswered": 690, "wins": 28, "bestCombo": 23, "badgeCount": 17},
    {"name": "priya_k", "location": "", "xp": 3780, "level": 11, "accuracy": 0.89, "totalAnswered": 640, "wins": 26, "bestCombo": 21, "badgeCount": 16},
    {"name": "jwrites", "location": "Sydney", "xp": 3410, "level": 10, "accuracy": 0.87, "totalAnswered": 590, "wins": 23, "bestCombo": 19, "badgeCount": 14},
    {"name": "sam_b", "location": "", "xp": 3050, "level": 10, "accuracy": 0.85, "totalAnswered": 540, "wins": 21, "bestCombo": 18, "badgeCount": 13},
    {"name": "QuietStorm", "location": "London", "xp": 2760, "level": 9, "accuracy": 0.84, "totalAnswered": 490, "wins": 19, "bestCombo": 16, "badgeCount": 12},
    {"name": "ellaquick", "location": "Los Angeles", "xp": 2490, "level": 9, "accuracy": 0.83, "totalAnswered": 450, "wins": 17, "bestCombo": 15, "badgeCount": 11},
    {"name": "Marcus_V", "location": "", "xp": 2210, "level": 8, "accuracy": 0.82, "totalAnswered": 410, "wins": 16, "bestCombo": 14, "badgeCount": 11},
    {"name": "tessa.codes", "location": "", "xp": 1940, "level": 7, "accuracy": 0.80, "totalAnswered": 370, "wins": 14, "bestCombo": 12, "badgeCount": 10},
    {"name": "ben_underline", "location": "Chicago", "xp": 1680, "level": 7, "accuracy": 0.79, "totalAnswered": 330, "wins": 12, "bestCombo": 11, "badgeCount": 9},
    {"name": "RiverSong", "location": "", "xp": 1420, "level": 6, "accuracy": 0.78, "totalAnswered": 290, "wins": 10, "bestCombo": 10, "badgeCount": 8},
    {"name": "dyl_ok", "location": "", "xp": 1180, "level": 6, "accuracy": 0.76, "totalAnswered": 250, "wins": 9, "bestCombo": 9, "badgeCount": 7},
    {"name": "noor_writes", "location": "London", "xp": 970, "level": 5, "accuracy": 0.75, "totalAnswered": 210, "wins": 7, "bestCombo": 8, "badgeCount": 6},
    {"name": "petewrong", "location": "", "xp": 760, "level": 4, "accuracy": 0.73, "totalAnswered": 170, "wins": 6, "bestCombo": 7, "badgeCount": 5},
    {"name": "AvaMarie", "location": "New York", "xp": 590, "level": 4, "accuracy": 0.71, "totalAnswered": 140, "wins": 5, "bestCombo": 6, "badgeCount": 4},
    {"name": "kjay99", "location": "", "xp": 410, "level": 3, "accuracy": 0.70, "totalAnswered": 100, "wins": 3, "bestCombo": 5, "badgeCount": 3},
    {"name": "first_try_liam", "location": "", "xp": 240, "level": 2, "accuracy": 0.68, "totalAnswered": 60, "wins": 2, "bestCombo": 4, "badgeCount": 2},
]


def _bot_rows() -> list[dict]:
    return [
        {
            "id": f"bot-{i}",
            "bot": True,
            "updatedAt": 0,
            **seed,
        }
        for i, seed in enumerate(BOT_SEED)
    ]


class LeaderboardError(ValueError):
    pass


def _clean_str(value, max_len: int, fallback: str = "") -> str:
    if not isinstance(value, str):
        return fallback
    return value.strip()[:max_len]


def _clean_number(value, lo: float = 0, hi: float = 10_000_000) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return 0.0
    if n != n or n in (float("inf"), float("-inf")):  # NaN / inf
        return 0.0
    return max(lo, min(hi, n))


def _load() -> dict:
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "players": {}}
    if not isinstance(data, dict) or not isinstance(data.get("players"), dict):
        return {"version": 1, "players": {}}
    return data


def _save(data: dict) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def submit(player_id: str, payload: dict) -> dict:
    """Upsert one player's row. Returns the stored row."""
    player_id = _clean_str(player_id, 64)
    if not player_id:
        raise LeaderboardError("missing playerId")

    row = {
        "id": player_id,
        "name": _clean_str(payload.get("name"), MAX_NAME_LEN, "Anonymous") or "Anonymous",
        "location": _clean_str(payload.get("location"), MAX_LOCATION_LEN),
        "xp": int(_clean_number(payload.get("xp"))),
        "level": int(_clean_number(payload.get("level"), 1, 500)),
        "accuracy": _clean_number(payload.get("accuracy"), 0, 1),
        "totalAnswered": int(_clean_number(payload.get("totalAnswered"))),
        "wins": int(_clean_number(payload.get("wins"))),
        "bestCombo": int(_clean_number(payload.get("bestCombo"))),
        "badgeCount": int(_clean_number(payload.get("badgeCount"), 0, 1000)),
        "updatedAt": time.time(),
    }

    with _lock:
        data = _load()
        players = data["players"]
        if player_id not in players and len(players) >= MAX_PLAYERS:
            # Cap reached: drop the stalest row to make room rather than growing forever.
            stalest = min(players, key=lambda k: players[k].get("updatedAt", 0))
            del players[stalest]
        players[player_id] = row
        _save(data)
    return row


def _rank_key(row: dict):
    return (-row.get("xp", 0), -row.get("wins", 0), row.get("name", ""))


def rankings(location: str | None = None, limit: int = 100) -> list[dict]:
    with _lock:
        players = list(_load()["players"].values())
    players = [{"bot": False, **p} for p in players] + _bot_rows()

    if location:
        needle = location.strip().lower()
        players = [p for p in players if p.get("location", "").strip().lower() == needle]

    players.sort(key=_rank_key)
    ranked = []
    for i, row in enumerate(players[: max(1, min(limit, 500))]):
        ranked.append({**row, "rank": i + 1})
    return ranked


def locations() -> list[dict]:
    """Distinct locations in use, most-populated first — powers a picker."""
    with _lock:
        players = list(_load()["players"].values())
    players = players + _bot_rows()
    counts: dict[str, int] = {}
    for p in players:
        loc = p.get("location", "").strip()
        if loc:
            counts[loc] = counts.get(loc, 0) + 1
    return [{"location": loc, "count": n} for loc, n in sorted(counts.items(), key=lambda kv: -kv[1])]
