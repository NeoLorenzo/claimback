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
from .log import DIM, RESET, emit as _emit
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
    uploads: list[dict] = field(default_factory=list)
    pending_followups: list[str] = field(default_factory=list)  # insurer messages whose evidence is complete, reply not drafted yet

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
        # The console shows which case each line belongs to; the timeline file is already per case
        _emit(agent, kind, message, _path=self.events_path, _console_prefix=f"{DIM}[{self.case_id}]{RESET} ",
              case=self.case_id, **data)

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

    def complete_task_kind(self, kind: str, note: str = "") -> None:
        for t in self.tasks:
            if t["kind"] == kind and t["status"] == "open":
                self.complete_task(t["id"], note)

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
    from .letters import split_reviewer_notes
    body, notes = split_reviewer_notes(redact.rehydrate(draft["letter_markdown"], display))
    notes += [redact.rehydrate(n, display) for n in draft.get("reviewer_notes", [])]
    case.dir.mkdir(parents=True, exist_ok=True)
    (case.dir / "outbox").mkdir(exist_ok=True)
    (case.dir / "outbox" / "O1.md").write_text(body, encoding="utf-8")
    case.outbox.append({"id": "O1", "kind": "initial_appeal", "to": insurer.lower(),
                        "subject": f"Internal appeal: {case.claim_number}", "reviewer_notes": notes,
                        "body_file": "outbox/O1.md", "status": "awaiting_approval", "created": _now()})
    packet = RUNS_DIR / run_id / "output" / "appeal_packet.html"
    case.emit("case_worker", "start", f"case opened from run {run_id} · replies go to {case.reply_address}",
              run=run_id, packet=str(packet) if packet.exists() else None)
    case.add_task("approve_send", "Review the appeal letter, then Approve & send it to the insurer",
                  outbox_id="O1")
    case.set_status("awaiting_human", "the first letter needs your approval")
    case.save()
    return case


# ---- human actions (called from the web view and the CLI) ----------------------
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_UPLOADS = {".pdf", ".txt", ".md"}


class ActionRefused(Exception):
    """A human action that ClaimBack won't perform (wrong state, recipient not allowed, ...)."""


