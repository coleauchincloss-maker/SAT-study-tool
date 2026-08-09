# SAT Quest

A 1v1 SAT game. You and a friend get the same question at the same time and race
for it. There's a room code, a scoreboard, a clock, and a running record of how
you've done against each other.

```bash
python3 server.py --lan --open
```

Your opponent opens the `On your Wi-Fi` address the server prints. You pick a
format, hit **Open a room**, and read them the four-character code.

## Three ways to play someone

| | How it works | Needs |
| --- | --- | --- |
| **Same Wi-Fi** | You run the server, they open your LAN address, you duel live. | `--lan` |
| **Online** | The same server, deployed. Both of you open the deployed URL. | See [DEPLOY.md](DEPLOY.md) |
| **Challenge code** | You play eight questions, send a code, they race your recorded run. | Nothing |

Challenge codes are the fallback for when you're not online together. The code
contains the question list and your score, so their app serves the identical
questions and shows the head-to-head when they finish.

## The four formats

| Format | The idea |
| --- | --- |
| **Buzzer Race** | Same question on both screens. First correct answer takes the point; a wrong answer locks you out while they answer freely. First to 5. |
| **Steal** | The question belongs to one of you. Miss it and your opponent gets a short window to steal the point. |
| **Category Draft** | Draft SAT domains, then fight over them. Two correct answers claims a domain; most domains wins. |
| **Wager Rounds** | You see the domain and difficulty, secretly bet 1–3 points, then race. Correct wins your bet; wrong loses it. First to 8. |

Math questions come with a graphing calculator and the formula reference sheet,
both toggleable mid-question.

## Why the server decides everything

The server owns which question is live, when time expires, who buzzed first, and
which answer is correct. Clients render state and send intents. Two consequences
worth knowing:

- Neither player can win by editing JavaScript — the answer key isn't sent to the
  browser until the reveal.
- Both screens agree on the clock even if one machine is slower, because the
  countdown is derived from a server timestamp rather than each client's own.

State arrives over Server-Sent Events, so there's no WebSocket dependency and the
same process runs locally or deployed.

## Fresh questions from Claude

49 original questions ship with the app. That's enough for a few matches before
you start recognizing them, so the app can write more:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python3 generate.py -n 20                      # spread across everything
python3 generate.py -n 10 --section math
python3 generate.py -n 8 --domain "Geometry & Trig"
python3 generate.py --stats                    # what's in the bank
```

With the key set in the shell running `server.py`, the lobby's **Generate**
buttons do the same thing without leaving the browser. The key stays in the server
process — the page never sees it and never calls the API directly.

**Every generated question is checked before it's accepted.** A second, separate
request gets the question *without* its answer key, solves it independently, and
judges whether exactly one choice is defensible. Items where the two disagree are
thrown out, and `generate.py` tells you which and why. This is the only automatic
guard against a question that reads well but has the wrong answer marked.

Generated questions land in `data/generated.json` and merge into the bank on load.
Reload the page to pick them up. New skills appear in tracking automatically.

## Layout

```
index.html            entry point
server.py             static files + match API + generation proxy
match.py              authoritative match engine (rooms, rounds, scoring, clock)
satquest_gen.py       question generation and the answer-key verification pass
generate.py           bulk generation CLI
data/questions.json   the 49 built-in questions
data/generated.json   Claude-generated questions
Dockerfile, fly.toml  for deploying the match server
js/
  main.js             router; the only place persistent state is written
  net.js              match API client and the SSE state stream
  bank.js             merges built-in + generated questions
  rivals.js           head-to-head records and challenge codes
  engine.js           XP, levels, badges, per-skill tracking
  exam.js             parked: two-module adaptive section logic (see below)
  views/
    home.js           lobby: formats, rooms, challenge codes, rivals
    match.js          the live duel screen, all four formats
    quiz.js           solo practice and challenge runs
    results.js        round summary and challenge verdicts
    dashboard.js      your card: accuracy by domain, weak spots, badges
  components/
    calculator.js     graphing calculator (own parser, canvas plotting)
    reference.js      formula reference sheet
    ui.js             shared presentational helpers
```

Both the question bank files are JSON precisely so the Python server and the
browser read the same data — the server can't import a JS module, and it has to
know the answers.

## Progress, and the parked test mode

Playing still builds a profile: XP and levels from correct answers plus a win
bonus, a per-skill accuracy record, and badges. **Your card** in the header shows
accuracy by SAT domain and your weakest skills. It's there so you can see what
keeps costing you points, not as a study destination — the footer has a
`Practice alone` link if you actually want to drill.

`js/exam.js` holds a working two-module adaptive section engine (27/22 questions,
real timing, Module 2 difficulty routed by Module 1 performance). It is **not
wired to any UI** — a full timed practice test is a study tool, not a duel, so it
was left out when the app became a game. The logic is there if you ever want it.

## Notes

- All questions are original items written for this project. Real College Board
  SAT questions are copyrighted and none are reproduced here. Bluebook's
  interface conventions informed the math tools; its content did not.
- Records, XP and skill history live in `localStorage`, per browser. Your seat in
  a match lives in `sessionStorage`, so a refresh rejoins the same match but a
  second tab is a separate player.
- Match rooms are in memory and last for the match. A server restart ends live
  rooms.
- Pacing is tunable with env vars when you want faster or slower rounds:
  `SATQUEST_QUESTION_SECONDS`, `SATQUEST_REVEAL_SECONDS`,
  `SATQUEST_COUNTDOWN_SECONDS`, `SATQUEST_STEAL_SECONDS`,
  `SATQUEST_WAGER_SECONDS`, `SATQUEST_PICK_SECONDS`, `SATQUEST_MAX_ROUNDS`.
- No build step and no runtime dependencies. `anthropic` is needed only for
  generating questions.
