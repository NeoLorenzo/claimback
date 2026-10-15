"""ClaimBack CLI.

  python -m claimback run cases/cgm-denial            # new run
  python -m claimback run cases/cgm-denial --chaos    # inject failures to show recovery
  python -m claimback run cases/cgm-denial --stop-after policy   # simulate a crash
  python -m claimback resume <run_id>                 # continue from the last checkpoint
  python -m claimback purge <run_id>                  # delete a run and its identifier map
  python -m claimback serve                           # live agent timeline + replay at http://127.0.0.1:8765
  python -m claimback export-site <run_id> [...]      # static replay site in docs/ (GitHub Pages)
"""
import argparse
import os
import shutil
import sys
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(prog="claimback")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="start a new run on a case folder")
    r.add_argument("case_dir", type=Path)
    r.add_argument("--chaos", action="store_true", help="inject failures on first attempts (demo)")
    r.add_argument("--stop-after", help="stop the run after this stage (simulates a crash)")
    r.add_argument("--offline", action="store_true", help="skip web search; use the case's reference library")
    r.add_argument("--mock", action="store_true", help="no API calls; canned agent outputs (for testing)")
    r.add_argument("--run-id", help="id for the new run (default: <case>-<timestamp>)")
    s = sub.add_parser("resume", help="resume a run from its last checkpoint")
    s.add_argument("run_id")
    s.add_argument("--mock", action="store_true")
    s.add_argument("--offline", action="store_true")
    d = sub.add_parser("purge", help="delete a run directory, including the local identifier map")
    d.add_argument("run_id")
    v = sub.add_parser("serve", help="web view: live agent timeline and replay")
    v.add_argument("--port", type=int, default=8765)
    x = sub.add_parser("export-site", help="export finished synthetic runs as a static replay site")
    x.add_argument("run_ids", nargs="+")
    x.add_argument("--out", type=Path, default=Path(__file__).resolve().parent.parent / "docs")
    args = p.parse_args()

    if args.cmd == "export-site":
        from .export import ExportRefused, export_site
        try:
            out = export_site(args.run_ids, args.out)
        except ExportRefused as e:
            print(f"export refused: {e}")
            return 1
        print(f"exported {len(args.run_ids)} run(s) to {out}")
        return 0

    if args.cmd == "serve":
        from .server import serve
        serve(args.port)
        return 0

    # Set before importing modules that read these flags
    if getattr(args, "mock", False):
        os.environ["CLAIMBACK_MOCK"] = "1"
    if getattr(args, "chaos", False):
        os.environ["CLAIMBACK_CHAOS"] = "1"

    from .llm import FatalError
    from .orchestrator import StageFailed, StopRequested, orchestrate
    from .state import RUNS_DIR

    if args.cmd == "purge":
        target = RUNS_DIR / args.run_id
        if not target.is_dir():
            print(f"no such run: {args.run_id}")
            return 1
        shutil.rmtree(target)
        print(f"deleted {target}")
        return 0

    try:
        if args.cmd == "run":
            orchestrate(args.case_dir, stop_after=args.stop_after, offline=args.offline,
                        new_run_id=args.run_id)
        else:
            orchestrate(None, run_id=args.run_id, offline=args.offline)
    except StopRequested as e:
        print(f"\n[stopped after stage '{e}'. Run `python -m claimback resume <run_id>` to continue]")
        return 2
    except KeyboardInterrupt:
        print("\n[interrupted. Progress is checkpointed; continue with `python -m claimback resume <run_id>`]")
        return 130
    except FatalError as e:
        print(f"\n[run stopped: {e}]")
        if "workspace" in str(e):
            print("Fix: add ANTHROPIC_WORKSPACE_ID=wrkspc_... to .env, or create an API key inside a workspace.")
        return 1
    except StageFailed as e:
        print(f"\n[run failed at stage '{e}'. Fix the cause, then resume]")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
