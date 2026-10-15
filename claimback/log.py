"""Live event log: colored console lines for the demo, JSONL on disk for replay."""
import json
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

COLORS = {
    "orchestrator": "\033[1;37m",
    "planner": "\033[1;35m",
    "intake": "\033[36m",
    "policy_analyst": "\033[34m",
    "evidence_researcher": "\033[32m",
    "writer": "\033[33m",
    "reviewer": "\033[31m",
    "fact_checker": "\033[95m",
    "packager": "\033[92m",
    "case_worker": "\033[1;36m",
    "connector": "\033[96m",
    "insurer_sim": "\033[90m",
    "correspondence": "\033[94m",
}
RESET = "\033[0m"
DIM = "\033[2m"

_lock = threading.Lock()
_log_path: Path | None = None
_t0 = time.monotonic()
_sinks: list = []  # extra destinations for events, e.g. the hosted app's database (claimback/cloud)
_ctx = threading.local()  # per-thread defaults: which log file, plus fields like the current stage

if sys.platform == "win32":
    import os
    os.system("")  # enable ANSI escape handling in Windows consoles
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def set_log_file(path: Path) -> None:
    global _log_path
    _log_path = path
    path.parent.mkdir(parents=True, exist_ok=True)


def add_sink(fn) -> None:
    """fn(record, path) is called after every event; path is the run or case log it went to."""
    _sinks.append(fn)


@contextmanager
def context(path: Path | None = None, prefix: str | None = None, **data):
    """Defaults for every emit in this thread: the log file (e.g. one case's timeline,
    so model-usage lines land next to the agent that made the call), a console
    prefix, and fields merged into each event's data (e.g. the current stage)."""
    saved = (getattr(_ctx, "path", None), getattr(_ctx, "prefix", ""), getattr(_ctx, "data", {}))
    _ctx.path = path or saved[0]
    _ctx.prefix = saved[1] if prefix is None else prefix
    _ctx.data = {**saved[2], **data}
    try:
        yield
    finally:
        _ctx.path, _ctx.prefix, _ctx.data = saved


def emit(agent: str, kind: str, message: str, _path: Path | None = None, _console_prefix: str = "",
         **data) -> None:
    """kind: start | done | info | handoff | retry | error | loop | warn.
    _path overrides the run log, e.g. to write to one case's timeline.
    data is the structured part of the event; it must never hold identifiers,
    only placeholders, counts and de-identified facts."""
    data = {**getattr(_ctx, "data", {}), **data}
    _path = _path or getattr(_ctx, "path", None)
    _console_prefix = _console_prefix or getattr(_ctx, "prefix", "")
    elapsed = time.monotonic() - _t0
    color = COLORS.get(agent, "")
    marker = {
        "start": "▶", "done": "✓", "handoff": "→", "retry": "↻",
        "error": "✗", "loop": "⟲", "warn": "!", "info": "·",
    }.get(kind, "·")
    line = f"{DIM}{elapsed:6.1f}s{RESET} {color}{agent:>19}{RESET} {marker} {_console_prefix}{message}"
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "elapsed": round(elapsed, 2),
        "agent": agent,
        "kind": kind,
        "message": message,
        **({"data": data} if data else {}),
    }
    with _lock:
        print(line, flush=True)
        target = _path or _log_path
        if target:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")
        for sink in _sinks:
            try:
                sink(record, target)
            except Exception as e:  # a mirror must never break the run
                print(f"[event sink failed: {type(e).__name__}: {e}]", file=sys.stderr)
