"""Export recorded runs as a static site (GitHub Pages) for the replay view.

Only runs on synthetic cases can be exported: every case document must carry
the SYNTHETIC TEST DOCUMENT marker. Real patient data never leaves the machine.
Each run is published with the case opened from it (insurer email, replies,
approvals, outcome), so the replay shows the whole lifecycle. As a last check,
the exported logs are scanned for every identifier in the run's and the case's
identifier maps; one hit and nothing is written."""
import json
import os
import re
import shutil
from pathlib import Path

from . import llm  # noqa: F401  loads .env (CLAIMBACK_EMAIL, so the export can mask it)
from .cases import CASEFILES_DIR
from .state import RUNS_DIR

ROOT = Path(__file__).resolve().parent.parent
INDEX = Path(__file__).resolve().parent / "web" / "index.html"
MARKER = "SYNTHETIC TEST DOCUMENT"


class ExportRefused(Exception):
    pass


def _check_synthetic(case_dir: Path) -> None:
    docs = list(case_dir.glob("*.txt"))
    if not docs:
        raise ExportRefused(f"no case documents found in {case_dir}")
    unmarked = [d.name for d in docs if MARKER not in d.read_text(encoding="utf-8")]
    if unmarked:
        raise ExportRefused(f"{case_dir.name}: {', '.join(unmarked)} not marked '{MARKER}'; refusing to publish")


def _scrubber():
    """Drop local filesystem paths and mask the ClaimBack mailbox's own address."""
    prefixes = {str(ROOT), str(ROOT).replace("\\", "/"), str(ROOT).replace("\\", "\\\\")}
    mailbox = os.environ.get("CLAIMBACK_EMAIL", "")
    local = mailbox.partition("@")[0]

    def scrub(value):
        if isinstance(value, str):
            for prefix in prefixes:
                value = value.replace(prefix, "")
            # Runs recorded in another checkout carry its path; drop anything local before runs/ or casefiles/
            value = re.sub(r"[A-Za-z]:[\\/]+(?:[^\\/\s\"]+[\\/]+)*?(?=(?:runs|casefiles)[\\/])", "", value)
            if local and local != "claimback.demo":
                value = re.sub(rf"\b{re.escape(local)}(?=[+@])", "claimback-inbox", value, flags=re.IGNORECASE)
            return value
        if isinstance(value, list):
            return [scrub(v) for v in value]
        if isinstance(value, dict):
            return {k: scrub(v) for k, v in value.items()}
        return value
    return scrub


def _identifiers(*maps: Path) -> dict[str, str]:
    """{identifier text: category} from identifier maps (run and case)."""
    found = {}
    for path in maps:
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for original, placeholder in data["redact"].items():
            found[original] = placeholder.strip("[]").rsplit("_", 1)[0]
        for placeholder, value in data["display"].items():
            found.setdefault(value, placeholder.strip("[]").rsplit("_", 1)[0])
    return {k: v for k, v in found.items() if len(k) >= 4}


def _check_no_identifiers(text: str, identifiers: dict[str, str], what: str) -> None:
    hits = sorted({cat for ident, cat in identifiers.items() if ident.casefold() in text.casefold()})
    if hits:  # name the categories only, never the values
        raise ExportRefused(f"{what}: exported log would contain identifiers ({', '.join(hits)}); refusing to publish")


def _case_for(run_id: str, case_id: str | None) -> Path | None:
    """The named case, or the newest closed case opened from the run (else the newest open one)."""
    if case_id:
        d = CASEFILES_DIR / case_id
        if not (d / "case.json").exists():
            raise ExportRefused(f"no case {case_id}")
        return d
    found = []
    for d in CASEFILES_DIR.glob("*/case.json") if CASEFILES_DIR.exists() else []:
        c = json.loads(d.read_text(encoding="utf-8"))
        if c.get("run_id") == run_id:
            found.append((c.get("status") == "closed", c.get("created", ""), d.parent))
    return max(found)[2] if found else None


def _events(path: Path, scrub) -> list[dict]:
    return [scrub(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def export_site(run_ids: list[str], out: Path) -> Path:
    """run_ids: 'run_id' (adds the run's newest case, if any) or 'run_id:case_id'."""
    scrub = _scrubber()
    staged = []
    for spec in run_ids:
        run_id, _, case_id = spec.partition(":")
        run_dir = RUNS_DIR / run_id
        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        case_dir = Path(state["case_dir"])
        _check_synthetic(case_dir)
        packet = run_dir / "output" / "appeal_packet.html"
        if not packet.exists():
            raise ExportRefused(f"{run_id} has no appeal packet; only finished runs can be exported")

        payload = {"status": state["status"], "events": _events(run_dir / "events.jsonl", scrub)}
        maps = [run_dir / "phi_map.json"]
        cdir = _case_for(run_id, case_id or None)
        if cdir:
            c = json.loads((cdir / "case.json").read_text(encoding="utf-8"))
            payload["case"] = {"id": c["case_id"], "status": c["status"],
                               "outcome": (c.get("outcome") or {}).get("result"),
                               "events": _events(cdir / "events.jsonl", scrub)}
            maps.append(cdir / "phi_map.json")
        text = json.dumps(payload)
        _check_no_identifiers(text, _identifiers(*maps), spec)
        staged.append((run_id, payload, text, packet,
                       {"id": run_id, "case": case_dir.name, "created": state["created"], "status": state["status"],
                        "has_packet": True, "case_id": payload.get("case", {}).get("id"),
                        "case_status": payload.get("case", {}).get("status"),
                        "outcome": payload.get("case", {}).get("outcome")}))

    # Every run passed its checks; only now replace the published data
    data = out / "data" / "runs"
    if (out / "data").exists():
        shutil.rmtree(out / "data")
    data.mkdir(parents=True)
    for run_id, _, text, packet, _ in staged:
        (data / run_id).mkdir()
        (data / run_id / "events.json").write_text(text, encoding="utf-8")
        shutil.copy(packet, data / run_id / "packet.html")
    # Keep the command-line order: the first run is the one visitors see playing
    (out / "data" / "runs.json").write_text(json.dumps([s[4] for s in staged], indent=2), encoding="utf-8")
    shutil.copy(INDEX, out / "index.html")
    (out / ".nojekyll").write_text("", encoding="utf-8")  # serve files as-is
    return out
