"""Readable summaries of what each agent received and produced, for the event log.

Every function here returns (message, data): a one-line message for people
reading the log, and structured data for the timeline view and for anyone
auditing the run from events.jsonl alone. They only ever see redacted
artifacts, so the output holds placeholders like [PATIENT_NAME_1], counts and
de-identified facts; the PHI scan is summarized by category counts only."""
import json
from collections import Counter
from pathlib import Path


def words(text: str) -> int:
    return len(text.split())


def size(obj) -> int:
    """Characters in an artifact as the next agent receives it."""
    return len(obj) if isinstance(obj, str) else len(json.dumps(obj))


def docs_input(docs: dict[str, str]) -> dict:
    return {"documents": {k: {"chars": len(v), "words": words(v)} for k, v in docs.items()}}


def describe_docs(docs: dict[str, str]) -> str:
    return ", ".join(f"{k} ({words(v):,} words)" for k, v in docs.items())


def artifact_input(**artifacts) -> dict:
    """{name: chars} for the typed artifacts an agent receives."""
    return {"artifacts": {k: size(v) for k, v in artifacts.items() if v is not None}}


def _list(items, n=None):
    items = list(items)
    return items if n is None else items[:n]


# ---- run stages ---------------------------------------------------------------------
def phi_scan(out: dict) -> tuple[str, dict]:
    cats = Counter(e["category"] for e in out["entities"])
    people = len({(e["category"], e["refers_to"].casefold()) for e in out["entities"]
                  if e["category"] in ("PATIENT_NAME", "PROVIDER_NAME")})
    msg = f"found {sum(cats.values())} identifier spellings: " + ", ".join(f"{n} {c}" for c, n in cats.most_common())
    return msg, {"identifier_spellings": sum(cats.values()), "by_category": dict(cats),
                 "distinct_people": people, "values_logged": False}


def redaction(mapping: dict, display: dict, docs: dict) -> tuple[str, dict]:
    by_cat = Counter(p.strip("[]").rsplit("_", 1)[0] for p in display)
    return (f"redacted {len(mapping)} identifier strings into {len(display)} placeholders "
            f"({', '.join(f'{n} {c}' for c, n in by_cat.most_common())}) · leak check passed",
            {"strings_replaced": len(mapping), "placeholders": sorted(display), "placeholders_by_category": dict(by_cat),
             "leak_check": "passed", "redacted_documents": {k: len(v) for k, v in docs.items()},
             "identifier_map": "kept on local disk (phi_map.json), never sent to a model or logged"})


def facts(out: dict) -> tuple[str, dict]:
    msg = (f"{out['insurer_name']} denied {out['service_requested']} ({', '.join(out['service_codes']) or 'no codes'}) "
           f"on {out['denial_date']} · reason {out['denial_reason_code']} · {out['appeal_window_days']}-day appeal window")
    keep = ("insurer_name", "denial_date", "request_or_claim_number", "service_requested", "service_codes",
            "denial_reason_code", "denial_reason_summary", "policy_cited_by_insurer", "appeal_window_days",
            "expedited_appeal_available", "diagnoses", "current_treatment", "clinical_summary", "missing_information")
    return msg, {k: out[k] for k in keep}


def plan(out: dict) -> tuple[str, dict]:
    msg = (f"merit {out['merit']} · {out['denial_category'].replace('_', ' ')} · {out['appeal_type']} appeal · "
           f"{len(out['policy_questions'])} policy + {len(out['research_questions'])} research questions · "
           f"{len(out['risks'])} risks")
    return msg, dict(out)


def policy(out: dict) -> tuple[str, dict]:
    st = Counter(c["status"] for c in out["criteria"])
    msg = (f"{out['policy_identified']}: {st.get('met', 0)}/{len(out['criteria'])} criteria met"
           + (f", {st['unclear']} unclear" if st.get("unclear") else "")
           + (f", {st['not_met']} not met" if st.get("not_met") else "")
           + f" · {len(out['discrepancies'])} discrepancies in the denial · merit {out['merit']}")
    return msg, {"policy_identified": out["policy_identified"], "insurer_rationale": out["insurer_rationale"],
                 "criteria": [{"id": c["criterion_id"], "criterion": c["criterion_text"], "status": c["status"],
                               "supporting_fact": c["supporting_fact"], "sources": c["source_ids"]}
                              for c in out["criteria"]],
                 "criteria_status": dict(st), "discrepancies": out["discrepancies"],
                 "procedural_issues": out["procedural_issues"],
                 "strongest_policy_argument": out["strongest_policy_argument"],
                 "merit": out["merit"], "merit_rationale": out["merit_rationale"]}


def evidence(out: dict, mode: str) -> tuple[str, dict]:
    msg = f"{len(out['items'])} sources ({mode}): " + "; ".join(f"{i['source_id']} {i['publisher']}" for i in out["items"])
    return msg, {"mode": mode, "sources": [{"id": i["source_id"], "title": i["title"], "publisher": i["publisher"],
                                            "url": i["url"], "finding": i["finding"], "relevance": i["relevance"]}
                                           for i in out["items"]], "gaps": out["gaps"]}