def add_upload(case_id: str, task_id: str, filename: str, data: bytes) -> dict:
    """Attach a document the insurer asked for. When every item from that request
    is in, the case worker drafts the reply."""
    case = Case.load(case_id)
    task = next((t for t in case.tasks if t["id"] == task_id), None)
    if not task or task["kind"] != "upload_evidence" or task["status"] != "open":
        raise ActionRefused(f"{task_id} is not an open evidence task on {case_id}")
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_UPLOADS:
        raise ActionRefused(f"{suffix or 'this file type'} isn't accepted; upload a PDF or text file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ActionRefused("file is larger than 10 MB")
    safe = "".join(ch for ch in Path(filename).name if ch.isalnum() or ch in "._-")[:80] or f"upload{suffix}"
    uid = f"U{len(case.uploads) + 1}"
    (case.dir / "uploads").mkdir(parents=True, exist_ok=True)
    (case.dir / "uploads" / f"{uid}_{safe}").write_bytes(data)
    upload = {"id": uid, "task": task_id, "file": f"uploads/{uid}_{safe}", "name": safe,
              "bytes": len(data), "correspondence": task.get("correspondence"), "created": _now()}
    case.uploads.append(upload)
    case.emit("case_worker", "info", f"upload {uid} for {task_id}: {safe} ({len(data) // 1024 or 1} KB)", upload=uid)
    case.complete_task(task_id, f"provided as {uid}")
    source = task.get("correspondence")
    still_open = [t for t in case.open_tasks() if t["kind"] == "upload_evidence" and t.get("correspondence") == source]
    if not still_open and source and source not in case.pending_followups:
        case.pending_followups.append(source)
        case.set_status("action_required", f"everything requested in {source} is in; drafting the reply")
    case.save()
    return upload


def approve_outbox(case_id: str, outbox_id: str) -> str:
    """Send one reviewed draft. The human's click is the approval; the recipient
    must be on the case's insurer allow-list. Returns the sent Message-ID."""
    import email.utils

    from .connectors import OutboundEmail, get_connector
    case = Case.load(case_id)
    item = next((o for o in case.outbox if o["id"] == outbox_id), None)
    if not item:
        raise ActionRefused(f"no draft {outbox_id} on {case_id}")
    if item["status"] == "sending":
        raise ActionRefused(f"{outbox_id} may already have been sent (interrupted mid-send); check the Sent folder")
    if item["status"] != "awaiting_approval":
        raise ActionRefused(f"{outbox_id} is {item['status']}, not awaiting approval")
    if item["to"].lower() not in case.insurer_addresses:
        case.emit("case_worker", "error", f"refused to send {outbox_id}: {item['to']} is not on this case's "
                                           "insurer list", outbox=outbox_id)
        raise ActionRefused(f"{item['to']} is not an allowed recipient for this case")

    from .letters import fill_send_time, to_html, to_plain, unresolved_blanks
    body = fill_send_time((case.dir / item["body_file"]).read_text(encoding="utf-8"))
    blanks = unresolved_blanks(body)
    if blanks:
        raise ActionRefused("fill in these blanks before sending (use Edit): " + "; ".join(blanks))
    attachments = []
    for uid in item.get("attachments", []):
        up = next(u for u in case.uploads if u["id"] == uid)
        mime = "application/pdf" if up["name"].lower().endswith(".pdf") else "text/plain"
        attachments.append((up["name"], (case.dir / up["file"]).read_bytes(), mime))
    # Record the Message-ID before sending, so an interrupted send can't silently go out twice
    item["message_id"] = email.utils.make_msgid(domain="claimback.local")
    item["status"] = "sending"
    case.save()
    connector = get_connector()
    sent_id = connector.send(OutboundEmail(
        from_addr=f"ClaimBack appeal <{mailbox_address()}>", to=item["to"], subject=item["subject"],
        body=to_plain(body), html=to_html(body),
        reply_to=case.reply_address, in_reply_to=item.get("in_reply_to"), attachments=attachments,
        message_id=item["message_id"]))
    item["status"], item["sent"] = "sent", _now()
    case.correspondence.append({"id": f"S{sum(c['direction'] == 'out' for c in case.correspondence) + 1}",
                                "direction": "out", "message_id": sent_id, "from": mailbox_address(),
                                "to": item["to"], "subject": item["subject"], "date": item["sent"],
                                "simulated": False, "trusted_sender": True, "outbox": outbox_id,
                                "attachments": item.get("attachments", []), "status": "sent"})
    case.emit("connector", "done", f"sent {outbox_id} to {item['to']} via {connector.name} "
                                   f"(approved by you) · replies come back to {case.reply_address}",
              outbox=outbox_id, direction="out")
    for t in case.open_tasks():
        if t["kind"] == "approve_send" and t.get("outbox_id") == outbox_id:
            case.complete_task(t["id"], "approved and sent")
    if not case.open_tasks("user"):
        case.set_status("awaiting_insurer", f"{outbox_id} sent; waiting for the insurer")
    case.save()
    return sent_id


def update_outbox(case_id: str, outbox_id: str, body: str) -> dict:
    """The human edits a draft before approving it (fill in blanks, change wording)."""
    case = Case.load(case_id)
    item = next((o for o in case.outbox if o["id"] == outbox_id), None)
    if not item or item["status"] != "awaiting_approval":
        raise ActionRefused(f"{outbox_id} isn't a draft awaiting approval")
    if not body.strip() or len(body) > 100_000:
        raise ActionRefused("the draft can't be empty or longer than 100,000 characters")
    (case.dir / item["body_file"]).write_text(body.rstrip() + "\n", encoding="utf-8")
    item["edited"] = _now()
    from .letters import unresolved_blanks
    left = unresolved_blanks(body)
    case.emit("case_worker", "info", f"draft {outbox_id} edited by you"
              + (f" · {len(left)} blank(s) still to fill" if left else " · ready to send"), outbox=outbox_id)
    case.save()
    return {"blanks": left}


def confirm_outcome(case_id: str, task_id: str) -> None:
    """A human confirms the insurer's decision; only then does the case close."""
    case = Case.load(case_id)
    task = next((t for t in case.tasks if t["id"] == task_id), None)
    if not task or task["kind"] != "confirm_outcome" or task["status"] != "open":
        raise ActionRefused(f"{task_id} is not an open confirm-outcome task on {case_id}")
    source = next((c for c in case.correspondence if c["id"] == task.get("correspondence")), {})
    decision = (source.get("analysis") or {}).get("decision") or {}
    case.outcome = {"result": decision.get("outcome", "confirmed"), "quote": decision.get("quote", task.get("quote")),
                    "source": task.get("correspondence"), "confirmed_by": "user", "confirmed": _now()}
    case.complete_task(task_id, "outcome confirmed by you")
    for t in case.open_tasks():  # anything still open is moot once the outcome is decided
        t["status"], t["completed"] = "withdrawn", _now()
        case.emit("case_worker", "info", f"task {t['id']} withdrawn: the case has an outcome", task=t["id"])
    case.set_status("closed", f"outcome confirmed: {case.outcome['result']}")
    case.emit("case_worker", "done", f"case closed · outcome: {case.outcome['result']} (confirmed by you)",
              outcome=case.outcome["result"])
    case.save()
