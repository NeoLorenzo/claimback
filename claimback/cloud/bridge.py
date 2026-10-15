"""Mirror: copies what the pipeline and the case worker write locally (run state,
case files, timeline events, the finished packet) into Supabase, where each
signed-in user can read only their own rows (row-level security).

Never mirrored: the identifier map (phi_map.json), raw inbound email, or stage
outputs. Those stay on the worker's private disk."""
import json
import queue
import threading
from pathlib import Path

from ..cases import CASEFILES_DIR
from ..log import add_sink
from ..state import RUNS_DIR, add_write_hook
from .supa import Supabase

ROOT = RUNS_DIR.parent
META = "cloud.json"  # runs/<id>/cloud.json: {"owner": uuid, "mode": "mock" | "live"}

_sb: Supabase | None = None
_q: "queue.Queue[tuple]" = queue.Queue()
_thread: threading.Thread | None = None


# ---- who owns what --------------------------------------------------------------
def write_meta(run_id: str, owner: str, mode: str) -> None:
    d = RUNS_DIR / run_id
    d.mkdir(parents=True, exist_ok=True)
    (d / META).write_text(json.dumps({"owner": owner, "mode": mode}), encoding="utf-8")


def run_meta(run_id: str) -> dict:
    try:
        return json.loads((RUNS_DIR / run_id / META).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def case_meta(case_id: str) -> dict:
    try:
        run_id = json.loads((CASEFILES_DIR / case_id / "case.json").read_text(encoding="utf-8"))["run_id"]
    except (OSError, ValueError, KeyError):
        return {}
    return run_meta(run_id)


def _scrub(value):
    """Drop worker filesystem paths from anything shown in the browser."""
    if isinstance(value, str):
        for prefix in (str(ROOT), str(ROOT).replace("\\", "/")):
            value = value.replace(prefix + "/", "").replace(prefix + "\\", "").replace(prefix, "")
        return value
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def _where(path: Path) -> tuple[str | None, str | None]:
    """(run_id, case_id) for a log or state file path."""
    parent = path.parent
    if parent.parent == RUNS_DIR:
        return parent.name, None
    if parent.parent == CASEFILES_DIR:
        return None, parent.name
    return None, None


# ---- hooks (called synchronously by log.emit / atomic_write_json) -----------------
def _on_event(record: dict, path: Path | None) -> None:
    if path is None:
        return
    run_id, case_id = _where(path)
    meta = run_meta(run_id) if run_id else case_meta(case_id) if case_id else {}
    if not meta.get("owner"):
        return  # a local run that nobody in the hosted app owns
    _q.put(("event", meta["owner"], run_id, case_id, record))


def _on_write(path: Path, data) -> None:
    run_id, case_id = _where(path)
    if run_id and path.name == "state.json":
        meta = run_meta(run_id)
        if meta.get("owner"):
            _q.put(("run", meta, run_id, data))
    elif case_id and path.name == "case.json":
        meta = case_meta(case_id)
        if meta.get("owner"):
            _q.put(("case", meta, case_id, data))


# ---- background sender (keeps network calls out of the agents' path) ---------------
def _send(item: tuple) -> None:
    kind = item[0]
    if kind == "event":
        _, owner, run_id, case_id, r = item
        _sb.insert("events", {"owner": owner, "run_id": run_id, "case_id": case_id, "ts": r["ts"],
                              "agent": r["agent"], "kind": r["kind"], "message": _scrub(r["message"]),
                              "data": _scrub(r.get("data") or {})})
        data = r.get("data") or {}
        if run_id and data.get("final") and data.get("merit"):
            _sb.update("runs", {"id": run_id}, {"verdict": data["merit"]})
    elif kind == "run":
        _, meta, run_id, state = item
        stages = {k: {"status": v["status"], "attempts": v["attempts"]} for k, v in state["stages"].items()}
        row = {"id": run_id, "owner": meta["owner"], "mode": meta["mode"], "status": state["status"],
               "case_name": Path(state["case_dir"]).name, "stages": stages}
        packet = RUNS_DIR / run_id / "output" / "appeal_packet.html"
        if state["stages"].get("package", {}).get("status") == "done" and packet.exists():
            base = f"{meta['owner']}/{run_id}"
            _sb.upload("packets", f"{base}/appeal_packet.html", packet.read_bytes(), "text/html")
            md = packet.with_suffix(".md")
            if md.exists():
                _sb.upload("packets", f"{base}/appeal_packet.md", md.read_bytes(), "text/markdown")
            row["packet_path"] = f"{base}/appeal_packet.html"
        _sb.insert("runs", row, upsert=True)
    elif kind == "case":
        _, meta, case_id, case = item
        case = json.loads(json.dumps(case, default=str))
        for o in case.get("outbox", []):  # the draft text the human approves
            try:
                o["body"] = (CASEFILES_DIR / case_id / o["body_file"]).read_text(encoding="utf-8")
            except (OSError, KeyError):
                o["body"] = None
        case.pop("processed_message_ids", None)
        _sb.insert("cases", {"id": case_id, "owner": meta["owner"], "run_id": case["run_id"],
                             "status": case["status"], "stage": case["stage"], "data": _scrub(case)}, upsert=True)


def _loop() -> None:
    while True:
        item = _q.get()
        try:
            _send(item)
        except Exception as e:
            print(f"[mirror] {item[0]} not mirrored: {type(e).__name__}: {str(e)[:200]}", flush=True)
        finally:
            _q.task_done()


def install(sb: Supabase | None = None) -> Supabase:
    """Start mirroring this process's runs and cases. Idempotent."""
    global _sb, _thread
    if _sb is None:
        _sb = sb or Supabase()
        add_sink(_on_event)
        add_write_hook(_on_write)
        _thread = threading.Thread(target=_loop, name="supabase-mirror", daemon=True)
        _thread.start()
    return _sb


def flush() -> None:
    """Wait until everything written so far has reached Supabase."""
    _q.join()
