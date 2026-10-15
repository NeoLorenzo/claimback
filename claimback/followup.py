"""Drafts the reply once the member has supplied everything an insurer asked
for: the Writer drafts a cover letter, the Fact Checker verifies it against the
request, the original appeal and the uploads, and the result waits in the
outbox for the human's Approve & send."""
from datetime import datetime, timezone

from . import agents, redact
from .cases import Case
from .correspondence import _email_text, _identifier_maps, _summary, redact_inbound
from .llm import AgentError, FatalError
from .orchestrator import make_draft_validator
from .state import RunState

MAX_ROUNDS = 2
MAX_ATTEMPTS = 3


def extract_text(path) -> str:
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages).strip()
    return path.read_text(encoding="utf-8", errors="replace").strip()


def _write_with_retries(case: Case, label: str, fn, validate) -> dict:
    feedback = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        case.emit("writer", "start", f"{label} (attempt {attempt}/{MAX_ATTEMPTS})")
        try:
            out = fn(feedback)
        except FatalError:
            raise
        except AgentError as e:
            case.emit("writer", "retry", f"{label} failed: {e}")
            continue
        problem = validate(out)
        if not problem:
            return out
        feedback = problem
        case.emit("writer", "retry", f"{label} rejected: {problem}")
    raise AgentError(f"{label}: no valid draft after {MAX_ATTEMPTS} attempts")


def draft_followup(case: Case, source_cid: str) -> None:
    entry = next(c for c in case.correspondence if c["id"] == source_cid)
    uploads = [u for u in case.uploads if u.get("correspondence") == source_cid]
    subject, body = _email_text(case, entry)

    texts = {}
    for i, u in enumerate(uploads, 1):
        text = extract_text(case.dir / u["file"])
        if not text:
            case.add_task("human_review", f"{u['name']} has no readable text (a scanned image?). "
                          "Upload a text-based PDF or a .txt version", correspondence=source_cid)
            case.set_status("awaiting_human", "an upload couldn't be read")
            case.pending_followups.remove(source_cid)
            case.save()
            return
        texts[f"UPLOAD-{i}"] = text
    red = redact_inbound(case, {"REQUEST": body, **texts})
    run = RunState.load(case.run_id)
    rounds = sorted(int(k.split("_")[1]) for k in run.stages if k.startswith("draft_") and run.is_done(k))
    docs = {"REQUEST": red["REQUEST"], "ORIGINAL_APPEAL": run.output(f"draft_{rounds[-1]}")["letter_markdown"],
            **{k: red[k] for k in texts}}
    names = {f"UPLOAD-{i}": u["name"] for i, u in enumerate(uploads, 1)}
    _, display = _identifier_maps(case)
    validate = make_draft_validator(set(docs), {p.strip("[]") for p in display})
    summary = {**_summary(case), "enclosures": names}

    case.emit("writer", "handoff", f"drafting the reply to {source_cid} with {len(uploads)} enclosure(s)",
              to=["writer"])
    draft = fc = None
    for r in range(1, MAX_ROUNDS + 1):
        prev, prev_fc = draft, fc
        draft = _write_with_retries(case, f"reply_{source_cid}_draft_{r}",
                                    lambda fb: agents.write_followup(summary, docs, prev, prev_fc, fb), validate)
        case.emit("fact_checker", "start", f"verifying {len(draft['claims'])} claims in reply draft {r}")
        fc = agents.fact_check(docs, {"items": []}, draft)
        bad = [c for c in fc["checks"] if not c["supported"]]
        n_bad = len(bad) + len(fc["untracked_claims"])
        case.emit("fact_checker", "info", f"{len(fc['checks']) - len(bad)}/{len(fc['checks'])} claims verified · "
                                          f"{n_bad} problems", round=r)
        for c in bad:
            case.emit("fact_checker", "warn", f"{c['claim_id']} unsupported: {c['explanation']}")
        if not n_bad:
            break
        if r < MAX_ROUNDS:
            case.emit("case_worker", "loop", f"reply draft {r} has {n_bad} unverified statement(s) → back to the writer")

    open_issues = [c["explanation"] for c in fc["checks"] if not c["supported"]] + fc["untracked_claims"]
    oid = f"O{len(case.outbox) + 1}"
    from .letters import split_reviewer_notes
    letter, notes = split_reviewer_notes(redact.rehydrate(draft["letter_markdown"], display))  # filled back in locally
    notes += [redact.rehydrate(n, display) for n in draft.get("reviewer_notes", [])]
    (case.dir / "outbox").mkdir(exist_ok=True)
    (case.dir / "outbox" / f"{oid}.md").write_text(letter, encoding="utf-8")
    case.outbox.append({
        "id": oid, "kind": "evidence_response", "to": case.insurer_addresses[0],
        "subject": subject if subject.lower().startswith("re:") else f"Re: {subject}",
        "body_file": f"outbox/{oid}.md", "in_reply_to": entry["message_id"],
        "attachments": [u["id"] for u in uploads], "status": "awaiting_approval",
        "fact_check": {"verified": len(fc["checks"]) - len(bad), "claims": len(fc["checks"])},
        "open_issues": open_issues, "reviewer_notes": notes, "created": datetime.now(timezone.utc).isoformat(),
    })
    case.pending_followups.remove(source_cid)
    note = f" · {len(open_issues)} statement(s) to check yourself" if open_issues else ""
    case.add_task("approve_send", f"Review the reply to {source_cid} ({len(uploads)} enclosure(s)), then "
                  f"Approve & send it{note}", outbox_id=oid)
    case.set_status("awaiting_human", f"reply {oid} is ready for your approval")
    case.emit("case_worker", "warn", "Waiting for you: a fact-checked reply is ready to approve",
              notify=True, waiting_for_user=True, outbox=oid)
    case.save()


def process_followups(case: Case) -> int:
    done = 0
    for source in list(case.pending_followups):
        try:
            draft_followup(case, source)
            done += 1
        except AgentError as e:
            case.emit("case_worker", "error", f"couldn't draft the reply to {source}: {e}")
            case.add_task("human_review", f"Draft the reply to {source} yourself: ClaimBack couldn't produce a "
                          "valid one", correspondence=source)
            case.pending_followups.remove(source)
            case.set_status("awaiting_human", "reply drafting failed")
            case.save()
    return done
