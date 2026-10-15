"""A case is the long-lived record of one appeal: it outlives the generation run
that drafted the first letter, collects every message to and from the insurer,
and tracks what has to happen next and who has to do it."""
import json
import os
import re
import secrets
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import redact
from .log import emit as _emit
from .state import RUNS_DIR, RunState, atomic_write_json

ROOT = Path(__file__).resolve().parent.parent
CASEFILES_DIR = ROOT / "casefiles"
CASE_ADDRESS_RE = re.compile(r"\+cb-([a-z0-9-]+)@", re.IGNORECASE)

STATUSES = ("awaiting_human", "awaiting_insurer", "action_required", "closed")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def mailbox_address() -> str:
    """The ClaimBack inbox. Each case gets a plus address on it."""
    return os.environ.get("CLAIMBACK_EMAIL", "claimback.demo@example.com")


def case_address(case_id: str) -> str:
    local, _, domain = mailbox_address().partition("@")
    return f"{local}+cb-{case_id}@{domain}"


def case_id_from_addresses(addresses: list[str]) -> str | None:
    for a in addresses:
        m = CASE_ADDRESS_RE.search(a or "")
        if m:
            return m.group(1).lower()
    return None


@dataclass
class Case:
    case_id: str
    run_id: str
    case_name: str
    reply_address: str
    insurer_addresses: list[str]  # allow-list: the only recipients Approve & send may use
    claim_number: str
    insurer_name: str
    created: str = field(default_factory=_now)
    status: str = "action_required"
    stage: str = "internal_appeal"
    tasks: list[dict] = field(default_factory=list)
    correspondence: list[dict] = field(default_factory=list)
    outbox: list[dict] = field(default_factory=list)
    deadlines: list[dict] = field(default_factory=list)
    processed_message_ids: list[str] = field(default_factory=list)
    outcome: dict | None = None

    _lock = threading.RLock()

    @property
    def dir(self) -> Path:
        return CASEFILES_DIR / self.case_id

    @property
    def events_path(self) -> Path:
        return self.dir / "events.jsonl"

    # ---- persistence ------------------------------------------------------
    def save(self) -> None:
        with self._lock:
            atomic_write_json(self.dir / "case.json", asdict(self))

    @classmethod
    def load(cls, case_id: str) -> "Case":
        data = json.loads((CASEFILES_DIR / case_id / "case.json").read_text(encoding="utf-8"))
        return cls(**data)

    @classmethod
    def exists(cls, case_id: str) -> bool:
        return (CASEFILES_DIR / case_id / "case.json").exists()

    # ---- timeline -----------------------------------------------------------
    def emit(self, agent: str, kind: str, message: str, **data) -> None:
        _emit(agent, kind, message, _path=self.events_path, case=self.case_id, **data)

    def set_status(self, status: str, why: str) -> None:
        assert status in STATUSES, status
        if status != self.status:
            old, self.status = self.status, status
            self.emit("case_worker", "info", f"status: {old} → {status} · {why}", status=status)

    # ---- tasks ----------------------------------------------------------------
    def add_task(self, kind: str, title: str, owner: str = "user", **details) -> dict:
        task = {"id": f"T{len(self.tasks) + 1}", "kind": kind, "title": title, "owner": owner,
                "status": "open", "created": _now(), **details}
        self.tasks.append(task)
        self.emit("case_worker", "warn" if owner == "user" else "info", f"task {task['id']} for {owner}: {title}",
                  task=task["id"], owner=owner, waiting_for_user=owner == "user")
        return task

    def complete_task(self, task_id: str, note: str = "") -> None:
        for t in self.tasks:
            if t["id"] == task_id and t["status"] == "open":
                t["status"], t["completed"] = "done", _now()
                self.emit("case_worker", "done", f"task {task_id} done{': ' + note if note else ''}", task=task_id)

    def open_tasks(self, owner: str | None = None) -> list[dict]:
        return [t for t in self.tasks if t["status"] == "open" and (owner is None or t["owner"] == owner)]


def all_cases() -> list[Case]:
    if not CASEFILES_DIR.exists():
        return []
    out = []
    for d in CASEFILES_DIR.iterdir():
        if (d / "case.json").exists():
            try:
                out.append(Case.load(d.name))
            except (ValueError, TypeError):
                continue
    return sorted(out, key=lambda c: c.created, reverse=True)


def open_case(run_id: str, insurer_email: str | None = None) -> Case:
    """Turn a finished run into an open case with the first letter queued for approval."""
    state = RunState.load(run_id)
    if not state.is_done("package"):
        raise ValueError(f"run {run_id} has no finished appeal packet")
    facts = state.output("intake_facts")
    display = state.read_private("phi_map.json")["display"]
    rounds = sorted(int(k.split("_")[1]) for k in state.stages if k.startswith("draft_") and state.is_done(k))
    draft = state.output(f"draft_{rounds[-1]}")

    slug = re.sub(r"[^a-z0-9]+", "-", Path(state.case_dir).name.lower()).strip("-")[:20]
    case_id = f"{slug}-{secrets.token_hex(2)}"
    # Real mailbox without a second account: the simulated insurer is the ClaimBack inbox itself
    real_mail = bool(os.environ.get("CLAIMBACK_EMAIL_APP_PASSWORD")) and os.environ.get("CLAIMBACK_FAKE_MAIL") != "1"
    insurer = (insurer_email or os.environ.get("INSURER_SIM_EMAIL")
               or (mailbox_address() if real_mail else "appeals@evergreen-mutual.example"))
    case = Case(
        case_id=case_id, run_id=run_id, case_name=Path(state.case_dir).name,
        reply_address=case_address(case_id), insurer_addresses=[insurer.lower()],
        claim_number=redact.rehydrate(facts["request_or_claim_number"], display),
        insurer_name=facts["insurer_name"],
    )
    # Real identifiers go back in locally; this draft only leaves the machine after Approve & send
    body = redact.rehydrate(draft["letter_markdown"], display)
    case.dir.mkdir(parents=True, exist_ok=True)
    (case.dir / "outbox").mkdir(exist_ok=True)
    (case.dir / "outbox" / "O1.md").write_text(body, encoding="utf-8")
    case.outbox.append({"id": "O1", "kind": "initial_appeal", "to": insurer.lower(),
                        "subject": f"Internal appeal: {case.claim_number}",
                        "body_file": "outbox/O1.md", "status": "awaiting_approval", "created": _now()})
    packet = RUNS_DIR / run_id / "output" / "appeal_packet.html"
    case.emit("case_worker", "start", f"case opened from run {run_id} · replies go to {case.reply_address}",
              run=run_id, packet=str(packet) if packet.exists() else None)
    case.add_task("approve_send", "Review the appeal letter, then Approve & send it to the insurer",
                  outbox_id="O1")
    case.set_status("awaiting_human", "the first letter needs your approval")
    case.save()
    return case
