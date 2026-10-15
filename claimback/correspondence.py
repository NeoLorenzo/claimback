"""Turns an incoming email into case updates: redact it, have the Correspondence
agent read it, check the agent's answer against the email itself, then update
tasks, deadlines and status. Restart-safe: only messages still marked
'received' are processed."""
import email
import email.policy
import json
import re
import time
from collections import Counter
from datetime import datetime

from . import agents, redact, trace
from .cases import Case
from .llm import AgentError, FatalError
from .schemas import PHIScan
from .state import RunState, atomic_write_json

MAX_ATTEMPTS = 3
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
DATE_PATTERNS = [
    (re.compile(rf"\b({MONTHS})\s+(\d{{1,2}}),\s+(\d{{4}})\b"), "%B %d %Y"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "%m %d %Y"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "%Y %m %d"),
]


# ---- redaction ------------------------------------------------------------------
def _identifier_maps(case: Case) -> tuple[dict, dict]:
    """The run's identifier map, extended with anything new found in this case's mail."""
    path = case.dir / "phi_map.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = RunState.load(case.run_id).read_private("phi_map.json")
    return data["redact"], data["display"]


def redact_inbound(case: Case, parts: dict[str, str]) -> dict[str, str]:
    """Redact an email's parts before any agent reads them. Stays local: the
    extended identifier map is written only to the case folder."""
    mapping, display = _identifier_maps(case)
    matched = sum(1 for original in mapping if any(original in v for v in parts.values()))
    known = {k: redact.apply(v, mapping) for k, v in parts.items()}
    # A fresh scan catches identifiers the case hasn't seen yet (a new name, a new ID)
    scan = agents.intake_phi_scan({k.upper(): v for k, v in known.items()})
    new_map, new_display = redact.build_map(PHIScan(**scan), known)
    added = 0
    added_by_category = Counter()
    for original, placeholder in new_map.items():
        if original in mapping or original.startswith("["):
            continue
        tag = f"[MAIL_{placeholder.strip('[]')}]"  # keep new placeholders distinct from the run's
        mapping[original] = tag
        display[tag] = new_display[placeholder]
        added += 1
        added_by_category[placeholder.strip("[]").rsplit("_", 1)[0]] += 1
    atomic_write_json(case.dir / "phi_map.json", {"redact": mapping, "display": display})
    out = {k: redact.apply(v, mapping) for k, v in parts.items()}
    leaked = [l for v in out.values() for l in redact.leaks(v, mapping)]
    if leaked:
        raise AgentError(f"redaction check failed: {len(leaked)} identifier(s) remain")
    case.emit("intake", "info", f"redacted {', '.join(parts)} before any agent reads them · {matched} known identifier(s) "
                                f"replaced · {added} new identifier(s) found by the Intake scan"
                                + (f" ({', '.join(f'{n} {c}' for c, n in added_by_category.items())})" if added else "")
                                + " · leak check passed",
              type="redaction", parts={k: len(v) for k, v in parts.items()}, known_identifiers_replaced=matched,
              new_identifiers=added, new_by_category=dict(added_by_category), leak_check="passed",
              identifier_map="kept in the local case folder only")
    return out


# ---- validation -----------------------------------------------------------------
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().strip('"“”').strip()


def dates_in(text: str) -> set[str]:
    found = set()
    for pattern, fmt in DATE_PATTERNS:
        for m in pattern.finditer(text):
            try:
                found.add(datetime.strptime(" ".join(m.groups()), fmt).strftime("%Y-%m-%d"))
            except ValueError:
                pass
    return found


def normalize_date(value: str | None) -> str | None:
    """Accept any of the email's date formats; store YYYY-MM-DD."""
    if not value:
        return None
    found = dates_in(value)
    return next(iter(found)) if len(found) == 1 else value


def normalize(analysis: dict) -> dict:
    for item in analysis["requested_items"]:
        item["due_date"] = normalize_date(item["due_date"])
    for d in analysis["deadlines"]:
        d["date"] = normalize_date(d["date"])
    return analysis


