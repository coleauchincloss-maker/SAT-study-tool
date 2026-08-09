# Testing SAT Quest with two people

Everything below assumes you're the host — the person whose laptop runs the server.

## Before your opponent arrives

**1. Start the server with `--lan`.** This is the step that has bitten us; without
it the server only listens to your own machine and nobody can join.

```bash
python3 ~/sat-quest/server.py --lan --open
```

It prints something like:

```
SAT Quest → http://localhost:5173/   (Ctrl+C to stop)
On your Wi-Fi  → http://192.168.0.21:5173/   (give this to your opponent)
```

**2. Say yes to the firewall prompt.** macOS asks whether `python3` may accept
incoming connections the first time. If you dismissed it once, it stays dismissed:
System Settings → Network → Firewall → Options → allow `python3`.

**3. Sanity-check the address yourself.** Open the `On your Wi-Fi` URL on your own
phone before your friend gets there. If it loads, the network side works. If it
doesn't, nothing else in this document will help — fix that first (see
Troubleshooting).

## The two-person run

| | You (host) | Them |
|---|---|---|
| 1 | Type your name in the header | Open the Wi-Fi address you sent |
| 2 | Pick a format, press **Open a room** | Type their name |
| 3 | Press **Copy** and text them the invite link | Tap the link (or type the 4-character code and press **Join a room**) |
| 4 | Their name appears in your room within a second | Your name appears in theirs |
| 5 | Press **I'm ready** | Press **I'm ready** |
| 6 | 3… 2… 1… first question on both screens | Same question, same clock |

Answer with the mouse or keys **1–4**. In Wager rounds, **1–3** sets your bet.

## What "working" looks like

Watch for these specifically — they're the things that prove the two machines are
genuinely in sync rather than each running their own copy:

- Their name shows up in your lobby **without you refreshing**.
- The countdown hits zero at the same moment on both screens.
- When one of you answers first, the other's screen updates immediately —
  the loser sees "locked out" or the round resolving, not a frozen question.
- The scoreboard reads the same on both screens after every round.
- At the end, both of you see the same winner and the same round-by-round table.
- Your rivalry record on the lobby goes up by one match.

## Suggested first session (about 15 minutes)

1. **Buzzer Race** to 5 — the core loop. Deliberately answer one wrong early so
   you can watch the lockout work.
2. **Steal** — have the question owner miss on purpose and confirm the other
   player gets the steal window.
3. **Wager Rounds** — both bet 3 on the same question and check the swing.
4. **Category Draft** — the most complex flow; confirm questions only come from
   the domains you drafted.
5. **Rematch** from the results screen, then check the lobby shows the record.

## Things that are expected, not bugs

- **You'll see repeat questions.** There are only 49 built in. Generate more with
  `python3 generate.py -n 30` before a long session.
- **A server restart ends live rooms.** Match state is in memory by design. Don't
  restart mid-match; deploy or edit between games.
- **Two tabs on one computer share a name.** The profile name lives in
  localStorage per browser. Real separate devices don't have this problem — it
  only shows up when you test alone.
- **Rivalry records are per browser.** Yours count your matches; theirs count
  theirs. There is no shared server-side leaderboard.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Ready button greyed out, says "Waiting for a second player" | They never actually joined | The seat is empty — it's a connection problem, not the game |
| Red box: "Nobody else can join this server yet" | Server bound to localhost | Restart with `--lan` |
| Their browser can't load the address at all | Firewall, or different networks | Allow `python3` in the firewall; confirm both are on the *same* Wi-Fi, not one on cellular |
| Address in the lobby looks wrong | Your Mac has several interfaces (VPN, hotspot) | The startup output lists every candidate — try the next one. Prefer a `192.168.x.x` address |
| "No match with that code" | Typo, or the server restarted | Codes avoid lookalike characters, but check O/0 anyway. Open a fresh room |
| One screen freezes mid-match | Stream dropped | It reconnects on its own; you'll briefly see "Connection lost". If it persists, both leave and re-open the room |
| Match won't start though both are in | Both must press ready | Check both seats show "Ready" |

## Testing the other two connection paths

**Challenge codes** (no network at all): press **Play a run to send**, finish the
eight questions, copy the code, and send it however you like. They paste it into
**Challenge code** and press Accept. They get the identical eight questions and
see the head-to-head at the end. This is the one to use if the Wi-Fi test fails
and you still want to demo the head-to-head idea.

**Online**: see [DEPLOY.md](DEPLOY.md). One instance only — match state is in
memory, so two instances means two separate sets of rooms.

## If you're demoing this to a group

Run the host laptop on a screen and have one volunteer join from their phone. The
lobby's room code is deliberately large and readable from across a room, and the
questions are legible on a projector. Have a challenge code prepared as a fallback
in case the venue's Wi-Fi isolates clients from each other — many guest networks
do, and that will block the LAN path no matter what you configure.
