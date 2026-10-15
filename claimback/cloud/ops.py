"""The actions a signed-in user can ask for, carried out on the worker. Every
action checks that the case or run belongs to the caller before touching it.
The Modal app (deploy/modal_app.py) decides where each one runs; these functions
work the same on a laptop for testing."""
import shutil
from pathlib import Path

from .. import llm, orchestrator
from ..cases import (CASEFILES_DIR, ActionRefused, Case, add_upload, all_cases, approve_outbox, confirm_outcome,
                     open_case, update_outbox)
from ..export import ExportRefused, _check_synthetic
from ..state import RUNS_DIR
from . import bridge

ROOT = RUNS_DIR.parent
SAMPLES_DIR = ROOT / "cases"
INPUTS_DIR = ROOT / "inputs"  # uploaded case documents, one folder per run
SAMPLES = {"cgm-denial": "Continuous glucose monitor denial (strong case)",
           "weak-cgm": "Continuous glucose monitor denial (weak case)",
           "mri-red-flag": "Lumbar MRI denial",
           "injection-cgm": "Denial letter with a prompt-injection attempt"}
DOC_NAMES = {"denial", "policy", "notes"}  # load_case files documents by these words in the name


class Refused(Exception):
    """Shown to the user as-is."""


def _set_mode(mode: str) -> None:
    llm.MOCK = mode == "mock"  # read at call time, so one warm worker can serve both modes
    orchestrator.CHAOS = False


def _own_case(owner: str, case_id: str) -> Case:
    if not Case.exists(case_id) or bridge.case_meta(case_id).get("owner") != owner:
        raise Refused("no such case")
    return Case.load(case_id)


# ---- runs ---------------------------------------------------------------------------
def prepare_run(owner: str, run_id: str, mode: str, sample: str | None, files: dict[str, bytes]) -> Path:
    """Put the case documents in place and check they are synthetic. Returns the case folder."""
    if sample:
        if sample not in SAMPLES:
            raise Refused("unknown sample case")
        case_dir = INPUTS_DIR / run_id / sample
        shutil.copytree(SAMPLES_DIR / sample, case_dir)
    else:
        if not files:
            raise Refused("upload at least a denial letter")
        case_dir = INPUTS_DIR / run_id / "uploaded-case"
        case_dir.mkdir(parents=True)
        for name, data in files.items():
            safe = "".join(ch for ch in Path(name).name if ch.isalnum() or ch in "._-")[:60]
            if not safe.lower().endswith(".txt"):
                raise Refused(f"{name}: only .txt documents are accepted in the hosted demo")
            (case_dir / safe).write_bytes(data)
        if not any("denial" in p.stem.lower() for p in case_dir.glob("*.txt")):
            raise Refused("one file must have 'denial' in its name (the denial letter)")
    try:
        _check_synthetic(case_dir)  # hosted demo: synthetic documents only, never real PHI
    except ExportRefused as e:
        shutil.rmtree(INPUTS_DIR / run_id, ignore_errors=True)
        raise Refused(str(e).replace("refusing to publish", "the hosted demo accepts synthetic test documents only"))
    bridge.write_meta(run_id, owner, mode)
    return case_dir


def run_pipeline(run_id: str, case_dir: Path, mode: str) -> bool:
    """The full agent team on one case. Checkpointed, so a retry resumes."""
    _set_mode(mode)
    try:
        if (RUNS_DIR / run_id / "state.json").exists():
            orchestrator.orchestrate(None, run_id=run_id)
        else:
            orchestrator.orchestrate(case_dir, new_run_id=run_id)
        return True
    except (orchestrator.StageFailed, llm.FatalError, SystemExit):
        return False
    finally:
        bridge.flush()


def open_case_for_run(run_id: str) -> str | None:
    """Turn a finished run into a long-lived case (first letter queued for approval)."""
    if any(c.run_id == run_id for c in all_cases()):
        return None
    case = open_case(run_id)
    bridge.flush()
    return case.case_id


# ---- case actions ----------------------------------------------------------------------
def approve(owner: str, case_id: str, outbox_id: str) -> str:
    _own_case(owner, case_id)
    return approve_outbox(case_id, outbox_id)


def edit(owner: str, case_id: str, outbox_id: str, body: str) -> dict:
    _own_case(owner, case_id)
    return update_outbox(case_id, outbox_id, body)


def confirm(owner: str, case_id: str, task_id: str) -> None:
    _own_case(owner, case_id)
    confirm_outcome(case_id, task_id)


def upload(owner: str, case_id: str, task_id: str, filename: str, data: bytes) -> dict:
    _own_case(owner, case_id)
    return add_upload(case_id, task_id, filename, data)


def simulate(owner: str, case_id: str, scene: str) -> None:
    from ..insurer_sim import send_scene
    case = _own_case(owner, case_id)
    if case.status == "closed":
        raise Refused("this case is closed")
    send_scene(case_id, scene)


def advance(case_ids: list[str] | None = None) -> int:
    """Check the mailbox, then let the agents read new mail and draft replies."""
    from ..connectors import get_connector
    from ..correspondence import process_pending
    from ..followup import process_followups
    from ..worker import check_mailbox
    check_mailbox(get_connector())
    n = 0
    for case in all_cases():
        if case.status == "closed" or (case_ids and case.case_id not in case_ids):
            continue
        meta = bridge.case_meta(case.case_id)
        if not meta.get("owner"):
            continue
        _set_mode(meta.get("mode", "mock"))
        if any(c["direction"] == "in" and c["status"] == "received" for c in case.correspondence):
            n += process_pending(case)
            case = Case.load(case.case_id)
        if case.pending_followups:
            n += process_followups(case)
    bridge.flush()
    return n


def purge(owner: str) -> int:
    """Delete everything this user has on the worker. The database rows go with the account."""
    n = 0
    for case in all_cases():
        if bridge.case_meta(case.case_id).get("owner") == owner:
            shutil.rmtree(CASEFILES_DIR / case.case_id, ignore_errors=True)
            n += 1
    if RUNS_DIR.exists():
        for d in RUNS_DIR.iterdir():
            if bridge.run_meta(d.name).get("owner") == owner:
                shutil.rmtree(d, ignore_errors=True)
                shutil.rmtree(INPUTS_DIR / d.name, ignore_errors=True)
                n += 1
    return n


__all__ = ["ActionRefused", "Refused", "SAMPLES", "prepare_run", "run_pipeline", "open_case_for_run",
           "approve", "confirm", "upload", "simulate", "advance", "purge"]