def validate(analysis: dict, email_text: str) -> str | None:
    """Quotes must be verbatim, and every date must be stated explicitly in the email.
    A date doesn't have to sit inside its item's quote: emails often list the
    items first and give the deadline in the next sentence."""
    body = _norm(email_text)
    stated = dates_in(email_text)
    problems = []

    def check_quote(label, quote):
        if not quote or _norm(quote) not in body:
            problems.append(f"{label}: quote is not copied exactly from the email")

    for i, item in enumerate(analysis["requested_items"], 1):
        check_quote(f"requested item {i}", item["quote"])
        if item["due_date"] and item["due_date"] not in stated:
            problems.append(f"requested item {i}: due_date {item['due_date']} isn't stated in the email; "
                            "use null unless the email gives that exact date")
    for i, d in enumerate(analysis["deadlines"], 1):
        check_quote(f"deadline {i}", d["quote"])
        if d["date"] not in stated:
            problems.append(f"deadline {i}: {d['date']} isn't stated in the email")
    decision = analysis["decision"]
    if analysis["message_type"] == "decision" and not decision:
        problems.append("message_type is 'decision' but no decision is recorded")
    if decision:
        if analysis["message_type"] != "decision":
            problems.append(f"a message classified as '{analysis['message_type']}' cannot carry a decision")
        check_quote("decision", decision["quote"])
        q = decision["quote"].lower()
        if decision["outcome"] == "overturned" and not re.search(r"overturn|approv|revers|grant", q):
            problems.append("decision 'overturned' but the quote doesn't say the denial was overturned or approved")
        if decision["outcome"] == "upheld" and not re.search(r"uphe|uphold|affirm|denied|deny", q):
            problems.append("decision 'upheld' but the quote doesn't say the denial was upheld")
    if analysis["message_type"] == "evidence_request" and not analysis["requested_items"]:
        problems.append("evidence_request with no requested items")
    return "; ".join(problems) or None


# ---- applying the analysis --------------------------------------------------------
def _summary(case: Case) -> dict:
    return {"insurer": case.insurer_name, "request_number": case.claim_number, "stage": case.stage,
            "status": case.status, "open_tasks": [t["title"] for t in case.open_tasks()],
            "messages_so_far": [f"{c['direction']}: {c['subject']}" for c in case.correspondence[-6:]]}


def _email_text(case: Case, entry: dict) -> tuple[str, str]:
    raw = (case.dir / entry["raw_file"]).read_bytes()
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    body = msg.get_body(preferencelist=("plain", "html"))
    return str(msg.get("Subject", "")), body.get_content() if body else ""


def apply_analysis(case: Case, entry: dict, a: dict, took: float | None = None) -> None:
    cid = entry["id"]
    headline, data = trace.correspondence(a)
    case.emit("correspondence", "done", f"{cid} is {a['message_type'].replace('_', ' ')}: {a['summary']}"
              + (f" · {took:.1f}s" if took is not None else ""),
              correspondence=cid, message_type=a["message_type"], headline=headline, output=data,
              **({"total_duration_s": round(took, 2), "duration_s": round(took, 2)} if took is not None else {}))
    for item in a["requested_items"]:
        case.emit("correspondence", "info", f"{cid} requests: {item['item']} (from the {item['owner']}"
                  + (f", due {item['due_date']}" if item["due_date"] else "") + ")", type="requested_item",
                  correspondence=cid, **item)
    if a["decision"]:
        case.emit("correspondence", "info", f"{cid} decision: {a['decision']['outcome']} · “{a['decision']['quote']}”",
                  type="decision", correspondence=cid, **a["decision"])
    case.emit("correspondence", "handoff", f"case_worker: next action {a['next_action']['kind'].replace('_', ' ')} "
                                           f"for {a['next_action']['owner']} · {a['next_action']['description']}",
              to=["case_worker"], artifact="CorrespondenceAnalysis", correspondence=cid, next_action=a["next_action"])
    if a["injection_suspected"]:
        case.emit("correspondence", "warn", f"{cid} looks like an attempt to steer the agents: {a['injection_note']}")

    if not entry["trusted_sender"]:
        case.add_task("confirm_sender", f"Confirm whether {cid} ({entry['from']}) really comes from the insurer "
                      "before ClaimBack acts on it", correspondence=cid)
        case.set_status("awaiting_human", f"{cid} came from an unrecognized sender")
        return
    if a["injection_suspected"]:
        case.add_task("human_review", f"Review {cid}: it contains instructions or requests that look suspicious",
                      correspondence=cid)
        case.set_status("awaiting_human", f"{cid} needs a human to read it")
        return

    for d in a["deadlines"]:
        case.deadlines.append({**d, "source": cid, "confirmed": False})
        case.emit("correspondence", "info", f"deadline from {cid}: {d['label']} by {d['date']} (unconfirmed)",
                  deadline=d["date"])

    kind = a["message_type"]
    if kind == "acknowledgment":
        case.complete_task_kind("await_acknowledgment", f"acknowledged in {cid}")
        if not case.open_tasks("user"):
            case.set_status("awaiting_insurer", f"{cid} confirms receipt; this is not a decision")
    elif kind == "evidence_request":
        for item in a["requested_items"]:
            # The due date is a separate field (the panel shows it with days left), not part of the title
            case.add_task("upload_evidence", f"Provide: {item['item']}", owner="user",
                          supplier=item["owner"], due_date=item["due_date"], quote=item["quote"], correspondence=cid)
        case.set_status("awaiting_human", f"the insurer asked for {len(a['requested_items'])} item(s) in {cid}")
        case.emit("case_worker", "warn", "Waiting for you: the insurer needs more information",
                  notify=True, waiting_for_user=True)
    elif kind == "decision":
        outcome = a["decision"]["outcome"]
        if outcome == "upheld":
            case.stage = "external_review"
            case.add_task("consider_external_review",
                          "The denial was upheld. Decide whether to request independent external review",
                          correspondence=cid, quote=a["decision"]["quote"])
        else:
            case.add_task("confirm_outcome", f"The insurer says the denial was {outcome.replace('_', ' ')}. "
                          "Confirm the outcome to close the case", correspondence=cid, quote=a["decision"]["quote"])
        case.set_status("awaiting_human", f"{cid} states a decision ({outcome}); a human confirms it")
        case.emit("case_worker", "warn", f"Waiting for you: the insurer sent a decision ({outcome})",
                  notify=True, waiting_for_user=True)
    elif kind == "unclear":
        case.add_task("human_review", f"Read {cid} and decide what it means for the case", correspondence=cid)
        case.set_status("awaiting_human", f"{cid} is unclear")
    # administrative: recorded on the timeline, no status change


