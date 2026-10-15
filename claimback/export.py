"""Export recorded runs as a static site (GitHub Pages) for the replay view.

Only runs on synthetic cases can be exported: every case document must carry
the SYNTHETIC TEST DOCUMENT marker. Real patient data never leaves the machine."""
import json
import shutil
from pathlib import Path

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


def _scrub(text: str) -> str:
    """Drop local filesystem paths from log messages."""
    for prefix in (str(ROOT), str(ROOT).replace("\\", "/")):
        text = text.replace(prefix, "")
    return text


def export_site(run_ids: list[str], out: Path) -> Path:
    data = out / "data" / "runs"
    if (out / "data").exists():
        shutil.rmtree(out / "data")
    data.mkdir(parents=True)
    listing = []
    for run_id in run_ids:
        run_dir = RUNS_DIR / run_id
        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        case_dir = Path(state["case_dir"])
        _check_synthetic(case_dir)
        packet = run_dir / "output" / "appeal_packet.html"
        if not packet.exists():
            raise ExportRefused(f"{run_id} has no appeal packet; only finished runs can be exported")

        events = []
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines():
            e = json.loads(line)
            e["message"] = _scrub(e["message"])
            events.append(e)
        (data / run_id).mkdir()
        (data / run_id / "events.json").write_text(
            json.dumps({"status": state["status"], "events": events}), encoding="utf-8")
        shutil.copy(packet, data / run_id / "packet.html")
        listing.append({"id": run_id, "case": case_dir.name, "created": state["created"],
                        "status": state["status"], "has_packet": True})

    # Keep the command-line order: the first run is the one visitors see playing
    (out / "data" / "runs.json").write_text(json.dumps(listing, indent=2), encoding="utf-8")
    shutil.copy(INDEX, out / "index.html")
    (out / ".nojekyll").write_text("", encoding="utf-8")  # serve files as-is
    return out
