"""The Orchestrator: plans the run, hands artifacts between agents, retries
failures, runs independent agents in parallel, and checkpoints every stage so a
run can resume after a crash."""
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

from . import agents, llm, packager, redact, trace
from .llm import AgentError, FatalError
from .log import context as log_context, emit, set_log_file
from .schemas import PHIScan
from .state import RunState

ROOT = Path(__file__).resolve().parent.parent
MAX_ROUNDS = 3  # writer <-> reviewer/fact-checker revision rounds
APPROVE_SCORE = 8
HOPELESS_SCORE = 3  # reviewer score at or below which revising stops: polishing won't change the outcome

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
              validate=None, stop_after: str | None = None, inputs: dict | None = None, received: str = ""):
    """Run one agent stage with retries. `inputs` describes what the agent receives
    (sizes and artifact names, never identifiers) and `received` says it in words."""
    if state.is_done(name):
        out = state.output(name)
        summary, data = trace.stage_output(name, out)
        emit(agent, "info", f"{name}: restored from checkpoint · {summary}", stage=name, restored=True, output=data)
        return out

    feedback = None
    t_first = time.monotonic()
    for attempt in range(1, retries + 1):
        stage = state.begin(name)
        t0 = time.monotonic()
        with log_context(stage=name, attempt=attempt):
            emit(agent, "start", f"{name} (attempt {attempt}/{retries})" + (f" · received {received}" if received else ""),
                 max_attempts=retries, inputs=inputs or {},
                 **({"feedback_from_previous_attempt": feedback} if feedback else {}))
            try:
                if CHAOS and name in CHAOS_FAILS and stage.attempts == 1:
                    raise AgentError(f"[chaos] {CHAOS_FAILS[name]}")
                out = fn(feedback)
                problem = validate(out) if validate else None
                if problem:
                    feedback = problem  # validation problems go back to the agent
                    raise AgentError(f"output rejected by the orchestrator's validator: {problem}")
                state.complete(name, out)
                summary, data = trace.stage_output(name, out)
                took = time.monotonic() - t0
                emit(agent, "done", f"{name} complete in {took:.1f}s" + (f" · {summary}" if summary else ""),
                     duration_s=round(took, 2), total_duration_s=round(time.monotonic() - t_first, 2),
                     validator="passed" if validate else "none", output=data)
                if stop_after == name:
                    raise StopRequested(name)
                return out
            except FatalError as e:
                state.fail(name, str(e))
                emit(agent, "error", f"{name}: {e} · not retryable, stopping run", reason=str(e),
                     duration_s=round(time.monotonic() - t0, 2), retryable=False)
                raise
            except (AgentError, Exception) as e:
                if isinstance(e, StopRequested):
                    raise
                if not isinstance(e, AgentError):
                    e = AgentError(f"unexpected {type(e).__name__}: {str(e)[:200]}")
                state.fail(name, str(e))
                fed_back = feedback  # the next attempt's prompt carries the last validator rejection, if any
                if attempt < retries:
                    wait = 2 ** attempt
                    emit(agent, "retry", f"{name} failed: {e} · retrying in {wait}s"
                         + (" with the validator's feedback" if fed_back else " with the same inputs"),
                         reason=str(e), duration_s=round(time.monotonic() - t0, 2), wait_s=wait,
                         next_attempt=attempt + 1, fed_back_to_agent=fed_back,
                         chaos=str(e).startswith("[chaos]"))
                    time.sleep(wait)
                else:
                    emit(agent, "error", f"{name} failed after {retries} attempts: {e}", reason=str(e),
                         duration_s=round(time.monotonic() - t0, 2), retryable=True)
    raise StageFailed(name)


def handoff(sender: str, to: list[str], artifact: str, message: str, **data) -> None:
    emit(sender, "handoff", message, to=to, artifact=artifact, **data)


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


def final_verdict(run_plan: dict, policy: dict, review: dict) -> str:
    """Combine three independent judgments; any one of them can mark an appeal weak."""
    ratings = (run_plan["merit"], policy["merit"])
    if review["score"] <= HOPELESS_SCORE or "weak" in ratings:
        return "weak"
    if all(m == "strong" for m in ratings) and review["score"] >= APPROVE_SCORE:
        return "strong"
    return "possible"


