"""ClaimBack's hosted worker on Modal.

  api         HTTPS endpoint the web app calls (checks the Supabase session, applies
              quotas, records a job, hands it to a worker function)
  start_run   one agent-team run per call (5-10 min), checkpointed on a Volume
  case_ops    every change to a case, one at a time (max_containers=1), so two
              actions never write the same case.json at once
  poll        cron: checks the case mailbox and lets agents read new insurer mail

Deploy:  python -m modal deploy deploy/modal_app.py
Secrets: Modal secret "claimback" with ANTHROPIC_API_KEY, SUPABASE_URL,
         SUPABASE_SECRET_KEY, SUPABASE_PUBLISHABLE_KEY (optional:
         ANTHROPIC_WORKSPACE_ID, CLAIMBACK_EMAIL, CLAIMBACK_EMAIL_APP_PASSWORD,
         LIVE_RUNS_PER_USER, LIVE_RUNS_PER_DAY)."""
import os
import secrets as _secrets
from datetime import datetime, timezone
from pathlib import Path

import modal

REPO = Path(__file__).resolve().parent.parent

app = modal.App("claimback")
volume = modal.Volume.from_name("claimback-data", create_if_missing=True)
secret = modal.Secret.from_name("claimback")
image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("anthropic>=1.14", "pydantic>=2", "markdown>=3.5", "pypdf>=4", "httpx", "fastapi[standard]")
    .add_local_dir(REPO / "cases", "/root/cases")
    .add_local_python_source("claimback")
)
DATA = Path("/data")
WORKER = dict(image=image, volumes={str(DATA): volume}, secrets=[secret])


def _setup() -> None:
    """Point the repo's runs/, casefiles/ and inputs/ folders at the persistent Volume."""
    for name in ("runs", "casefiles", "inputs"):
        (DATA / name).mkdir(parents=True, exist_ok=True)
        link = Path("/root") / name
        if not link.exists():
            link.symlink_to(DATA / name)
    from claimback.cloud import bridge
    bridge.install()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job(job_id: int | None, **values) -> None:
    if job_id is None:
        return
    from claimback.cloud.supa import Supabase
    Supabase().update("jobs", {"id": job_id}, {**values, "updated_at": _now()})


# ---- the agent team ------------------------------------------------------------------
@app.function(**WORKER, timeout=60 * 60, retries=modal.Retries(max_retries=1, initial_delay=5.0))
def start_run(job_id: int, owner: str, run_id: str, mode: str, sample: str | None, uploads: list[str]) -> None:
    _setup()
    from claimback.cloud import ops
    from claimback.cloud.supa import Supabase
    sb = Supabase()
    _job(job_id, status="running", result={"run_id": run_id})
    case_dir = next(iter((ops.INPUTS_DIR / run_id).glob("*")), None)
    if case_dir is None:  # first attempt (a retry finds the documents already in place)
        files = {}
        for path in uploads:
            if not path.startswith(f"{owner}/"):
                _job(job_id, status="failed", error="upload belongs to someone else")
                return
            files[path.rsplit("/", 1)[-1]] = sb.download("uploads", path)
        try:
            case_dir = ops.prepare_run(owner, run_id, mode, sample, files)
        except ops.Refused as e:
            _job(job_id, status="failed", error=str(e))
            return
        volume.commit()
    ok = ops.run_pipeline(run_id, case_dir, mode)
    volume.commit()
    if not ok:
        _job(job_id, status="failed", error="the run stopped; see its timeline")
        return
    case_id = case_ops.remote("open_case", owner, {"run_id": run_id}, None)
    _job(job_id, status="done", result={"run_id": run_id, "case_id": case_id})


