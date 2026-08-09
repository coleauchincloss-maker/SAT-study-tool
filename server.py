#!/usr/bin/env python3
"""SAT Quest server: static files, question generation, and 1v1 matches.

    python3 server.py                 # http://localhost:5173, this machine only
    python3 server.py --lan           # also reachable from other devices on your Wi-Fi
    python3 server.py -p 8080 --open

Endpoints
    GET  /api/status            what this server can do
    POST /api/generate          generate questions with Claude (needs ANTHROPIC_API_KEY)
    GET  /api/match/info        available modes and bank size
    POST /api/match/create      open a room, returns a 4-character code
    POST /api/match/join        join a room by code
    POST /api/match/action      ready / answer / wager / pick / rematch / leave
    GET  /api/match/stream      Server-Sent Events stream of match state
    GET  /api/match/state       one-shot state read (fallback for no EventSource)

The generation key stays in this process — the browser never sees it. Match state
is authoritative here too, so neither player can fake a score from the console.
"""

import argparse
import functools
import http.server
import json
import os
import socket
import socketserver
import threading
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))

# A generation request costs real money, so bound what one click can spend.
MAX_PER_REQUEST = 10
MAX_BODY_BYTES = 8192
# Bring-your-own-questions payloads are plain data (no LLM call), so they can
# be much larger than a normal intent — a few hundred questions still fits.
MAX_IMPORT_BODY_BYTES = 4_000_000
MAX_IMPORT_QUESTIONS = 1000
SSE_HEARTBEAT_SECONDS = 15.0

# One generation at a time: concurrent runs would race on data/generated.json.
_generation_lock = threading.Lock()


