"""Checkpointed run state. Every stage writes its output here, so a crashed or
interrupted run resumes from the last completed stage."""
import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Stage:
    status: str = "pending"  # pending | running | done | failed
    attempts: int = 0
    output: dict | list | None = None
    error: str | None = None
    started: str | None = None
    finished: str | None = None


@dataclass
class RunState:
    run_id: str
    case_dir: str
    created: str = field(default_factory=_now)
    status: str = "running"  # running | done | failed
    stages: dict[str, Stage] = field(default_factory=dict)
    # Counters for bounded loops, so a resumed run doesn't restart them
    loops: dict[str, int] = field(default_factory=dict)

    _lock = threading.RLock()

    @property
    def dir(self) -> Path:
        return RUNS_DIR / self.run_id

    # ---- persistence -------------------------------------------------
    def save(self) -> None:
        with self._lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self.dir / "state.json.tmp"
            data = asdict(self)
            tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
            for attempt in range(20):  # Windows refuses the swap while a reader (e.g. the web view) has the file open
                try:
                    os.replace(tmp, self.dir / "state.json")  # atomic on the same volume
                    break
                except PermissionError:
                    if attempt == 19:
                        raise
                    time.sleep(0.05)

    @classmethod
    def load(cls, run_id: str) -> "RunState":
        data = json.loads((RUNS_DIR / run_id / "state.json").read_text(encoding="utf-8"))
        stages = {k: Stage(**v) for k, v in data.pop("stages").items()}
        return cls(**data, stages=stages)

    # ---- stage helpers -----------------------------------------------
    def stage(self, name: str) -> Stage:
        with self._lock:  # agents run in parallel threads
            if name not in self.stages:
                self.stages[name] = Stage()
            return self.stages[name]

    def is_done(self, name: str) -> bool:
        return name in self.stages and self.stages[name].status == "done"

    def output(self, name: str):
        return self.stages[name].output

    def begin(self, name: str) -> Stage:
        s = self.stage(name)
        s.status, s.started, s.error = "running", _now(), None
        s.attempts += 1
        self.save()
        return s

    def complete(self, name: str, output) -> None:
        s = self.stage(name)
        s.status, s.output, s.finished = "done", output, _now()
        self.save()

    def fail(self, name: str, error: str) -> None:
        s = self.stage(name)
        s.status, s.error, s.finished = "failed", error, _now()
        self.save()

    def reset(self, name: str) -> None:
        """Mark a stage to be redone (used by the review / fact-check loops)."""
        if name in self.stages:
            self.stages[name].status = "pending"
            self.save()

    # ---- private side files (never sent to the model) ----------------
    def write_private(self, filename: str, data) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / filename).write_text(json.dumps(data, indent=2), encoding="utf-8")

    def read_private(self, filename: str):
        return json.loads((self.dir / filename).read_text(encoding="utf-8"))