# ---- the run --------------------------------------------------------------------
def orchestrate(case_dir: Path | None, run_id: str | None = None, stop_after: str | None = None,
                offline: bool = False, new_run_id: str | None = None) -> Path:
    """Start a new run on case_dir, or resume run_id from its checkpoints."""
    config = {"model": llm.MODEL, "mock": llm.MOCK, "chaos": CHAOS, "offline": offline,
              "max_revision_rounds": MAX_ROUNDS, "approve_score": APPROVE_SCORE, "hopeless_score": HOPELESS_SCORE,
              "chaos_failures": CHAOS_FAILS if CHAOS else {}}
    if run_id:
        state = RunState.load(run_id)
        case_dir = Path(state.case_dir)
        state.status = "running"
        state.save()
        set_log_file(state.dir / "events.jsonl")
        done = [k for k, s in state.stages.items() if s.status == "done"]
        emit("orchestrator", "start", f"resuming run {run_id} · {len(done)} stages restored from checkpoints",
             run=run_id, case_folder=case_dir.name, resumed=True, restored_stages=done, config=config)
    else:
        run_id = new_run_id or f"{case_dir.name}-{datetime.now():%Y%m%d-%H%M%S}"
        state = RunState(run_id=run_id, case_dir=str(case_dir.resolve()))
        state.save()
        set_log_file(state.dir / "events.jsonl")
        emit("orchestrator", "start", f"new run {run_id} for case '{case_dir.name}' · model {llm.MODEL}"
             + (" · chaos mode: planned failures on first attempts" if CHAOS else ""),
             run=run_id, case_folder=case_dir.name, resumed=False, config=config)
    t0 = time.monotonic()
    try:
        return _run(state, case_dir, stop_after, offline)
    except StopRequested:
        state.status = "stopped"
        state.save()
        emit("orchestrator", "warn", "run stopped on request · resume to continue from the checkpoint",
             stopped_after=stop_after)
        raise
    except BaseException as e:
        state.status = "failed"
        state.save()
        emit("orchestrator", "error", f"run failed: {type(e).__name__}: {str(e)[:200]} · resume to continue",
             reason=f"{type(e).__name__}: {str(e)[:200]}")
        raise
    finally:
        if state.status in ("done", "failed", "stopped"):
            t = trace.totals(trace.read_events(state.dir / "events.jsonl"))
            emit("orchestrator", "info", f"run summary · {state.status} · {time.monotonic() - t0:.0f}s this session · "
                 f"{t['model_calls']} model calls · {t['input_tokens']:,} in / {t['output_tokens']:,} out tokens · "
                 f"est. ${t['cost_usd']:.2f} · {t['retries']} retries",
                 type="run_summary", status=state.status, session_seconds=round(time.monotonic() - t0, 1), **t)


