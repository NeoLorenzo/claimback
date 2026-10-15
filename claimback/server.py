"""Local web view for demos: a live agent timeline (Server-Sent Events tailing
events.jsonl), a replay of finished runs, and the case panel (status, tasks,
correspondence, Approve & send). Binds to 127.0.0.1 only, since run and case
folders hold the local identifier map, real identifiers and the filled-in packet."""
import base64
import email.parser
import email.policy
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import cases as cases_mod
from . import letters
from .cases import CASEFILES_DIR
from .state import RUNS_DIR

ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = ROOT / "cases"
INDEX = Path(__file__).resolve().parent / "web" / "index.html"
SAFE = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
MAX_UPLOAD = 10 * 1024 * 1024

_procs: dict[str, subprocess.Popen] = {}  # runs started from the web view


def _safe_id(value: str) -> str | None:
    return value if value and set(value) <= SAFE and not value.startswith(".") else None


def _read_events(run_id: str, start: int = 0, path: Path | None = None) -> list[dict]:
    path = path or RUNS_DIR / run_id / "events.jsonl"
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


# ---- cases ------------------------------------------------------------------
def _case_dir(case_id: str) -> Path | None:
    case_id = _safe_id(case_id)
    return CASEFILES_DIR / case_id if case_id and (CASEFILES_DIR / case_id / "case.json").exists() else None


def _load_case(d: Path) -> dict:
    return json.loads((d / "case.json").read_text(encoding="utf-8"))


def _list_cases() -> list[dict]:
    out = []
    if CASEFILES_DIR.exists():
        for d in CASEFILES_DIR.iterdir():
            if not (d / "case.json").exists():
                continue
            try:
                c = _load_case(d)
            except (OSError, ValueError):
                continue  # mid-write on Windows; it shows up on the next refresh
            out.append({
                "id": c["case_id"], "case_name": c.get("case_name"), "insurer_name": c.get("insurer_name"),
                "claim_number": c.get("claim_number"), "status": c.get("status"), "stage": c.get("stage"),
                "created": c.get("created", ""),
                "waiting": sum(t["status"] == "open" and t.get("owner") == "user" for t in c.get("tasks", [])),
            })
    return sorted(out, key=lambda c: c["created"], reverse=True)


def _case_detail(d: Path) -> dict:
    c = _load_case(d)
    c.pop("processed_message_ids", None)
    root = d.resolve()
    for o in c.get("outbox", []):
        body = (d / o.get("body_file", "")).resolve()
        o["body"] = body.read_text(encoding="utf-8") if body.is_file() and body.is_relative_to(root) else None
        if o["body"] is not None:
            # Preview exactly what will be emailed: send-time dates filled, markdown rendered (escaped)
            o["body_html"] = letters.to_html(letters.fill_send_time(o["body"]))
            o["blanks"] = letters.unresolved_blanks(o["body"]) if o.get("status") == "awaiting_approval" else []
    c["event_count"] = len(_read_events("", path=d / "events.jsonl"))
    return c


def _clean_filename(name: str) -> str:
    name = Path(str(name).replace("\\", "/")).name
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).lstrip("._")[:100]
    return name or "upload"


