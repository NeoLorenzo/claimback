"""Packager: the only step that puts real identifiers back. It runs locally,
with no model call, and builds the appeal packet as Markdown and printable HTML."""
from datetime import datetime, timedelta
from pathlib import Path

import markdown as md

from . import redact

VERDICT = {
    "strong": ("Strong case: we recommend appealing",
               "The plan's own criteria appear to be met, and the insurer's strongest rebuttals are weak."),
    "possible": ("Possible case: worth appealing, but close the gaps first",
                 "The appeal can win, but it depends on contestable judgment or documentation that's missing. "
                 "Fix the items under *Needs your attention* before sending."),
    "weak": ("Weak case: this appeal is unlikely to succeed",
             "On the documents provided, the denial appears to apply the plan's terms correctly. A better-worded "
             "letter won't change that, so the team stopped revising. The draft below is here if you still want "
             "to appeal, but try the options listed first."),
}


def build(state, facts, run_plan, policy, evidence, draft, review, factcheck, display, rounds,
          verdict="possible", feedback=None) -> dict:
    out_dir = state.dir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    denial = datetime.strptime(facts["denial_date"], "%Y-%m-%d")
    deadline = denial + timedelta(days=facts["appeal_window_days"])
    unsupported = [c for c in factcheck["checks"] if not c["supported"]]
    approved = review["decision"] == "approve" and not unsupported and not factcheck["untracked_claims"]

    letter = redact.rehydrate(draft["letter_markdown"], display)
    send_to = redact.rehydrate(f"{facts['appeals_mailing_address']} · Fax: {facts['appeals_fax']}", display)

    headline, summary = VERDICT[verdict]
    weak = verdict == "weak"
    alternatives = run_plan["alternatives"]
    lines = [
        "# Appeal assessment" if weak else "# Appeal packet",
        "",
        "> **DRAFT FOR HUMAN REVIEW.** ClaimBack prepared this draft. It is not legal or medical advice. "
        "Read every statement, confirm it is accurate, then sign and send it yourself.",
        "",
        f"## Our assessment: {headline}",
        "",
        summary,
        "",
        f"- **Planner:** {run_plan['merit']} · {run_plan['merit_rationale']}",
        f"- **Policy Analyst (plan criteria):** {policy['merit']} · {policy['merit_rationale']}",
        f"- **Adversarial Reviewer (playing the insurer):** {review['score']}/10",
        "",
    ]
    if alternatives:
        lines += ["### " + ("Better options to try first" if weak else "Also worth doing"), "",
                  "*Suggestions from the Planner. Unlike the letter, these aren't fact-checked, so confirm "
                  "products, prices and coverage before relying on them.*", "",
                  *[f"- {a}" for a in alternatives], ""]
    lines += [
        "## At a glance",
        "",
        "| Field | Detail |\n|---|---|",
        f"| **Insurer** | {facts['insurer_name']} |",
        f"| **Request / claim #** | {facts['request_or_claim_number']} |",
        f"| **Service denied** | {facts['service_requested']} |",
        f"| **Denial reason** | {facts['denial_reason_code']}: {facts['denial_reason_summary']} |",
        f"| **Appeal type** | {run_plan['appeal_type'].title()} — {run_plan['appeal_type_rationale']} |",
        f"| **Appeal must be received by** | **{deadline:%B %d, %Y}** ({facts['appeal_window_days']} days, counted from the {denial:%B %d, %Y} notice date to be safe; the rules count from when you received it) |",
        f"| **Send to** | {send_to} |",
        f"| **Reviewer score** | {review['score']}/10 after {rounds} round(s) · {'approved' if approved else 'open issues, see below'} |",
        "",
        "## If you decide to send it" if weak else "## Before you send",
        "",
        "- [ ] Read the whole letter and correct anything that is wrong",
        "- [ ] Sign and date the letter (and have the treating provider co-sign if possible)",
        *[f"- [ ] Attach: {e}" for e in redact.rehydrate("\n".join(draft["enclosures"]), display).splitlines() if e],
        "- [ ] Attach a copy of the denial notice",
        "- [ ] Send by fax *and* mail, and keep the fax confirmation and a copy of everything",
        f"- [ ] Put {deadline:%B %d, %Y} in your calendar as the hard deadline",
        "- [ ] Call the plan about 7 days after sending to confirm they received the appeal",
        "- [ ] If you haven't yet, ask the plan for a free copy of your claim file and the clinical criteria it used (you have a right to both)",
        "- [ ] If waiting could seriously jeopardize your health, ask your doctor to request an expedited appeal (decided within 72 hours)",
        "- [ ] If the denial is upheld, you can usually ask for an independent external review within 4 months of the final denial (the final letter explains how)",
        "",
    ]

    flags = []
    flags += [f"Unverified claim {c['claim_id']}: {c['explanation']}" for c in unsupported]
    flags += [f"Unverified statement: {u}" for u in factcheck["untracked_claims"]]
    if review["decision"] != "approve":
        flags += [f"Reviewer still expects the insurer to argue: {r}" for r in review["insurer_rebuttals"]]
    flags += [f"Missing information: {m}" for m in facts["missing_information"]]
    if flags:
        lines += ["## Needs your attention", "", *[f"- {redact.rehydrate(f, display)}" for f in flags], ""]

    lines += ["---", "", "## Appeal letter", "", letter, "", "---", "", "## Evidence relied on", ""]
    lines += [f"- **{i['source_id']}** [{i['title']}]({i['url']}) ({i['publisher']}): {i['finding']}"
              for i in evidence["items"]]
    lines += ["", "## Plan criteria check", "", "| Criterion | Status | Support |", "|---|---|---|"]
    lines += [f"| {c['criterion_id']}: {c['criterion_text']} | {c['status'].replace('_', ' ')} | "
              f"{redact.rehydrate(c['supporting_fact'], display)} |" for c in policy["criteria"]]
    lines += ["", "## How this was made", "",
              f"Run `{state.run_id}`. Intake (PHI redaction) → Planner → Policy Analyst ∥ Evidence Researcher → "
              f"Writer ⇄ Adversarial Reviewer ∥ Fact Checker ({rounds} round(s)) → Packager. "
              "The model only saw de-identified documents after intake; names and IDs were filled back in on this "
              "machine. The full agent log is in `events.jsonl`."]

    text = redact.rehydrate("\n".join(lines), display)
    md_path = out_dir / "appeal_packet.md"
    md_path.write_text(text, encoding="utf-8")
    html_path = out_dir / "appeal_packet.html"
    html_path.write_text(_html(text, facts), encoding="utf-8")
    return {"markdown": str(md_path), "html": str(html_path)}


