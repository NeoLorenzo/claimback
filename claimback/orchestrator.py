"""The Orchestrator: plans the run, hands artifacts between agents, retries
failures, runs independent agents in parallel, and checkpoints every stage so a
run can resume after a crash."""
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from . import agents, packager, redact
from .llm import AgentError, FatalError
from .log import emit, set_log_file
from .schemas import PHIScan
from .state import RunState

MAX_ROUNDS = 3  # writer <-> reviewer/fact-checker revision rounds
APPROVE_SCORE = 8

# Demo mode: make chosen stages fail on their first attempt to show recovery
CHAOS = os.environ.get("CLAIMBACK_CHAOS") == "1"
CHAOS_FAILS = {
    "policy": "simulated API timeout",
    "evidence_web": "simulated web search outage",
    "draft_1": "simulated malformed handoff (claim cites unknown source EV-99)",
}

DOC_IDS = [("denial", "DENIAL"), ("policy", "POLICY"), ("note", "NOTES")]
PLACEHOLDER_RE = re.compile(r"\[([A-Z_]+_\d+)\]")


class StageFailed(Exception):
    pass


class StopRequested(Exception):
    """Raised by --stop-after to simulate a crash mid-run."""


# ---- stage runner -----------------------------------------------------------
def run_stage(state: RunState, name: str, agent: str, fn, *, retries: int = 3,
              validate=None, stop_after: str | None = None):
    if state.is_done(name):
        emit(agent, "info", f"{name}: restored from checkpoint")
        return state.output(name)

    feedback = None
    for attempt in range(1, retries + 1):
        stage = state.begin(name)
        emit(agent, "start", f"{name} (attempt {attempt}/{retries})")
        try:
            if CHAOS and name in CHAOS_FAILS and stage.attempts == 1:
                raise AgentError(f"[chaos] {CHAOS_FAILS[name]}")
            out = fn(feedback)
            problem = validate(out) if validate else None
            if problem:
                feedback = problem  # validation problems go back to the agent
                raise AgentError(f"output rejected: {problem}")
            state.complete(name, out)
            emit(agent, "done", f"{name} complete")
            if stop_after == name:
                raise StopRequested(name)
            return out
        except FatalError as e:
            state.fail(name, str(e))
            emit(agent, "error", f"{name}: {e} · not retryable, stopping run")
            raise
        except (AgentError, Exception) as e:
            if isinstance(e, StopRequested):
                raise
            if not isinstance(e, AgentError):
                e = AgentError(f"unexpected {type(e).__name__}: {str(e)[:200]}")
            state.fail(name, str(e))
            if attempt < retries:
                wait = 2 ** attempt
                emit(agent, "retry", f"{name} failed: {e} · retrying in {wait}s")
                time.sleep(wait)
            else:
                emit(agent, "error", f"{name} failed after {retries} attempts: {e}")
    raise StageFailed(name)


# ---- case loading --------------------------------------------------------------
def load_case(case_dir: Path) -> tuple[dict[str, str], str]:
    docs: dict[str, str] = {}
    extra = 0
    for f in sorted(case_dir.glob("*.txt")):
        doc_id = next((i for key, i in DOC_IDS if key in f.stem.lower()), None)
        if doc_id is None or doc_id in docs:
            extra += 1
            doc_id = f"DOC-{extra}"
        docs[doc_id] = f.read_text(encoding="utf-8")
    if "DENIAL" not in docs:
        raise SystemExit(f"No denial letter found in {case_dir} (expected a file with 'denial' in its name)")
    library = "\n\n".join(p.read_text(encoding="utf-8") for p in sorted((case_dir / "references").glob("*.md"))) \
        if (case_dir / "references").exists() else ""
    return docs, library


# ---- validators -----------------------------------------------------------------
def validate_phi(out: dict) -> str | None:
    cats = {e["category"] for e in out["entities"]}
    if "PATIENT_NAME" not in cats:
        return "no PATIENT_NAME found; the denial letter is addressed to the patient, so look again"
    return None


