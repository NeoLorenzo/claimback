"""Local web view for demos: a live agent timeline (Server-Sent Events tailing
events.jsonl) and a replay of finished runs. Binds to 127.0.0.1 only, since run
folders hold the local identifier map and the filled-in packet."""
import json
import subprocess
import sys
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .state import RUNS_DIR

ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = ROOT / "cases"
INDEX = Path(__file__).resolve().parent / "web" / "index.html"
SAFE = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")

_procs: dict[str, subprocess.Popen] = {}  # runs started from the web view


def _safe_id(value: str) -> str | None:
    return value if value and set(value) <= SAFE and not value.startswith(".") else None


def _read_events(run_id: str, start: int = 0) -> list[dict]:
    path = RUNS_DIR / run_id / "events.jsonl"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines[start:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            break  # partially written last line; pick it up next poll
    return out


def _status(run_id: str) -> str:
    proc = _procs.get(run_id)
    try:
        status = json.loads((RUNS_DIR / run_id / "state.json").read_text(encoding="utf-8"))["status"]
    except (OSError, ValueError, KeyError):
        status = "starting" if proc else "unknown"
    if status in ("running", "starting") and proc and proc.poll() is not None:
        return "done" if proc.returncode == 0 else "failed"
    return status


def _list_runs() -> list[dict]:
    runs = []
    if RUNS_DIR.exists():
        for d in RUNS_DIR.iterdir():
            if not d.is_dir():
                continue
            try:
                state = json.loads((d / "state.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            runs.append({
                "id": d.name,
                "case": Path(state["case_dir"]).name,
                "created": state["created"],
                "status": _status(d.name),
                "has_packet": (d / "output" / "appeal_packet.html").exists(),
            })
    return sorted(runs, key=lambda r: r["created"], reverse=True)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep the console for the agent log
        pass

    # ---- helpers ------------------------------------------------------
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code: int = 200) -> None:
        self._send(code, json.dumps(data).encode(), "application/json")

    # ---- routes -------------------------------------------------------
    def do_GET(self):
        url = urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        query = parse_qs(url.query)

        if not parts:
            return self._send(200, INDEX.read_bytes(), "text/html; charset=utf-8")
        if parts == ["api", "runs"]:
            return self._json(_list_runs())
        if parts == ["api", "cases"]:
            cases = sorted(d.name for d in CASES_DIR.iterdir() if (d / "denial_letter.txt").exists() or any(d.glob("*denial*.txt")))
            return self._json(cases)
        if len(parts) == 4 and parts[:2] == ["api", "runs"]:
            run_id = _safe_id(parts[2])
            if not run_id or not (RUNS_DIR / run_id).is_dir():
                return self._json({"error": "no such run"}, 404)
            if parts[3] == "events":
                return self._json({"status": _status(run_id), "events": _read_events(run_id)})
            if parts[3] == "stream":
                return self._stream(run_id, int(query.get("from", ["0"])[0]))
            if parts[3] == "packet":
                packet = RUNS_DIR / run_id / "output" / "appeal_packet.html"
                if packet.exists():
                    return self._send(200, packet.read_bytes(), "text/html; charset=utf-8")
                return self._json({"error": "packet not ready"}, 404)
        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        if urlparse(self.path).path != "/api/start":
            return self._json({"error": "not found"}, 404)
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        case = _safe_id(body.get("case", ""))
        if not case or not (CASES_DIR / case).is_dir():
            return self._json({"error": "unknown case"}, 400)
        run_id = f"{case}-{datetime.now():%Y%m%d-%H%M%S}"
        cmd = [sys.executable, "-m", "claimback", "run", str(CASES_DIR / case), "--run-id", run_id]
        for flag in ("chaos", "offline", "mock"):
            if body.get(flag):
                cmd.append(f"--{flag}")
        log_dir = RUNS_DIR / run_id
        log_dir.mkdir(parents=True, exist_ok=True)
        console = open(log_dir / "console.log", "w", encoding="utf-8")
        _procs[run_id] = subprocess.Popen(cmd, cwd=ROOT, stdout=console, stderr=subprocess.STDOUT)
        return self._json({"run_id": run_id})

    # ---- live stream ----------------------------------------------------
    def _stream(self, run_id: str, start: int) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        sent = start
        quiet_since = time.monotonic()
        try:
            while True:
                events = _read_events(run_id, sent)
                for e in events:
                    self.wfile.write(f"data: {json.dumps(e)}\n\n".encode())
                sent += len(events)
                status = _status(run_id)
                if events:
                    quiet_since = time.monotonic()
                elif status not in ("running", "starting") and time.monotonic() - quiet_since > 1.5:
                    self.wfile.write(f"event: end\ndata: {json.dumps({'status': status})}\n\n".encode())
                    self.wfile.flush()
                    return
                else:
                    self.wfile.write(b": keep-alive\n\n")
                self.wfile.flush()
                time.sleep(0.4)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return


def serve(port: int = 8765) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    print(f"ClaimBack timeline: http://127.0.0.1:{port}  (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
