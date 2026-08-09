# Putting the match server online

You need this only for playing someone who **isn't on your Wi-Fi**. Local play
(`python3 server.py --lan`) and challenge codes need no deployment at all.

The deployed server is the same `server.py` you already run — it serves the app
*and* the match API, so both players just open the deployed URL.

## The one constraint that matters

**Match state lives in memory, on one process.** There is no database. That is a
deliberate trade (rooms are ephemeral and last minutes), but it means:

- Run **exactly one instance**. Two instances means two separate sets of rooms,
  and your opponent can be routed to the one that has never heard of your code.
- Don't let the host suspend or scale-to-zero the machine mid-match — a restart
  drops every live room. Players get "no match with that code" and re-open a room.
- A deploy restarts the process, so deploy between matches.

If you later want rooms to survive restarts or run on several instances, the state
in `match.py` would need to move to Redis or Postgres. Nothing else changes.

## Fly.io

`fly.toml` and `Dockerfile` are ready. From this directory:

```bash
fly launch --no-deploy --copy-config --name your-app-name
```

```bash
fly deploy && fly scale count 1
```

`fly scale count 1` is not optional — see above. Then both players open
`https://your-app-name.fly.dev`.

To enable question generation on the deployed server:

```bash
fly secrets set ANTHROPIC_API_KEY=sk-ant-...
```

Leave that unset and the deployed app still plays fine; the generate buttons are
just disabled and you generate locally instead (`python3 generate.py -n 20`), then
redeploy to ship the new questions.

## Any other host

Anything that can run a container and route HTTP works — Render, Railway,
Koyeb, a VPS. Two requirements:

1. **Set the instance count to 1.**
2. **Don't buffer responses.** The state stream is Server-Sent Events. The server
   already sends `X-Accel-Buffering: no`, which nginx-based proxies respect; if a
   host buffers anyway, matches will look frozen and then jump. Test by opening a
   room in two browsers and watching whether the second player appears instantly.

`PORT` is read from the environment, so most hosts need no extra configuration.

## Pointing a local page at a deployed server

You don't have to open the deployed URL. On the lobby, under *"Play someone not
on your network"*, paste the deployed base URL. Your local page then runs matches
against that server. This is handy when you want your own questions locally but a
shared server for play.

The API allows any origin (`Access-Control-Allow-Origin: *`) so this works. There
are no cookies or credentials involved — a room code is the only thing gating a
match, which is the right level of security for a game between friends and the
wrong level for anything private.

## What's exposed

Anyone with the URL can open rooms and generate questions if you set the API key.
There is no login. Rate limiting is one generation at a time and ten questions per
request, which bounds cost but does not stop someone who finds your URL from
spending your credits. For a server you share beyond friends, either leave
`ANTHROPIC_API_KEY` unset on the deployment or put the whole thing behind auth.