def draft(out: dict) -> tuple[str, dict]:
    cited = Counter(s for c in out["claims"] for s in c["source_ids"])
    msg = (f"{words(out['letter_markdown']):,} words · {len(out['claims'])} sourced claims · "
           f"cites {', '.join(f'{s}×{n}' for s, n in sorted(cited.items()))}")
    return msg, {"subject_line": out["subject_line"], "words": words(out["letter_markdown"]),
                 "claims": [{"id": c["claim_id"], "text": c["text"], "sources": c["source_ids"]} for c in out["claims"]],
                 "citations_per_source": dict(cited), "enclosures": out["enclosures"]}


def review(out: dict) -> tuple[str, dict]:
    msg = (f"score {out['score']}/10 · {out['decision']} · {len(out['insurer_rebuttals'])} insurer rebuttals · "
           f"{len(out['required_changes'])} required changes")
    return msg, {"score": out["score"], "decision": out["decision"], "insurer_rebuttals": out["insurer_rebuttals"],
                 "required_changes": out["required_changes"], "strengths": out["strengths"]}


def factcheck(out: dict) -> tuple[str, dict]:
    bad = [c for c in out["checks"] if not c["supported"]]
    msg = (f"{len(out['checks']) - len(bad)}/{len(out['checks'])} claims verified · {len(bad)} unsupported · "
           f"{len(out['untracked_claims'])} untracked statements")
    return msg, {"verified": len(out["checks"]) - len(bad), "claims": len(out["checks"]),
                 "checks": [{"claim": c["claim_id"], "verdict": "supported" if c["supported"] else "unsupported",
                             "explanation": c["explanation"]} for c in out["checks"]],
                 "untracked_claims": out["untracked_claims"]}


def package(out: dict, verdict: str, deadline: str, root: Path) -> tuple[str, dict]:
    rel = {k: Path(v).resolve().relative_to(root).as_posix() if Path(v).resolve().is_relative_to(root) else Path(v).name
           for k, v in out.items()}
    return (f"verdict {verdict} · appeal deadline {deadline} · wrote {', '.join(rel.values())}",
            {"verdict": verdict, "appeal_deadline": deadline, "outputs": rel,
             "identifiers": "filled back in locally by the Packager; no model sees them"})


STAGES = {"intake_phi": phi_scan, "intake_facts": facts, "plan": plan, "policy": policy,
          "evidence_web": lambda o: evidence(o, "web search"), "evidence_offline": lambda o: evidence(o, "offline library"),
          "draft": draft, "review": review, "factcheck": factcheck}


def stage_output(name: str, out) -> tuple[str, dict]:
    fn = STAGES.get(name) or STAGES.get(name.rsplit("_", 1)[0])
    if fn and isinstance(out, dict):
        try:
            return fn(out)
        except (KeyError, TypeError):
            pass
    return "", {"chars": size(out)} if out is not None else {}


# ---- case worker ----------------------------------------------------------------------
def correspondence(a: dict) -> tuple[str, dict]:
    parts = [a["message_type"].replace("_", " ")]
    if a["requested_items"]:
        parts.append(f"{len(a['requested_items'])} requested item(s)")
    if a["decision"]:
        parts.append(f"decision: {a['decision']['outcome']}")
    if a["deadlines"]:
        parts.append(f"{len(a['deadlines'])} deadline(s)")
    parts.append(f"next: {a['next_action']['kind'].replace('_', ' ')} ({a['next_action']['owner']})")
    if a["injection_suspected"]:
        parts.append("possible prompt injection")
    return " · ".join(parts), dict(a)


# ---- totals ---------------------------------------------------------------------------
def totals(events: list[dict]) -> dict:
    """Model calls, tokens, cost and time, overall and per agent, from a log's events."""
    calls = [e for e in events if (e.get("data") or {}).get("type") == "model_call"]
    per_agent: dict[str, dict] = {}
    for e in calls:
        d = e["data"]
        a = per_agent.setdefault(e["agent"], {"model_calls": 0, "input_tokens": 0, "output_tokens": 0,
                                              "cost_usd": 0.0, "model_seconds": 0.0})
        a["model_calls"] += 1
        a["input_tokens"] += d.get("input_tokens", 0)
        a["output_tokens"] += d.get("output_tokens", 0)
        a["cost_usd"] = round(a["cost_usd"] + d.get("cost_usd", 0), 5)
        a["model_seconds"] = round(a["model_seconds"] + d.get("duration_s", 0), 2)
    stages = {}
    for e in events:
        d = e.get("data") or {}
        if e["kind"] == "done" and d.get("stage") and "total_duration_s" in d:
            stages[d["stage"]] = {"agent": e["agent"], "seconds": d["total_duration_s"], "attempts": d.get("attempt", 1)}
    return {
        "model_calls": len(calls),
        "input_tokens": sum(e["data"].get("input_tokens", 0) for e in calls),
        "output_tokens": sum(e["data"].get("output_tokens", 0) for e in calls),
        "web_searches": sum(e["data"].get("web_search_requests", 0) for e in calls),
        "cost_usd": round(sum(e["data"].get("cost_usd", 0) for e in calls), 4),
        "model_seconds": round(sum(e["data"].get("duration_s", 0) for e in calls), 1),
        "retries": sum(e["kind"] == "retry" for e in events),
        "per_agent": per_agent, "stages": stages,
    }


def read_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out