def _html(text: str, facts: dict) -> str:
    body = md.markdown(text, extensions=["tables"])
    body = body.replace("[ ]", "☐")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Appeal packet</title>
<style>
:root {{ --ink:#1d2433; --muted:#5b6475; --line:#d9dee7; --accent:#1f6f5c; --warn:#a35a00; --bg:#ffffff; --panel:#f5f7fa; }}
body {{ background:var(--bg); color:var(--ink); font:16px/1.6 Georgia, 'Times New Roman', serif; max-width:820px; margin:0 auto; padding:32px 16px 80px; }}
h1,h2,h3 {{ font-family: system-ui, sans-serif; line-height:1.25; }}
h1 {{ color:var(--accent); }}
h2 {{ border-bottom:1px solid var(--line); padding-bottom:4px; margin-top:2em; }}
blockquote {{ margin:0; padding:12px 16px; background:var(--panel); border-left:4px solid var(--warn); }}
table {{ border-collapse:collapse; width:100%; font:14px/1.5 system-ui, sans-serif; }}
td,th {{ border:1px solid var(--line); padding:6px 10px; vertical-align:top; text-align:left; }}
ul {{ padding-left:1.3em; }}
a {{ color:var(--accent); }}
hr {{ border:0; border-top:1px solid var(--line); margin:2em 0; }}
@media print {{ body {{ max-width:none; }} h2 {{ break-after:avoid; }} }}
</style></head><body>
{body}
</body></html>"""