def validate_facts(out: dict) -> str | None:
    try:
        datetime.strptime(out["denial_date"], "%Y-%m-%d")
    except ValueError:
        return f"denial_date '{out['denial_date']}' is not YYYY-MM-DD"
    if out["appeal_window_days"] <= 0:
        return "appeal_window_days must be a positive number of days"
    return None


def make_draft_validator(known_sources: set[str], placeholders: set[str]):
    def validate(out: dict) -> str | None:
        problems = []
        for c in out["claims"]:
            if not c["source_ids"]:
                problems.append(f"claim {c['claim_id']} has no source")
            unknown = [s for s in c["source_ids"] if s not in known_sources]
            if unknown:
                problems.append(f"claim {c['claim_id']} cites unknown source(s) {unknown}")
        invented = {p for p in PLACEHOLDER_RE.findall(out["letter_markdown"])} - placeholders
        if invented:
            problems.append(f"letter uses placeholders that don't exist: {sorted(invented)}")
        if len(out["letter_markdown"]) < 500:
            problems.append("letter is too short to be a complete appeal")
        return "; ".join(problems) or None
    return validate


# ---- the run --------------------------------------------------------------------
def orchestrate(case_dir: Path, run_id: str | None = None, stop_after: str | None = None,
                offline: bool = False) -> Path:
    if run_id:
        state = RunState.load(run_id)
        case_dir = Path(state.case_dir)
        set_log_file(state.dir / "events.jsonl")
        emit("orchestrator", "start", f"resuming run {run_id}")
    else:
        run_id = f"{case_dir.name}-{datetime.now():%Y%m%d-%H%M%S}"
        state = RunState(run_id=run_id, case_dir=str(case_dir.resolve()))
        state.save()
        set_log_file(state.dir / "events.jsonl")
        emit("orchestrator", "start", f"new run {run_id} for case '{case_dir.name}'")
    emit("orchestrator", "info",
         "workflow: intake → planner → (policy ∥ evidence) → writer ⇄ (reviewer ∥ fact-checker) → packager")

    raw_docs, library = load_case(case_dir)
    S = dict(stop_after=stop_after)

    # 1. Intake: find identifiers, redact them, extract the facts
    emit("intake", "info", f"received {len(raw_docs)} documents: {', '.join(raw_docs)}")
    phi = run_stage(state, "intake_phi", "intake", lambda fb: agents.intake_phi_scan(raw_docs, fb),
                    validate=validate_phi, **S)
    mapping, display = redact.build_map(PHIScan(**phi), raw_docs)
    docs = {k: redact.apply(v, mapping) for k, v in raw_docs.items()}
    leaked = [l for d in docs.values() for l in redact.leaks(d, mapping)]
    if leaked:
        raise SystemExit(f"Redaction check failed, refusing to continue: {len(leaked)} identifiers remain")
    state.write_private("phi_map.json", {"redact": mapping, "display": display})
    emit("intake", "done", f"redacted {len(mapping)} identifier strings ({len(display)} distinct) · leak check passed · "
                           "downstream agents see placeholders only")

    facts = run_stage(state, "intake_facts", "intake", lambda fb: agents.intake_facts(docs, fb),
                      validate=validate_facts, **S)
    emit("intake", "handoff", f"planner: {facts['service_requested']} denied "
                              f"({facts['denial_reason_code']}) on {facts['denial_date']}")

    # 2. Planner
    run_plan = run_stage(state, "plan", "planner", lambda fb: agents.plan(facts, fb), **S)
    emit("planner", "info", f"category={run_plan['denial_category']} · appeal={run_plan['appeal_type']}")
    emit("planner", "info", f"strategy: {run_plan['strategy']}")
    emit("planner", "handoff", f"policy_analyst: {len(run_plan['policy_questions'])} questions · "
                               f"→ evidence_researcher: {len(run_plan['research_questions'])} questions")

    # 3. Policy Analyst and Evidence Researcher in parallel
    def do_evidence():
        if not offline:
            try:
                return run_stage(state, "evidence_web", "evidence_researcher",
                                 lambda fb: agents.evidence_web(facts, run_plan, fb), retries=2, **S)
            except StageFailed:
                emit("evidence_researcher", "warn", "web research unavailable → falling back to offline reference library")
        if not library:
            raise StageFailed("evidence: web failed and no offline library")
        return run_stage(state, "evidence_offline", "evidence_researcher",
                         lambda fb: agents.evidence_offline(library, run_plan, fb), **S)

    for name in ("policy", "evidence_web", "evidence_offline"):
        state.stage(name)  # pre-register before threads start
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_policy = pool.submit(run_stage, state, "policy", "policy_analyst",
                               lambda fb: agents.policy_analysis(docs, facts, run_plan, fb), **S)
        f_evidence = pool.submit(do_evidence)
        policy, evidence = f_policy.result(), f_evidence.result()

    for d in policy["discrepancies"]:
        emit("policy_analyst", "info", f"discrepancy: {d}")
    met = sum(c["status"] == "met" for c in policy["criteria"])
    emit("policy_analyst", "handoff", f"writer: {met}/{len(policy['criteria'])} criteria met")
    for item in evidence["items"]:
        emit("evidence_researcher", "info", f"{item['source_id']}: {item['title']} ({item['publisher']})")
    emit("evidence_researcher", "handoff", f"writer: {len(evidence['items'])} sources")

    # 4. Writer ⇄ Reviewer + Fact Checker, bounded loop
    known_sources = set(docs) | {i["source_id"] for i in evidence["items"]}
    validate_draft = make_draft_validator(known_sources, {p.strip("[]") for p in display})
    draft = review = factcheck = None
    rounds = 0
    for r in range(1, MAX_ROUNDS + 1):
        rounds = r
        prev, prev_review, prev_fc = draft, review, factcheck
        draft = run_stage(state, f"draft_{r}", "writer",
                          lambda fb: agents.write_appeal(docs, facts, run_plan, policy, evidence,
                                                         prev, prev_review, prev_fc, fb),
                          validate=validate_draft, **S)
        emit("writer", "handoff", f"reviewer + fact_checker: draft {r} "
                                  f"({len(draft['letter_markdown'].split())} words, {len(draft['claims'])} claims)")

        with ThreadPoolExecutor(max_workers=2) as pool:
            f_rev = pool.submit(run_stage, state, f"review_{r}", "reviewer",
                                lambda fb: agents.review(docs, facts, policy, draft, fb), **S)
            f_fc = pool.submit(run_stage, state, f"factcheck_{r}", "fact_checker",
                               lambda fb: agents.fact_check(docs, evidence, draft, fb), **S)
            review, factcheck = f_rev.result(), f_fc.result()

        unsupported = [c for c in factcheck["checks"] if not c["supported"]]
        n_bad = len(unsupported) + len(factcheck["untracked_claims"])
        emit("reviewer", "info", f"score {review['score']}/10 · {review['decision']} · "
                                 f"{len(review['required_changes'])} required changes")
        for rb in review["insurer_rebuttals"][:3]:
            emit("reviewer", "info", f"insurer would argue: {rb}")
        emit("fact_checker", "info", f"{len(factcheck['checks']) - len(unsupported)}/{len(factcheck['checks'])} "
                                     f"claims verified · {n_bad} problems")
        for c in unsupported:
            emit("fact_checker", "warn", f"{c['claim_id']} unsupported: {c['explanation']}")

        if review["decision"] == "approve" and review["score"] >= APPROVE_SCORE and n_bad == 0:
            emit("orchestrator", "done", f"draft {r} approved by reviewer and fact checker")
            break
        if r < MAX_ROUNDS:
            emit("orchestrator", "loop", f"round {r} not approved → back to writer with "
                                         f"{len(review['required_changes'])} changes + {n_bad} fact problems")
        else:
            emit("orchestrator", "warn", f"round limit ({MAX_ROUNDS}) reached → packaging with "
                                         "open issues flagged for human review")

    # 5. Packager (deterministic: fills identifiers back in locally, builds the packet)
    out_dir = run_stage(state, "package", "packager",
                        lambda fb: packager.build(state, facts, run_plan, policy, evidence, draft,
                                                  review, factcheck, display, rounds), **S)
    state.status = "done"
    state.save()
    emit("orchestrator", "done", f"appeal packet ready: {out_dir['html']}")
    return Path(out_dir["html"])