def process_pending(case: Case) -> int:
    done = 0
    for entry in case.correspondence:
        if entry["direction"] != "in" or entry["status"] != "received":
            continue
        with case.log_context(stage=f"read_{entry['id']}"):
            done += _process_one(case, entry)
    return done


def _process_one(case: Case, entry: dict) -> int:
    cid = entry["id"]
    t_first = time.monotonic()
    subject, body = _email_text(case, entry)
    case.emit("correspondence", "start", f"reading {cid}: “{case.redact_for_log(subject)}” "
                                         f"({trace.words(body):,} words) · redacting first",
              correspondence=cid, words=trace.words(body), simulated=entry.get("simulated", False),
              trusted_sender=entry.get("trusted_sender"))
    try:
        red = redact_inbound(case, {"subject": subject, "body": body})
        red_subject, red_body = red["subject"], red["body"]
    except AgentError as e:
        case.emit("correspondence", "error", f"{cid}: {e}; not sending it to any agent", correspondence=cid,
                  reason=str(e), leak_check="failed")
        entry["status"] = "needs_human"
        case.add_task("human_review", f"Read {cid} yourself: it couldn't be safely redacted", correspondence=cid)
        case.set_status("awaiting_human", "redaction failed")
        case.save()
        return 0
    summary = _summary(case)
    feedback, analysis = None, None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        t0 = time.monotonic()
        case.emit("correspondence", "start", f"read_{cid} (attempt {attempt}/{MAX_ATTEMPTS}) · received the redacted "
                                             f"email ({len(red_body):,} chars) and a case summary",
                  correspondence=cid, attempt=attempt, max_attempts=MAX_ATTEMPTS,
                  inputs={"email_chars": len(red_body), "case_summary": summary},
                  **({"feedback_from_previous_attempt": feedback} if feedback else {}))
        try:
            candidate = agents.analyze_correspondence(summary, red_subject, red_body, feedback)
        except FatalError:
            raise
        except AgentError as e:
            case.emit("correspondence", "retry", f"{cid} attempt {attempt}: {e} · retrying with the same inputs",
                      correspondence=cid, attempt=attempt, reason=str(e), duration_s=round(time.monotonic() - t0, 2))
            continue
        candidate = normalize(candidate)
        problem = validate(candidate, red_body)
        if not problem:
            analysis = candidate
            quotes = len(candidate["requested_items"]) + len(candidate["deadlines"]) + bool(candidate["decision"])
            case.emit("correspondence", "info", f"validator passed: {quotes} quote(s) copied verbatim from the "
                                                "email, every date stated explicitly, classification consistent",
                      type="validator", result="passed", correspondence=cid, attempt=attempt, quotes_checked=quotes,
                      checks=["quotes are verbatim", "dates appear in the email", "decision only on decision emails",
                              "evidence requests list items"])
            break
        feedback = problem
        case.emit("correspondence", "retry", f"{cid} attempt {attempt} rejected by the validator: {problem} · "
                                             "sent back to the agent", type="validator", result="rejected",
                  correspondence=cid, attempt=attempt, reason=problem, fed_back_to_agent=problem,
                  duration_s=round(time.monotonic() - t0, 2))
    if analysis is None:
        entry["status"] = "needs_human"
        case.emit("correspondence", "error", f"{cid}: no valid reading after {MAX_ATTEMPTS} attempts → a human reads it",
                  correspondence=cid)
        case.add_task("human_review", f"Read {cid}: ClaimBack couldn't interpret it reliably", correspondence=cid)
        case.set_status("awaiting_human", f"{cid} couldn't be interpreted reliably")
    else:
        entry["status"], entry["analysis"] = "analyzed", analysis
        apply_analysis(case, entry, analysis, time.monotonic() - t_first)
    case.save()
    return 1