def _run(state: RunState, case_dir: Path, stop_after: str | None, offline: bool) -> Path:
    emit("orchestrator", "info",
         "workflow: intake → planner → (policy ∥ evidence) → writer ⇄ (reviewer ∥ fact-checker) → packager",
         type="workflow", stages=["intake_phi", "intake_facts", "plan", "policy ∥ evidence", "draft_n ⇄ (review_n ∥ factcheck_n)",
                                  "package"])

    raw_docs, library = load_case(case_dir)
    S = dict(stop_after=stop_after)

    # 1. Intake: find identifiers, redact them, extract the facts
    emit("intake", "info", f"received {len(raw_docs)} documents: {trace.describe_docs(raw_docs)}"
         + (f" · offline reference library {trace.words(library):,} words" if library else ""),
         **trace.docs_input(raw_docs), reference_library_words=trace.words(library))
    phi = run_stage(state, "intake_phi", "intake", lambda fb: agents.intake_phi_scan(raw_docs, fb),
                    validate=validate_phi, inputs=trace.docs_input(raw_docs),
                    received=f"the {len(raw_docs)} raw documents (the only stage that sees identifiers)", **S)
    mapping, display = redact.build_map(PHIScan(**phi), raw_docs)
    docs = {k: redact.apply(v, mapping) for k, v in raw_docs.items()}
    leaked = [l for d in docs.values() for l in redact.leaks(d, mapping)]
    if leaked:
        emit("intake", "error", f"redaction check failed: {len(leaked)} identifiers remain · refusing to continue",
             leak_check="failed", remaining=len(leaked))
        raise SystemExit(f"Redaction check failed, refusing to continue: {len(leaked)} identifiers remain")
    state.write_private("phi_map.json", {"redact": mapping, "display": display})
    msg, data = trace.redaction(mapping, display, docs)
    emit("intake", "done", msg + " · downstream agents see placeholders only", **data)

    facts = run_stage(state, "intake_facts", "intake", lambda fb: agents.intake_facts(docs, fb),
                      validate=validate_facts, inputs=trace.docs_input(docs),
                      received=f"{len(docs)} redacted documents", **S)
    handoff("intake", ["planner"], "CaseFacts",
            f"planner: case facts · {facts['service_requested']} denied ({facts['denial_reason_code']}) on "
            f"{facts['denial_date']} · {len(facts['missing_information'])} gaps noted", chars=trace.size(facts))

    # 2. Planner
    run_plan = run_stage(state, "plan", "planner", lambda fb: agents.plan(facts, fb),
                         inputs=trace.artifact_input(CaseFacts=facts), received="the case facts (no documents)", **S)
    emit("planner", "info", f"category={run_plan['denial_category']} · appeal={run_plan['appeal_type']} · "
                            f"{run_plan['appeal_type_rationale']}")
    emit("planner", "info", f"merit: {run_plan['merit']} · {run_plan['merit_rationale']}", merit=run_plan["merit"])
    emit("planner", "info", f"strategy: {run_plan['strategy']}")
    for r in run_plan["risks"]:
        emit("planner", "info", f"risk: {r}", type="risk")
    handoff("planner", ["policy_analyst", "evidence_researcher"], "RunPlan",
            f"policy_analyst: {len(run_plan['policy_questions'])} questions · "
            f"→ evidence_researcher: {len(run_plan['research_questions'])} questions",
            policy_questions=run_plan["policy_questions"], research_questions=run_plan["research_questions"])

    # 3. Policy Analyst and Evidence Researcher in parallel
    def do_evidence():
        if not offline:
            try:
                return run_stage(state, "evidence_web", "evidence_researcher",
                                 lambda fb: agents.evidence_web(facts, run_plan, fb), retries=2,
                                 inputs={"clinical_summary_chars": len(facts["clinical_summary"]),
                                         "diagnoses": len(facts["diagnoses"]),
                                         "research_questions": len(run_plan["research_questions"]),
                                         "identifiers_sent_to_search": 0},
                                 received=f"a de-identified clinical summary and {len(run_plan['research_questions'])} "
                                          "research questions", **S)
            except StageFailed:
                emit("evidence_researcher", "warn", "web research unavailable → falling back to offline reference library",
                     type="fallback", from_stage="evidence_web", to_stage="evidence_offline")
        if not library:
            raise StageFailed("evidence: web failed and no offline library")
        return run_stage(state, "evidence_offline", "evidence_researcher",
                         lambda fb: agents.evidence_offline(library, run_plan, fb),
                         inputs={"reference_library_words": trace.words(library),
                                 "research_questions": len(run_plan["research_questions"])},
                         received=f"the offline reference library ({trace.words(library):,} words)", **S)

    for name in ("policy", "evidence_web", "evidence_offline"):
        state.stage(name)  # pre-register before threads start
    emit("orchestrator", "info", "policy analyst and evidence researcher run in parallel", type="parallel",
         stages=["policy", "evidence"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_policy = pool.submit(run_stage, state, "policy", "policy_analyst",
                               lambda fb: agents.policy_analysis(docs, facts, run_plan, fb),
                               inputs={**trace.docs_input(docs), **trace.artifact_input(CaseFacts=facts),
                                       "planner_questions": len(run_plan["policy_questions"])},
                               received=f"{len(docs)} redacted documents, the case facts and "
                                        f"{len(run_plan['policy_questions'])} planner questions", **S)
        f_evidence = pool.submit(do_evidence)
        policy, evidence = f_policy.result(), f_evidence.result()

    for c in policy["criteria"]:
        emit("policy_analyst", "info", f"criterion {c['criterion_id']} {c['status'].replace('_', ' ')}: "
                                       f"{c['criterion_text']} [{', '.join(c['source_ids'])}]",
             type="criterion", criterion=c["criterion_id"], status=c["status"])
    for d in policy["discrepancies"]:
        emit("policy_analyst", "info", f"discrepancy: {d}")
    for p in policy["procedural_issues"]:
        emit("policy_analyst", "info", f"procedural issue: {p}")
    emit("policy_analyst", "info", f"merit: {policy['merit']} · {policy['merit_rationale']}", merit=policy["merit"])
    met = sum(c["status"] == "met" for c in policy["criteria"])
    handoff("policy_analyst", ["writer"], "PolicyAnalysis", f"writer: {met}/{len(policy['criteria'])} criteria met",
            chars=trace.size(policy))
    for item in evidence["items"]:
        emit("evidence_researcher", "info", f"{item['source_id']}: {item['title']} ({item['publisher']}) {item['url']}",
             type="source", source=item["source_id"], url=item["url"])
    for g in evidence["gaps"]:
        emit("evidence_researcher", "info", f"gap: {g}")
    handoff("evidence_researcher", ["writer"], "EvidencePack", f"writer: {len(evidence['items'])} sources",
            chars=trace.size(evidence))

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
                          validate=validate_draft,
                          inputs={**trace.docs_input(docs), **trace.artifact_input(
                              CaseFacts=facts, RunPlan=run_plan, PolicyAnalysis=policy, EvidencePack=evidence,
                              previous_draft=prev and prev["letter_markdown"]),
                              "required_changes": len(prev_review["required_changes"]) if prev_review else 0,
                              "fact_problems": (len([c for c in prev_fc["checks"] if not c["supported"]])
                                                + len(prev_fc["untracked_claims"])) if prev_fc else 0,
                              "known_sources": sorted(known_sources)},
                          received="documents, facts, plan, policy analysis, evidence"
                                   + (" + the previous draft and the reviewers' feedback" if prev else ""), **S)
        handoff("writer", ["reviewer", "fact_checker"], "AppealDraft",
                f"reviewer + fact_checker: draft {r} ({len(draft['letter_markdown'].split())} words, "
                f"{len(draft['claims'])} claims)", round=r)

        emit("orchestrator", "info", f"reviewer and fact checker check draft {r} in parallel", type="parallel",
             stages=[f"review_{r}", f"factcheck_{r}"])
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_rev = pool.submit(run_stage, state, f"review_{r}", "reviewer",
                                lambda fb: agents.review(docs, facts, policy, draft, fb),
                                inputs={**trace.docs_input(docs), **trace.artifact_input(
                                    PolicyAnalysis=policy, draft=draft["letter_markdown"])},
                                received=f"draft {r}, the documents and the policy analysis", **S)
            f_fc = pool.submit(run_stage, state, f"factcheck_{r}", "fact_checker",
                               lambda fb: agents.fact_check(docs, evidence, draft, fb),
                               inputs={"sources": sorted(known_sources), "claims": len(draft["claims"]),
                                       **trace.artifact_input(draft=draft["letter_markdown"])},
                               received=f"draft {r}'s {len(draft['claims'])} claims and every cited source", **S)
            review, factcheck = f_rev.result(), f_fc.result()

        unsupported = [c for c in factcheck["checks"] if not c["supported"]]
        n_bad = len(unsupported) + len(factcheck["untracked_claims"])
        emit("reviewer", "info", f"score {review['score']}/10 · {review['decision']} · "
                                 f"{len(review['required_changes'])} required changes",
             score=review["score"], decision=review["decision"], round=r)
        for rb in review["insurer_rebuttals"]:
            emit("reviewer", "info", f"insurer would argue: {rb}", type="rebuttal", round=r)
        for ch in review["required_changes"]:
            emit("reviewer", "info", f"required change: {ch}", type="required_change", round=r)
        emit("fact_checker", "info", f"{len(factcheck['checks']) - len(unsupported)}/{len(factcheck['checks'])} "
                                     f"claims verified · {n_bad} problems",
             verified=len(factcheck["checks"]) - len(unsupported), claims=len(factcheck["checks"]), round=r)
        for c in unsupported:
            emit("fact_checker", "warn", f"{c['claim_id']} unsupported: {c['explanation']}", type="unsupported_claim",
                 claim=c["claim_id"], round=r)
        for u in factcheck["untracked_claims"]:
            emit("fact_checker", "warn", f"untracked statement: {u}", type="untracked_claim", round=r)

        if review["decision"] == "approve" and review["score"] >= APPROVE_SCORE and n_bad == 0:
            emit("orchestrator", "done", f"draft {r} approved by reviewer and fact checker", round=r,
                 rule=f"reviewer approves with score ≥ {APPROVE_SCORE} and the fact checker finds 0 problems")
            break
        if review["score"] <= HOPELESS_SCORE:
            emit("orchestrator", "warn", f"reviewer scored {review['score']}/10 → stopping revisions: the record, "
                                         "not the wording, is the problem. Packaging an honest assessment",
                 round=r, rule=f"score ≤ {HOPELESS_SCORE} stops the loop")
            break
        if r < MAX_ROUNDS:
            emit("orchestrator", "loop", f"round {r} not approved → back to writer with "
                                         f"{len(review['required_changes'])} changes + {n_bad} fact problems",
                 to=["writer"], round=r, fed_back_to_writer={
                     "required_changes": review["required_changes"], "insurer_rebuttals": review["insurer_rebuttals"],
                     "unsupported_claims": [{"claim": c["claim_id"], "explanation": c["explanation"]} for c in unsupported],
                     "untracked_claims": factcheck["untracked_claims"]})
        else:
            emit("orchestrator", "warn", f"round limit ({MAX_ROUNDS}) reached → packaging with "
                                         "open issues flagged for human review", round=r)

    verdict = final_verdict(run_plan, policy, review)
    emit("orchestrator", "info", f"verdict: {verdict} (planner {run_plan['merit']}, policy analyst "
                                 f"{policy['merit']}, reviewer {review['score']}/10)", merit=verdict, final=True,
         planner_merit=run_plan["merit"], policy_merit=policy["merit"], reviewer_score=review["score"],
         rule=f"weak if any rating is weak or score ≤ {HOPELESS_SCORE}; strong if both ratings are strong and "
              f"score ≥ {APPROVE_SCORE}; otherwise possible")
    handoff("orchestrator", ["packager"], "final draft + reviews",
            f"packager: draft {rounds}, review, fact check and verdict {verdict}", round=rounds)

    # 5. Packager (deterministic: fills identifiers back in locally, builds the packet)
    out_dir = run_stage(state, "package", "packager",
                        lambda fb: packager.build(state, facts, run_plan, policy, evidence, draft,
                                                  review, factcheck, display, rounds, verdict),
                        inputs={"model_calls": 0, "identifier_map": "local only"},
                        received="the final draft, reviews and verdict (no model call)", **S)
    deadline = (datetime.strptime(facts["denial_date"], "%Y-%m-%d")
                + timedelta(days=facts["appeal_window_days"])).strftime("%Y-%m-%d")
    msg, data = trace.package(out_dir, verdict, deadline, ROOT)
    emit("packager", "info", msg, **data)
    state.status = "done"
    state.save()
    emit("orchestrator", "done", f"appeal packet ready: {data['outputs'].get('html', '')}", packet=True,
         verdict=verdict, rounds=rounds)
    return Path(out_dir["html"])
