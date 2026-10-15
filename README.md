# ClaimBack

**A team of Claude agents that turns a health-insurance denial letter into a ready-to-send appeal packet.**

Built for *Future Founders: Long Running Agents — From Task to Workflow*.

## The problem

Insurers deny a significant share of claims, and almost nobody fights back.

- In 2021, HealthCare.gov insurers denied **~17% of in-network claims**, with rates ranging from 2% to 49% depending on the insurer. ([KFF](https://www.kff.org/private-insurance/issue-brief/claims-denials-and-appeals-in-aca-marketplace-plans/))
- Patients appealed **fewer than 0.2%** of those denials. ([KFF](https://www.kff.org/private-insurance/issue-brief/claims-denials-and-appeals-in-aca-marketplace-plans/))
- Appeals are slow, confusing and deadline-driven. To write one, you have to read the denial reason, find the plan clause it relies on, collect clinical evidence, and write a formal argument, often while you're sick.

> TODO: refresh these figures with KFF's 2023/2024 updates before the pitch.

## Who it's for

1. **Patients and caregivers** who got a denial and don't know where to start.
2. **Clinic billing and revenue-cycle staff** who appeal denials every day by hand. This is the paying customer: every overturned denial is recovered revenue.

## The output (a real deliverable, not a mockup)

An **appeal packet** containing:

- an appeal letter addressed to the insurer, citing the plan language and the clinical evidence
- a list of the evidence relied on, with a source for every claim
- a deadline and submission checklist (internal appeal, then external review)
- a list of what the human still has to sign, attach or verify

## Agent team

```
Denial letter + plan docs + notes
        │
   [Orchestrator]  plans the run, tracks state, retries failed steps
        │
   ┌────┴─────────────┬──────────────────┐
[Intake/Redactor]  [Policy Analyst]  [Evidence Researcher]
 extracts facts,    finds the clause   finds clinical guidelines
 strips PHI         the denial uses    and medical-necessity support
   └────┬─────────────┴──────────────────┘
        │
     [Writer]  drafts the appeal
        │
 [Adversarial Reviewer]  plays the insurer and rejects weak arguments ──┐
        │                                                               │
        │◄──────────── revise (bounded loop) ◄──────────────────────────┘
        │
   [Fact Checker]  every claim must trace to a source document
        │
    [Packager]  letter + evidence list + checklist
```

**Handoffs:** each agent writes a typed artifact to a shared run-state file, and the next agent reads only what it needs.

**Error recovery:** the orchestrator retries failed steps. The reviewer-to-writer loop is capped. Any claim that fails the fact check is removed or flagged instead of being shipped.

**Long-running:** the run is checkpointed, so it can resume after a crash. Live logs show each agent's handoffs as they happen.

## Responsible design

- **Privacy:** PHI is redacted at intake, and downstream agents see placeholders. Data is processed locally and not stored after the run.
- **No fabrication:** the fact checker blocks any statement that isn't grounded in an uploaded document or a cited source.
- **Not medical or legal advice:** the packet is a draft that a human reviews and signs. ClaimBack never submits anything on its own.
- **Misuse:** ClaimBack only drafts appeals for documents the user provides. It refuses to invent diagnoses or treatments or to alter records.

## Status

Day-one hackathon build. Synthetic denial letters only; no real patient data.
