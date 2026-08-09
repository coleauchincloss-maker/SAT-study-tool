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
    counts: dict[str, int] = {}
    for p in players:
        loc = p.get("location", "").strip()
        if loc:
            counts[loc] = counts.get(loc, 0) + 1
    return [{"location": loc, "count": n} for loc, n in sorted(counts.items(), key=lambda kv: -kv[1])]
