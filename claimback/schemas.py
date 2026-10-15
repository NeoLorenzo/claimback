"""Typed handoff artifacts. Each agent returns one of these, the orchestrator
checkpoints it, and the next agent reads only the fields it needs."""
from typing import Literal

from pydantic import BaseModel


# ---- Intake ---------------------------------------------------------------
class PHIEntity(BaseModel):
    text: str  # exact string as it appears in the documents
    category: Literal[
        "PATIENT_NAME", "PATIENT_ADDRESS", "DATE_OF_BIRTH", "MEMBER_ID",
        "GROUP_NUMBER", "MEDICAL_RECORD_NUMBER", "PHONE", "EMAIL",
        "PROVIDER_NAME", "OTHER_IDENTIFIER",
    ]
    # Canonical form of the person or value this text refers to, without titles
    # or credentials ('Jane Roe' for 'Dr. Jane Roe, MD'). Variants share it.
    refers_to: str


class PHIScan(BaseModel):
    entities: list[PHIEntity]


class CaseFacts(BaseModel):
    insurer_name: str
    denial_date: str  # YYYY-MM-DD
    request_or_claim_number: str
    service_requested: str
    service_codes: list[str]
    denial_reason_code: str
    denial_reason_summary: str
    policy_cited_by_insurer: str
    appeal_window_days: int
    expedited_appeal_available: bool
    appeals_mailing_address: str
    appeals_fax: str
    diagnoses: list[str]
    current_treatment: list[str]
    clinical_summary: str
    missing_information: list[str]


# ---- Planner --------------------------------------------------------------
Merit = Literal["strong", "possible", "weak"]


class RunPlan(BaseModel):
    merit: Merit  # honest odds that an appeal succeeds on this record
    merit_rationale: str
    alternatives: list[str]  # other routes to the care or coverage, instead of or alongside an appeal
    denial_category: Literal[
        "medical_necessity", "not_a_covered_benefit", "prior_authorization",
        "coding_or_billing", "out_of_network", "other",
    ]
    appeal_type: Literal["standard", "expedited"]
    appeal_type_rationale: str
    strategy: str
    policy_questions: list[str]
    research_questions: list[str]
    argument_hypotheses: list[str]
    risks: list[str]


# ---- Policy Analyst -------------------------------------------------------
class CriterionCheck(BaseModel):
    criterion_id: str
    criterion_text: str
    status: Literal["met", "not_met", "unclear"]
    supporting_fact: str
    source_ids: list[str]


class PolicyAnalysis(BaseModel):
    policy_identified: str
    insurer_rationale: str
    criteria: list[CriterionCheck]
    discrepancies: list[str]  # where the denial misreads or misapplies the policy
    procedural_issues: list[str]
    strongest_policy_argument: str
    merit: Merit  # judged from the criteria check alone
    merit_rationale: str


# ---- Evidence Researcher --------------------------------------------------
class EvidenceItem(BaseModel):
    source_id: str  # e.g. EV-1
    title: str
    publisher: str
    url: str
    finding: str  # what the source says, paraphrased
    relevance: str  # why it matters for this appeal


class EvidencePack(BaseModel):
    items: list[EvidenceItem]
    gaps: list[str]


# ---- Writer ---------------------------------------------------------------
class Claim(BaseModel):
    claim_id: str  # C1, C2, ...
    text: str
    source_ids: list[str]


class AppealDraft(BaseModel):
    subject_line: str
    letter_markdown: str
    claims: list[Claim]
    enclosures: list[str]


# ---- Adversarial Reviewer -------------------------------------------------
class ReviewVerdict(BaseModel):
    decision: Literal["approve", "revise"]
    score: int  # 1-10, how likely this letter is to win
    insurer_rebuttals: list[str]
    required_changes: list[str]
    strengths: list[str]


# ---- Fact Checker ---------------------------------------------------------
class ClaimCheck(BaseModel):
    claim_id: str
    supported: bool
    explanation: str


class FactCheckReport(BaseModel):
    checks: list[ClaimCheck]
    untracked_claims: list[str]  # factual statements in the letter that are not in the claims list and lack support
