"""Canned agent outputs for offline testing (--mock). They exercise the same
orchestration paths as a real run: the first review asks for revisions and the
first fact check flags a claim, so the revision loop runs."""
import itertools
import threading
import time

from .schemas import (AppealDraft, CaseFacts, EvidencePack, FactCheckReport,
                      PHIScan, PolicyAnalysis, ReviewVerdict, RunPlan)

_counts: dict[str, itertools.count] = {}
_lock = threading.Lock()


def _n(key: str) -> int:
    with _lock:
        return next(_counts.setdefault(key, itertools.count(1)))


LETTER = """**Re: Request for internal appeal, Request # UM-2026-0918-55731, Member ID [MEMBER_ID_1]**

To the Appeals and Grievances Department:

I, [PATIENT_NAME_1], request an internal appeal of the denial of a continuous glucose monitor (E2103 / A4239).

The denial states that Medical Policy MP-DME-031 requires three or more daily insulin injections. That requirement was removed from the policy on 01/01/2026. Criterion I.B.1 now covers any insulin-treated member, including a single daily dose of basal insulin.

I take insulin glargine 32 units nightly, and I have had recurrent level 2 hypoglycemia (48 and 51 mg/dL) despite a dose reduction, which also meets criterion I.B.2.a.

Please overturn this denial and send me a written decision within 30 days.

Sincerely,
[PATIENT_NAME_1]
"""


def respond(agent: str, schema):
    time.sleep(0.3)
    if schema is PHIScan:
        return PHIScan(entities=[
            {"text": "Rosa Delgado", "category": "PATIENT_NAME", "refers_to": "Rosa Delgado"},
            {"text": "EVM-88231407", "category": "MEMBER_ID", "refers_to": "EVM-88231407"},
            {"text": "03/14/1961", "category": "DATE_OF_BIRTH", "refers_to": "03/14/1961"},
            {"text": "1427 Alder Creek Lane", "category": "PATIENT_ADDRESS", "refers_to": "1427 Alder Creek Lane"},
            {"text": "WVE-0049217", "category": "MEDICAL_RECORD_NUMBER", "refers_to": "WVE-0049217"},
            {"text": "Dr. Anil Mehta, MD", "category": "PROVIDER_NAME", "refers_to": "Anil Mehta"},
            {"text": "Anil Mehta", "category": "PROVIDER_NAME", "refers_to": "Anil Mehta"},
        ])
    if schema is CaseFacts:
        return CaseFacts(
            insurer_name="Evergreen Mutual Health Plan", denial_date="2026-09-22",
            request_or_claim_number="UM-2026-0918-55731", service_requested="Continuous glucose monitor",
            service_codes=["E2103", "A4239"], denial_reason_code="MN-04",
            denial_reason_summary="Not medically necessary: requires 3+ daily insulin injections",
            policy_cited_by_insurer="MP-DME-031", appeal_window_days=180, expedited_appeal_available=True,
            appeals_mailing_address="PO Box 4415, Portland, OR 97208", appeals_fax="1-800-555-0177",
            diagnoses=["Type 2 diabetes, insulin-treated", "Recurrent level 2 hypoglycemia"],
            current_treatment=["insulin glargine 32 units nightly"],
            clinical_summary="Type 2 diabetes on basal insulin with recurrent nocturnal level 2 hypoglycemia.",
            missing_information=["Letter of medical necessity from the treating provider"])
    if schema is RunPlan:
        return RunPlan(denial_category="medical_necessity", appeal_type="standard",
                       appeal_type_rationale="No imminent jeopardy documented.",
                       strategy="Show the denial applied criteria that the plan removed on 01/01/2026.",
                       policy_questions=["Which version of MP-DME-031 applies?"],
                       research_questions=["What do current guidelines say about CGM on basal insulin?"],
                       argument_hypotheses=["Outdated criteria applied"], risks=["Plan may dispute the effective date"])
    if schema is PolicyAnalysis:
        return PolicyAnalysis(policy_identified="MP-DME-031 rev. 01/01/2026",
                              insurer_rationale="Requires 3+ daily injections",
                              criteria=[{"criterion_id": "I.B.1", "criterion_text": "Insulin-treated",
                                         "status": "met", "supporting_fact": "Glargine 32 units nightly",
                                         "source_ids": ["POLICY", "NOTES"]}],
                              discrepancies=["Denial cites the pre-2026 requirement for 3+ daily injections"],
                              procedural_issues=[], strongest_policy_argument="Criterion I.B.1 is met.")
    if schema is EvidencePack:
        return EvidencePack(items=[{"source_id": "EV-1", "title": "ADA Standards of Care, Section 7",
                                    "publisher": "American Diabetes Association",
                                    "url": "https://diabetesjournals.org/care/issue/48/Supplement_1",
                                    "finding": "Offer CGM to adults on basal insulin.",
                                    "relevance": "Supports medical necessity"}], gaps=[])
    if schema is AppealDraft:
        return AppealDraft(subject_line="Appeal", letter_markdown=LETTER, enclosures=["Clinical note 09/10/2026"],
                           claims=[{"claim_id": "C1", "text": "Requirement removed 01/01/2026", "source_ids": ["POLICY"]},
                                   {"claim_id": "C2", "text": "Recurrent level 2 hypoglycemia", "source_ids": ["NOTES"]}])
    if schema is ReviewVerdict:
        first = _n("review") == 1
        return ReviewVerdict(decision="revise" if first else "approve", score=6 if first else 9,
                             insurer_rebuttals=["The member was never on intensive insulin therapy"] if first else [],
                             required_changes=["Quote the 01/01/2026 revision history line"] if first else [],
                             strengths=["Clear request"])
    if schema is FactCheckReport:
        first = _n("factcheck") == 1
        return FactCheckReport(checks=[{"claim_id": "C1", "supported": True, "explanation": "POLICY revision history"},
                                       {"claim_id": "C2", "supported": not first,
                                        "explanation": "NOTES list two events, not 'recurrent'" if first else "NOTES"}],
                               untracked_claims=[])
    raise ValueError(f"no mock for {schema.__name__}")


def research(agent: str) -> str:
    time.sleep(0.3)
    return "ADA Standards of Care Section 7 (diabetesjournals.org) recommends offering CGM to adults on basal insulin."