def _backend(name: str):
    """Case actions live in cases.py; look them up per request so the panel works as they land."""
    return getattr(cases_mod, name, None)


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
        if parts == ["api", "case-dirs"]:  # input folders a new run can start from
            dirs = sorted(d.name for d in CASES_DIR.iterdir() if (d / "denial_letter.txt").exists() or any(d.glob("*denial*.txt")))
            return self._json(dirs)
        if parts == ["api", "cases"]:
            return self._json(_list_cases())
        if len(parts) in (3, 4) and parts[:2] == ["api", "cases"]:
            d = _case_dir(parts[2])
            if not d:
                return self._json({"error": "no such case"}, 404)
            if len(parts) == 3:
                try:
                    return self._json(_case_detail(d))
                except (OSError, ValueError):
                    return self._json({"error": "case is being written, retry"}, 503)
            if parts[3] == "stream":
                return self._stream(d.name, int(query.get("from", ["0"])[0]), d / "events.jsonl")
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
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        if len(parts) == 4 and parts[:2] == ["api", "cases"]:
            return self._case_action(parts[2], parts[3])
        if parts != ["api", "start"]:
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

    # ---- case actions ---------------------------------------------------
    def _read_body(self, limit: int) -> bytes | None:
        length = int(self.headers.get("Content-Length") or 0)
        if length > limit:
            self._json({"error": f"too large (max {MAX_UPLOAD // 2**20} MB)"}, 413)
            return None
        return self.rfile.read(length)

    def _upload_fields(self, raw: bytes) -> tuple[str, str, bytes]:
        """multipart/form-data (task_id + file) or JSON {task_id, filename, data_b64}."""
        ctype = self.headers.get("Content-Type", "")
        if ctype.startswith("multipart/form-data"):
            msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
                f"Content-Type: {ctype}\r\n\r\n".encode() + raw)
            fields, filename, data = {}, "", b""
            for part in msg.iter_parts():
                if part.get_filename() is not None:
                    filename, data = part.get_filename(), part.get_payload(decode=True) or b""
                elif name := part.get_param("name", header="content-disposition"):
                    fields[name] = (part.get_payload(decode=True) or b"").decode("utf-8", "replace").strip()
            return fields.get("task_id", ""), filename, data
        body = json.loads(raw or b"{}")
        return body.get("task_id", ""), body.get("filename", ""), base64.b64decode(body.get("data_b64", ""), validate=True)

    def _case_action(self, case_id: str, action: str) -> None:
        d = _case_dir(case_id)
        if not d:
            return self._json({"error": "no such case"}, 404)
        fn_name = {"approve": "approve_outbox", "upload": "add_upload", "confirm-outcome": "confirm_outcome",
                   "edit": "update_outbox"}.get(action)
        if not fn_name:
            return self._json({"error": "not found"}, 404)
        raw = self._read_body(MAX_UPLOAD * 4 // 3 + 65536 if action == "upload" else 262144)
        if raw is None:
            return
        fn = _backend(fn_name)
        refused = _backend("ActionRefused") or type("NoActionRefused", (Exception,), {})
        if fn is None:
            return self._json({"error": "not built yet"}, 501)
        try:
            if action == "upload":
                task_id, filename, data = self._upload_fields(raw)
                if len(data) > MAX_UPLOAD:
                    return self._json({"error": f"too large (max {MAX_UPLOAD // 2**20} MB)"}, 413)
                if not data:
                    return self._json({"error": "empty file"}, 400)
                return self._json({"ok": True, "upload": fn(d.name, task_id, _clean_filename(filename), data)})
            body = json.loads(raw or b"{}")
            if action == "approve":
                return self._json({"ok": True, "message_id": fn(d.name, body.get("outbox_id", ""))})
            if action == "edit":
                return self._json({"ok": True, **fn(d.name, body.get("outbox_id", ""), str(body.get("body", "")))})
            fn(d.name, body.get("task_id", ""))
            return self._json({"ok": True})
        except refused as e:  # valid request, but the case's state or allow-list says no
            return self._json({"error": str(e) or "refused"}, 409)
        except (ValueError, LookupError) as e:  # malformed body, bad base64
            return self._json({"error": str(e) or type(e).__name__}, 400)
        except Exception as e:  # keep the server up; the panel shows the message
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    # ---- live stream ----------------------------------------------------
    def _stream(self, run_id: str, start: int, path: Path | None = None) -> None:
        """Tail a run's events.jsonl, or with `path` a case timeline, which never ends: cases are long-lived."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        sent = start
        quiet_since = time.monotonic()
        try:
            while True:
                events = _read_events(run_id, sent, path)
                for e in events:
                    self.wfile.write(f"data: {json.dumps(e)}\n\n".encode())
                sent += len(events)
                status = "open" if path else _status(run_id)
                if events:
                    quiet_since = time.monotonic()
                elif path is None and status not in ("running", "starting") and time.monotonic() - quiet_since > 1.5:
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
