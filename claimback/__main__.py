"""ClaimBack CLI.

  python -m claimback run cases/cgm-denial            # new run
  python -m claimback run cases/cgm-denial --chaos    # inject failures to show recovery
  python -m claimback run cases/cgm-denial --stop-after policy   # simulate a crash
  python -m claimback resume <run_id>                 # continue from the last checkpoint
  python -m claimback purge <run_id>                  # delete a run and its identifier map
  python -m claimback serve                           # live agent timeline + replay at http://127.0.0.1:8765
  python -m claimback export-site <run_id> [...]      # static replay site in docs/ (GitHub Pages)
  python -m claimback open-case <run_id>              # open a long-lived case from a finished run
  python -m claimback watch                           # case worker: watch the mailbox, move cases forward
  python -m claimback simulate-insurer <case> <scene> # scripted insurer email (ack, evidence-request, overturned, upheld)
  python -m claimback cases                           # list cases
  python -m claimback upload <case> <task> <file>     # supply a document the insurer asked for
  python -m claimback approve <case> <outbox_id>      # Approve & send a reviewed draft
  python -m claimback confirm <case> <task>           # confirm the insurer's decision and close the case
  (add --fake to any case command to use the local fake mailbox instead of Gmail)
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
    oc = sub.add_parser("open-case", help="open a case from a finished run")
    oc.add_argument("run_id")
    oc.add_argument("--insurer-email", help="insurer address for this case (the send allow-list)")
    w = sub.add_parser("watch", help="case worker: watch the mailbox and move cases forward")
    w.add_argument("--interval", type=int, default=20)
    w.add_argument("--once", action="store_true", help="check once and exit")
    si = sub.add_parser("simulate-insurer", help="send a scripted, clearly simulated insurer email")
    si.add_argument("case_id")
    si.add_argument("scene", choices=["ack", "evidence-request", "overturned", "upheld"])
    sub.add_parser("cases", help="list cases")
    up = sub.add_parser("upload", help="supply a document the insurer asked for")
    up.add_argument("case_id"); up.add_argument("task_id"); up.add_argument("file", type=Path)
    ap = sub.add_parser("approve", help="Approve & send a reviewed draft")
    ap.add_argument("case_id"); ap.add_argument("outbox_id")
    cf = sub.add_parser("confirm", help="confirm the insurer's decision and close the case")
    cf.add_argument("case_id"); cf.add_argument("task_id")
    for sp in (oc, w, si, ap, up, cf):
        sp.add_argument("--fake", action="store_true", help="use the local fake mailbox")
    args = p.parse_args()

    if getattr(args, "fake", False):
        os.environ["CLAIMBACK_FAKE_MAIL"] = "1"
    if args.cmd in ("open-case", "watch", "simulate-insurer", "cases", "upload", "approve", "confirm"):
        from . import llm  # noqa: F401  loads .env (mail credentials)
        from .cases import ActionRefused, add_upload, all_cases, approve_outbox, confirm_outcome, open_case
        try:
            if args.cmd == "upload":
                u = add_upload(args.case_id, args.task_id, args.file.name, args.file.read_bytes())
                print(f"uploaded {u['id']} for {args.task_id}")
                return 0
            if args.cmd == "approve":
                print(f"sent: {approve_outbox(args.case_id, args.outbox_id)}")
                return 0
            if args.cmd == "confirm":
                confirm_outcome(args.case_id, args.task_id)
                print(f"case {args.case_id} closed")
                return 0
        except ActionRefused as e:
            print(f"refused: {e}")
            return 1
        if args.cmd == "open-case":
            case = open_case(args.run_id, args.insurer_email)
            print(f"opened case {case.case_id} · replies to {case.reply_address} · insurer {case.insurer_addresses[0]}")
        elif args.cmd == "watch":
            from .worker import watch
            try:
                watch(args.interval, args.once)
            except KeyboardInterrupt:
                print("\n[case worker stopped; all case progress is saved]")
        elif args.cmd == "simulate-insurer":
            from .cases import Case
            from .insurer_sim import send_scene
            case = Case.load(args.case_id)
            with case.log_context():  # the simulator's own line goes on the case timeline too
                case.emit("insurer_sim", "start", f"scripted insurer scene '{args.scene}' · SIMULATED: ClaimBack's test "
                                                  "harness plays the insurer for this demo", type="simulated_scene",
                          scene=args.scene, simulated=True)
                send_scene(args.case_id, args.scene)
        else:
            for c in all_cases():
                waiting = [t["title"] for t in c.open_tasks("user")]
                print(f"{c.case_id:28} {c.status:17} {len(c.correspondence)} msg  {waiting[0] if waiting else ''}")
        return 0

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