# ---- case changes, strictly one at a time ------------------------------------------------
@app.function(**WORKER, timeout=20 * 60, max_containers=1)
def case_ops(kind: str, owner: str | None, args: dict, job_id: int | None):
    import time
    _setup()
    volume.reload()
    from claimback.cloud import ops
    from claimback.cloud.supa import Supabase
    _job(job_id, status="running")
    result = None
    try:
        if kind == "open_case":
            result = ops.open_case_for_run(args["run_id"])
        elif kind == "approve":
            result = {"message_id": ops.approve(owner, args["case_id"], args["outbox_id"])}
            from claimback.cases import Case
            letter = next((o for o in Case.load(args["case_id"]).outbox if o["id"] == args["outbox_id"]), {})
            if os.environ.get("SCRIPTED_INSURER", "1") == "1" and letter.get("kind") in INSURER_SCRIPT:
                # Report the send as done first, then play the insurer's replies in this same warm
                # container: no extra cold starts, and still serialized with everything else.
                volume.commit()
                _job(job_id, status="done", result=result)
                job_id = None
                for wait, scene in INSURER_SCRIPT[letter["kind"]]:
                    time.sleep(wait)
                    ops.simulate(owner, args["case_id"], scene, direct=True)
                    volume.commit()
        elif kind == "confirm":
            ops.confirm(owner, args["case_id"], args["task_id"])
        elif kind == "edit":
            result = ops.edit(owner, args["case_id"], args["outbox_id"], args["body"])
        elif kind == "upload":
            path = args["path"]
            if not path.startswith(f"{owner}/"):
                raise ops.Refused("upload belongs to someone else")
            data = Supabase().download("uploads", path)
            import re
            name = re.sub(r"^\d{10,}-", "", path.rsplit("/", 1)[-1])  # drop the storage timestamp prefix
            result = ops.upload(owner, args["case_id"], args["task_id"], name, data)
            volume.commit()
            _job(job_id, status="running", result={"note": "drafting the reply"})
            ops.read_now(args["case_id"])  # the upload is already here: no mailbox check needed
        elif kind == "simulate" and args.get("direct"):
            ops.simulate(owner, args["case_id"], args["scene"], direct=True)
        elif kind == "simulate":
            ops.simulate(owner, args["case_id"], args["scene"])
            volume.commit()
            for _ in range(6):  # real mail takes a few seconds to arrive
                if ops.advance([args["case_id"]]):
                    break
                time.sleep(5)
        elif kind == "advance":
            result = {"handled": ops.advance()}
        elif kind == "purge":
            result = {"deleted": ops.purge(owner)}
        else:
            raise ops.Refused(f"unknown action {kind}")
    except (ops.Refused, ops.ActionRefused) as e:
        volume.commit()
        _job(job_id, status="failed", error=str(e))
        return None
    except Exception as e:
        volume.commit()
        _job(job_id, status="failed", error=f"{type(e).__name__}: {str(e)[:300]}")
        raise
    volume.commit()
    _job(job_id, status="done", result=result if isinstance(result, dict) else {"value": result})
    return result


# ---- scripted insurer for the demo --------------------------------------------------------
# What the simulated insurer does after each kind of letter is sent: (wait in seconds, scene).
# Every message it sends is marked as simulated; it goes through case_ops, so it's serialized
# with everything else that touches the case.
INSURER_SCRIPT = {
    "initial_appeal": [(1, "ack"), (1, "evidence-request")],
    "evidence_response": [(1, "overturned")],
}


@app.function(**WORKER, schedule=modal.Cron("*/2 * * * *"), timeout=15 * 60)
def poll() -> None:
    """Safety net for insurer mail that arrives on its own schedule."""
    from claimback.cloud.supa import Supabase
    Supabase().insert("worker_heartbeat", {"id": "case-worker", "at": _now()}, upsert=True)
    case_ops.remote("advance", None, {}, None)


