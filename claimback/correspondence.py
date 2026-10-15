"""Turns an incoming email into case updates: redact it, have the Correspondence
agent read it, check the agent's answer against the email itself, then update
tasks, deadlines and status. Restart-safe: only messages still marked
'received' are processed."""
import email
import email.policy
import json
import re
from datetime import datetime

from . import agents, redact
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
    known = {k: redact.apply(v, mapping) for k, v in parts.items()}
    # A fresh scan catches identifiers the case hasn't seen yet (a new name, a new ID)
    scan = agents.intake_phi_scan({k.upper(): v for k, v in known.items()})
    new_map, new_display = redact.build_map(PHIScan(**scan), known)
    added = 0
    for original, placeholder in new_map.items():
        if original in mapping or original.startswith("["):
            continue
        tag = f"[MAIL_{placeholder.strip('[]')}]"  # keep new placeholders distinct from the run's
        mapping[original] = tag
        display[tag] = new_display[placeholder]
        added += 1
    atomic_write_json(case.dir / "phi_map.json", {"redact": mapping, "display": display})
    out = {k: redact.apply(v, mapping) for k, v in parts.items()}
    leaked = [l for v in out.values() for l in redact.leaks(v, mapping)]
    if leaked:
        raise AgentError(f"redaction check failed: {len(leaked)} identifier(s) remain")
    case.emit("correspondence", "info", f"redacted before reading · {added} new identifier(s) added to the case map")
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


def apply_analysis(case: Case, entry: dict, a: dict) -> None:
    cid = entry["id"]
    case.emit("correspondence", "done", f"{cid} is {a['message_type'].replace('_', ' ')}: {a['summary']}",
              correspondence=cid, message_type=a["message_type"])
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
        cid = entry["id"]
        subject, body = _email_text(case, entry)
        case.emit("correspondence", "start", f"reading {cid}: “{subject}”")
        try:
            red = redact_inbound(case, {"subject": subject, "body": body})
            red_subject, red_body = red["subject"], red["body"]
        except AgentError as e:
            case.emit("correspondence", "error", f"{cid}: {e}; not sending it to any agent")
            entry["status"] = "needs_human"
            case.add_task("human_review", f"Read {cid} yourself: it couldn't be safely redacted", correspondence=cid)
            case.set_status("awaiting_human", "redaction failed")
            case.save()
            continue
        feedback, analysis = None, None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                candidate = agents.analyze_correspondence(_summary(case), red_subject, red_body, feedback)
            except FatalError:
                raise
            except AgentError as e:
                case.emit("correspondence", "retry", f"{cid} attempt {attempt}: {e}")
                continue
            candidate = normalize(candidate)
            problem = validate(candidate, red_body)
            if not problem:
                analysis = candidate
                break
            feedback = problem
            case.emit("correspondence", "retry", f"{cid} attempt {attempt} rejected: {problem}")
        if analysis is None:
            entry["status"] = "needs_human"
            case.add_task("human_review", f"Read {cid}: ClaimBack couldn't interpret it reliably", correspondence=cid)
            case.set_status("awaiting_human", f"{cid} couldn't be interpreted reliably")
        else:
            entry["status"], entry["analysis"] = "analyzed", analysis
            apply_analysis(case, entry, analysis)
        case.save()
        done += 1
    return done
