# Pitch script: bullet points (about 3 minutes)

Follows the 11 slides in `design/deck` (public copy: neolorenzo.github.io/claimback/deck/). Timings come from the deck's speaker notes.

**1. Cover (0:00–0:18)**
- When people appeal an insurance denial, most win: 81% in Medicare Advantage.
- But almost nobody appeals. Nearly 9 in 10 denials just stand.
- ClaimBack is a team of AI agents that fights those denials.

**2. The gap (0:18–0:34)**
- Insurers deny at machine speed; patients appeal by hand.
- ProPublica reported Cigna doctors spending about 1.2 seconds per denial (Cigna disputes this).
- Fighting one denial means paperwork and rounds of review that can take six months.

**3. Market (0:34–0:50)**
- Private insurers deny about 450 million claims a year.
- Fighting each one costs about $44, so providers spend nearly $20B a year.
- Hospitals pay teams to fight. Patients fight alone.

**4. Rosa (0:50–1:08)**
- Meet Rosa: 65, type 2 diabetes, lives alone.
- Her blood sugar crashes at night, which can mean confusion, a fall or a seizure.
- Her doctor prescribed a glucose monitor whose alarm wakes her.
- Her insurer denied it: "3+ insulin shots a day". But the insurer removed that rule in January.

**5. The agent team (1:08–1:19)**
- Seven Claude agents take Rosa's case.
- Intake strips her personal details before anyone else sees the case.
- The Policy Analyst and Evidence Researcher work in parallel, and the Policy Analyst catches the removed rule.

**6. The insurer's side (1:19–1:37)**
- One agent plays the insurer and tries to reject the letter before the real insurer can.
- In Rosa's run it found four weak spots, for example that the letter never named the device.
- Draft two fixed them and passed, with all 42 facts checked against her records and the policy.

**7. Three judges (1:37–1:54)**
- Before anything is sent, three agents judge the odds against the plan's own rules.
- All three must agree to say "good chance"; any one can say "unlikely".
- Every rule and medical fact is checked against federal appeal law, Medicare's criteria and the ADA's 2026 guidelines.

**8. What Rosa gets (1:54–2:10)**
- An appeal ready to sign, straight from the real run.
- It points out the insurer's mistake and tells her the deadline.
- A person always signs and sends it.

**9. It keeps working (2:10–2:28)**
- It works the case for weeks in a real Gmail inbox.
- A receipt isn't a decision, so it keeps waiting.
- An evidence request becomes a task with the insurer's own deadline.
- Nothing closes until Rosa confirms. (The insurer here is our labelled simulator.)

**10. Results (2:28–2:45)**
- Tested live, at about $3 per appeal.
- Rosa's case passed. A new denial type, a back MRI, worked.
- A planted fake hospitalization was flagged and nothing was invented.
- When the denial was right, it said so and stopped early.
- So far every case is synthetic.

**11. The ask (2:45–2:58)**
- We get paid only when an appeal wins: a free merit check, then a success fee after a confirmed win.
- ClaimBack: the agents do the work. People decide.