# ---- HTTPS API for the web app ------------------------------------------------------------
@app.function(image=image, secrets=[secret], timeout=60)
@modal.concurrent(max_inputs=50)
@modal.asgi_app()
def api():
    from fastapi import FastAPI, Header, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel

    from claimback.cloud.ops import SAMPLES
    from claimback.cloud.supa import Supabase

    sb = Supabase()
    web = FastAPI(title="ClaimBack worker API")
    origins = os.environ.get("ALLOWED_ORIGINS", "https://neolorenzo.github.io,http://localhost:8000,"
                                                "http://127.0.0.1:8000").split(",")
    web.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"],
                       allow_headers=["Authorization", "Content-Type"])
    per_user = int(os.environ.get("LIVE_RUNS_PER_USER", "2"))
    per_day = int(os.environ.get("LIVE_RUNS_PER_DAY", "20"))
    jobs_per_hour = int(os.environ.get("JOBS_PER_USER_PER_HOUR", "40"))

    def caller(authorization: str | None) -> dict:
        token = (authorization or "").removeprefix("Bearer ").strip()
        user = sb.user_for_token(token) if token else None
        if not user:
            raise HTTPException(401, "sign in first")
        return user

    def today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")

    def new_job(owner: str, kind: str, payload: dict) -> int:
        hour_ago = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() - 3600, timezone.utc).isoformat()
        if sb.count("jobs", {"owner": f"eq.{owner}", "created_at": f"gte.{hour_ago}"}) >= jobs_per_hour:
            raise HTTPException(429, "too many actions in the last hour; try again later")
        return sb.insert("jobs", {"owner": owner, "kind": kind, "payload": payload}, returning=True)[0]["id"]

    class RunRequest(BaseModel):
        mode: str = "mock"
        sample: str | None = None
        uploads: list[str] = []

    class CaseAction(BaseModel):
        outbox_id: str | None = None
        task_id: str | None = None
        path: str | None = None
        scene: str | None = None
        body: str | None = None

    @web.get("/health")
    def health():
        return {"ok": True}

    @web.get("/config")
    def config(authorization: str | None = Header(None)):
        user = caller(authorization)
        live_today = sb.count("jobs", {"owner": f"eq.{user['id']}", "kind": "eq.start_run",
                                       "payload->>mode": "eq.live", "created_at": f"gte.{today()}"})
        return {"samples": SAMPLES, "live_runs_left": max(0, per_user - live_today), "live_runs_per_user": per_user}

    @web.post("/runs")
    def create_run(req: RunRequest, authorization: str | None = Header(None)):
        user = caller(authorization)
        owner = user["id"]
        if req.mode not in ("mock", "live"):
            raise HTTPException(400, "mode must be mock or live")
        if not req.sample and not req.uploads:
            raise HTTPException(400, "pick a sample case or upload documents")
        if req.sample and req.sample not in SAMPLES:
            raise HTTPException(400, "unknown sample case")
        if any(not p.startswith(f"{owner}/") for p in req.uploads) or len(req.uploads) > 6:
            raise HTTPException(400, "invalid uploads")
        if req.mode == "live":
            mine = sb.count("jobs", {"owner": f"eq.{owner}", "kind": "eq.start_run", "payload->>mode": "eq.live",
                                     "created_at": f"gte.{today()}"})
            if mine >= per_user:
                raise HTTPException(429, f"you've used today's {per_user} live runs; mock runs are unlimited")
            everyone = sb.count("jobs", {"kind": "eq.start_run", "payload->>mode": "eq.live",
                                         "created_at": f"gte.{today()}"})
            if everyone >= per_day:
                raise HTTPException(429, "today's live-run budget for the demo is used up; mock runs still work")
        name = req.sample or "uploaded-case"
        run_id = f"{name}-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{_secrets.token_hex(2)}"
        job_id = new_job(owner, "start_run", {"mode": req.mode, "sample": req.sample, "uploads": req.uploads,
                                              "run_id": run_id})
        start_run.spawn(job_id, owner, run_id, req.mode, req.sample, req.uploads)
        return {"job_id": job_id, "run_id": run_id}

    @web.post("/cases/{case_id}/{action}")
    def case_action(case_id: str, action: str, req: CaseAction, authorization: str | None = Header(None)):
        user = caller(authorization)
        owner = user["id"]
        need = {"approve": "outbox_id", "confirm": "task_id", "upload": "task_id", "simulate": "scene", "edit": "body"}
        if action not in need or not getattr(req, need[action]):
            raise HTTPException(400, "unknown action or missing field")
        if action == "upload" and not (req.path or "").startswith(f"{owner}/"):
            raise HTTPException(400, "invalid upload")
        if action == "edit" and (not req.outbox_id or len(req.body or "") > 100_000):
            raise HTTPException(400, "edit needs outbox_id and a body under 100,000 characters")
        if action == "simulate" and req.scene not in ("ack", "evidence-request", "overturned", "upheld"):
            raise HTTPException(400, "unknown scene")
        rows = sb.select("cases", {"id": f"eq.{case_id}", "owner": f"eq.{owner}", "select": "id"})
        if not rows:
            raise HTTPException(404, "no such case")
        args = {"case_id": case_id, **req.model_dump(exclude_none=True)}
        job_id = new_job(owner, action, args)
        case_ops.spawn(action, owner, args, job_id)
        return {"job_id": job_id}

    @web.post("/me/purge")
    def purge(authorization: str | None = Header(None)):
        user = caller(authorization)
        job_id = new_job(user["id"], "purge", {})
        case_ops.spawn("purge", user["id"], {}, job_id)
        sb.delete("events", {"owner": user["id"]})
        sb.delete("cases", {"owner": user["id"]})
        sb.delete("runs", {"owner": user["id"]})
        sb.remove("uploads", sb.list("uploads", user["id"]))  # <owner>/<file>
        for folder in sb.list("packets", user["id"]):  # <owner>/<run_id>/<file>
            sb.remove("packets", sb.list("packets", folder))
        return {"job_id": job_id}

    return web