class Handler(http.server.SimpleHTTPRequestHandler):
    # The app is 17 ES modules. Under HTTP/1.0 (the default here) every one of
    # those needs its own TCP connection, and a burst of ~17 handshakes over
    # Wi-Fi is enough for some to be dropped — which shows up as a page that
    # loads but never runs, because one module silently failed to arrive.
    # HTTP/1.1 keep-alive lets the browser pull them all down a few reused
    # connections instead. Every response below must then carry an accurate
    # Content-Length, or send Connection: close (the SSE stream does).
    protocol_version = "HTTP/1.1"

    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript",
        ".mjs": "text/javascript",
        ".css": "text/css",
        ".json": "application/json",
    }

    # ─────────────────────────── helpers ───────────────────────────
    def _api_headers(self):
        # The app is normally served from this same origin, but allowing any origin
        # lets a locally-open page talk to a deployed match server. There are no
        # cookies or credentials involved, so this grants no ambient authority.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._api_headers()
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self, max_bytes=MAX_BODY_BYTES):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if length <= 0:
            return {}
        if length > max_bytes:
            raise ValueError("request body too large")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _query(self):
        from urllib.parse import parse_qs, urlparse

        return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}

    @property
    def _route(self):
        return self.path.split("?")[0].rstrip("/") or "/"

    # ─────────────────────────── dispatch ───────────────────────────
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self._api_headers()
        self.end_headers()

    def do_GET(self):
        route = self._route
        if route == "/ping":
            # Deliberately trivial: plain text, no JavaScript, no app. If this
            # loads on a phone the network is fine and the problem is the app.
            body = b"SAT Quest server is reachable from this device.\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._api_headers()
            self.end_headers()
            return self.wfile.write(body)
        if route == "/api/status":
            return self._status()
        if route == "/api/match/info":
            return self._match_info()
        if route == "/api/match/state":
            return self._match_state()
        if route == "/api/match/stream":
            return self._match_stream()
        if route == "/api/questions/imported":
            return self._questions_imported()
        return super().do_GET()

    def do_POST(self):
        import match

        route = self._route
        routes = {
            "/api/generate": self._generate,
            "/api/match/create": self._match_create,
            "/api/match/join": self._match_join,
            "/api/match/action": self._match_action,
            "/api/questions/import": self._questions_import,
            "/api/questions/import/clear": self._questions_import_clear,
        }
        handler = routes.get(route)
        if not handler:
            return self._send_json({"error": f"no such endpoint: {route}"}, status=404)

        max_bytes = MAX_IMPORT_BODY_BYTES if route == "/api/questions/import" else MAX_BODY_BYTES
        try:
            body = self._read_json_body(max_bytes)
        except (ValueError, json.JSONDecodeError) as exc:
            return self._send_json({"error": f"bad request body: {exc}"}, status=400)

        try:
            return handler(body)
        except match.MatchError as exc:
            return self._send_json({"error": str(exc)}, status=400)

    # ─────────────────────────── generation ───────────────────────────
    def _status(self):
        import match
        import satquest_gen as gen

        self._send_json(
            {
                "generation": bool(os.environ.get("ANTHROPIC_API_KEY")),
                "model": gen.MODEL,
                "generated": len(gen.load_generated()),
                "imported": len(gen.load_imported()),
                "maxPerRequest": MAX_PER_REQUEST,
                "domains": gen.DOMAINS,
                "pool": match.POOL.counts(),
                "importedPool": match.IMPORTED_POOL.counts(),
                **self._reachability(),
            }
        )

    def _reachability(self):
        """Can another device reach this server, or is it localhost-only?

        This is the difference between "give your friend the code" working and
        silently never working, so the app surfaces it rather than leaving the
        host staring at an empty seat.
        """
        host, port = self.server.server_address[0], self.server.server_address[1]
        lan_bound = host in ("0.0.0.0", "::")
        return {
            "lanBound": lan_bound,
            "lanUrl": _lan_url(port) if lan_bound else None,
            "lanUrls": _lan_urls(port) if lan_bound else [],
            "boundTo": host,
            "port": port,
        }

    def _generate(self, body):
        import satquest_gen as gen

        try:
            count = int(body.get("count", 5))
        except (TypeError, ValueError):
            return self._send_json({"error": "count must be a number"}, status=400)
        count = max(1, min(count, MAX_PER_REQUEST))

        if not _generation_lock.acquire(blocking=False):
            return self._send_json({"error": "a generation run is already in progress"}, status=409)
        try:
            self.log_message("generating %d question(s) (section=%s domain=%s)",
                             count, body.get("section"), body.get("domain"))
            report = gen.generate_and_save(
                count=count,
                section=body.get("section") or None,
                domain=body.get("domain") or None,
                skills=body.get("skills") or None,
                verify=body.get("verify", True),
                effort=body.get("effort", "high"),
                progress=lambda msg: self.log_message("%s", msg),
            )
        except gen.GenerationError as exc:
            return self._send_json({"error": str(exc)}, status=502)
        except Exception as exc:  # surface the reason instead of a bare 500
            return self._send_json({"error": f"{type(exc).__name__}: {exc}"}, status=500)
        finally:
            _generation_lock.release()

        self._send_json(report.as_dict())

    # ─────────────────────────── bring-your-own questions ───────────────────────────
    def _questions_imported(self):
        import satquest_gen as gen

        questions = gen.load_imported()
        preview = [
            {"id": q["id"], "section": q["section"], "domain": q["domain"],
             "skill": q["skill"], "prompt": q["prompt"][:140]}
            for q in questions
        ]
        self._send_json({"count": len(questions), "questions": preview})

    def _questions_import(self, body):
        import satquest_gen as gen

        raw = body.get("questions")
        if not isinstance(raw, list) or not raw:
            return self._send_json({"error": "expected a non-empty 'questions' array"}, status=400)
        if len(raw) > MAX_IMPORT_QUESTIONS:
            return self._send_json({"error": f"at most {MAX_IMPORT_QUESTIONS} questions per import"}, status=400)

        try:
            report = gen.import_questions(raw)
        except Exception as exc:  # malformed items shouldn't 500 the server
            return self._send_json({"error": f"{type(exc).__name__}: {exc}"}, status=400)
        self._send_json(report.as_dict())

    def _questions_import_clear(self, _body):
        import satquest_gen as gen

        gen.clear_imported()
        self._send_json({"ok": True})

    # ─────────────────────────── matches ───────────────────────────
    def _match_info(self):
        import match

        info = match.SERVER.lobby_info()
        info.update(self._reachability())
        self._send_json(info)

    def _match_create(self, body):
        import match

        room, player = match.SERVER.create(
            name=body.get("name", ""),
            mode=body.get("mode", "buzzer"),
            section=body.get("section") or None,
            target=body.get("target"),
            question_seconds=body.get("questionSeconds"),
            focus_mode=bool(body.get("focusMode")),
            source=body.get("source") or "all",
        )
        self.log_message("room %s opened by %s (%s)", room.code, player.name, room.mode)
        self._send_json(
            {"code": room.code, "playerId": player.pid, "state": match.SERVER.snapshot(room.code, player.pid)}
        )

    def _match_join(self, body):
        import match

        room, player = match.SERVER.join(code=body.get("code", ""), name=body.get("name", ""))
        self.log_message("room %s joined by %s", room.code, player.name)
        self._send_json(
            {"code": room.code, "playerId": player.pid, "state": match.SERVER.snapshot(room.code, player.pid)}
        )

    def _match_action(self, body):
        import match

        code = body.get("code", "")
        pid = body.get("playerId", "")
        match.SERVER.action(code, pid, body.get("type", ""), body.get("payload") or {})
        # The room can disappear on "leave"; report that plainly instead of 500ing.
        try:
            state = match.SERVER.snapshot(code, pid)
        except match.MatchError:
            state = None
        self._send_json({"ok": True, "state": state})

    def _match_state(self):
        import match

        params = self._query()
        try:
            self._send_json(match.SERVER.snapshot(params.get("code", ""), params.get("playerId")))
        except match.MatchError as exc:
            self._send_json({"error": str(exc)}, status=404)

    def _match_stream(self):
        """Server-Sent Events: one message per state change, plus heartbeats."""
        import match

        params = self._query()
        code = params.get("code", "")
        pid = params.get("playerId")

        try:
            state = match.SERVER.snapshot(code, pid)
        except match.MatchError as exc:
            return self._send_json({"error": str(exc)}, status=404)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        # No Content-Length is possible on a stream, so under HTTP/1.1 the
        # connection must be marked as closing or the client will hang.
        self.send_header("Connection", "close")
        self.close_connection = True
        self.send_header("X-Accel-Buffering", "no")  # defeat proxy buffering when deployed
        self._api_headers()
        self.end_headers()

        epoch = match.SERVER.open_stream(code, pid) if pid else 0
        seq = -1
        last_beat = 0.0

        try:
            while True:
                if state is not None and state["seq"] != seq:
                    seq = state["seq"]
                    self.wfile.write(f"data: {json.dumps(state)}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    last_beat = match.now()

                state = match.SERVER.wait_for_change(code, pid, seq, timeout=5.0)
                if state is None:  # nothing changed; keep the connection warm
                    if match.now() - last_beat > SSE_HEARTBEAT_SECONDS:
                        self.wfile.write(b": keep-alive\n\n")
                        self.wfile.flush()
                        last_beat = match.now()
        except match.MatchError:
            try:
                self.wfile.write(b'data: {"gone": true}\n\n')
                self.wfile.flush()
            except OSError:
                pass
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # the player closed the tab or dropped off the network
        finally:
            if pid:
                match.SERVER.close_stream(code, pid, epoch)

    # ─────────────────────────── plumbing ───────────────────────────
    def end_headers(self):
        # No caching for the app itself, so an edit is one refresh away.
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()

    def log_message(self, fmt, *args):
        # Quiet the per-asset noise; keep API and match activity.
        first = str(args[0]) if args else ""
        if first.startswith("GET /") and "/api/" not in first:
            return
        super().log_message(fmt, *args)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    # Default is 5. A phone opening the app fires off a burst of parallel
    # requests; anything past the backlog is refused by the OS before Python
    # ever sees it, and the browser reports it as a failed asset.
    request_queue_size = 128


def _private_rank(address):
    """Order candidate addresses by how likely a phone on the Wi-Fi can reach them.

    A laptop often has several interfaces — Wi-Fi, a VPN tunnel, Docker, iPhone
    tethering. Guessing wrong hands the user an address their opponent cannot
    reach, which looks exactly like the app being broken, so rank rather than
    guess and show the alternatives.
    """
    if address.startswith("192.168."):
        return 0  # ordinary home Wi-Fi / router LAN
    if address.startswith("10."):
        return 1  # common on larger or corporate networks
    try:
        second = int(address.split(".")[1])
        if address.startswith("172.") and 16 <= second <= 31:
            return 2  # private, but often a VPN or container bridge
    except (IndexError, ValueError):
        pass
    return 3


def _lan_addresses():
    """Every private IPv4 address this machine appears to have, best first."""
    found = set()

    # The routing table's choice for reaching the outside world.
    for target in ("10.255.255.255", "192.168.1.1", "8.8.8.8"):
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            probe.settimeout(0.15)
            probe.connect((target, 1))  # no packets sent; just resolves a route
            found.add(probe.getsockname()[0])
            probe.close()
        except OSError:
            pass

    # Anything else the host resolves to, which catches interfaces the routing
    # table wouldn't pick.
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except (socket.gaierror, OSError):
        pass

    usable = [a for a in found if not a.startswith("127.") and _private_rank(a) < 3]
    return sorted(usable, key=lambda a: (_private_rank(a), a))


def _lan_url(port):
    """Best-guess address for the join screen."""
    addresses = _lan_addresses()
    return f"http://{addresses[0]}:{port}/" if addresses else None


def _lan_urls(port):
    """All candidates, so the user can try another if the first one fails."""
    return [f"http://{address}:{port}/" for address in _lan_addresses()]


def main():
    parser = argparse.ArgumentParser(description="Serve SAT Quest locally.")
    # PORT is what Fly/Render/Railway inject, so a deploy needs no extra flags.
    parser.add_argument("-p", "--port", type=int, default=int(os.environ.get("PORT", 5173)))
    parser.add_argument("--host", default=None, help="bind address (default 127.0.0.1)")
    parser.add_argument(
        "--lan",
        action="store_true",
        help="bind 0.0.0.0 so a friend on the same Wi-Fi can join your match",
    )
    parser.add_argument("--open", action="store_true", help="open the app in a browser")
    args = parser.parse_args()

    host = args.host or ("0.0.0.0" if args.lan else "127.0.0.1")
    handler = functools.partial(Handler, directory=ROOT)

    with Server((host, args.port), handler) as httpd:
        print(f"SAT Quest → http://localhost:{args.port}/   (Ctrl+C to stop)")
        if args.lan or host == "0.0.0.0":
            urls = _lan_urls(args.port)
            if urls:
                print(f"On your Wi-Fi  → {urls[0]}   (give this to your opponent)")
                for other in urls[1:]:
                    print(f"   or try     → {other}")
            else:
                print("On your Wi-Fi  → could not detect this machine's address")
        else:
            print("This machine only. Use --lan to let a friend join from their device.")
        print("Generation     → " + ("enabled" if os.environ.get("ANTHROPIC_API_KEY")
                                     else "disabled (ANTHROPIC_API_KEY not set in this shell)"))
        if args.open:
            webbrowser.open(f"http://localhost:{args.port}/")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")


if __name__ == "__main__":
    main()
