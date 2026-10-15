# Accuracy audit: ClaimBack against how US health insurance appeals actually work

Audited 2026-10-15 against primary regulations, Medicare coverage policy, the ADA Standards of Care 2026 and published imaging criteria. This document lists every rule and medical fact ClaimBack relies on, the source it was checked against, and what we changed.

## What the deck can say

> ClaimBack follows the US appeal rules for ACA and employer health plans: the 180-day appeal window, the 72-hour expedited track and external review. Its example cases are built on Medicare's actual CGM coverage criteria and the ADA's 2026 Standards of Care. Every rule and medical fact is checked against a cited primary source in our accuracy audit.

What it should **not** say: "100% medically accurate", or that ClaimBack's letters are legal or medical advice. The example patients, insurers and plan policies are synthetic (modeled on real criteria), and the letters are drafts a person checks and signs.

---

## 1. How a health insurance appeal works (ACA and employer plans)

```
claim or prior-authorization request
  → insurer denies it: the "adverse benefit determination" notice
  → internal appeal (filed within 180 days)
       decided in 72 h (urgent) · 30 days (before the service) · 60 days (after the service)
  → final internal decision
  → external review by an independent reviewer (requested within 4 months)
       decided in 45 days (standard) · 72 h (expedited); binding on the insurer
```

| Rule | What it says | Source |
|---|---|---|
| Time to appeal | At least **180 days** after receiving the denial notice | 29 CFR 2560.503-1(h)(3)(i); applied to insurers by 45 CFR 147.136(b) |
| Fresh review | No deference to the original decision; the reviewer isn't the original decision-maker or their subordinate | 2560.503-1(h)(3)(ii) |
| Clinical reviewer | For medical-judgment denials, the plan must consult a health professional with appropriate training and experience in that field | 2560.503-1(h)(3)(iii) |
| Your file | Free access to and copies of all documents relevant to the claim | 2560.503-1(h)(2)(iii) |
| New evidence | The plan must give you, free, any new evidence or rationale it uses, in time to respond before the final decision | 45 CFR 147.136(b)(2)(ii)(C) |
| Decision deadlines (group plans) | Urgent: **72 hours**. Pre-service: **30 days** (15 per level if two levels). Post-service: **60 days** (30 per level) | 2560.503-1(i)(2) |
| What counts as urgent | Standard timing "could seriously jeopardize the life or health of the claimant or the ability of the claimant to regain maximum function"; the plan must defer to the attending provider | 2560.503-1(m)(1); 147.136(b)(2)(ii)(B) |
| Appeal levels | Individual market: one internal level. Group plans: one or two | 147.136(b)(3)(ii)(G); HHS guidance |
| External review | Requested within **4 months** of receiving the denial; the federal process decides in **45 days** standard, with an expedited track | 147.136(d)(2)(i); CMS federal external review process |
| If the plan breaks the rules | The internal appeal is "deemed exhausted" and you can go straight to external review | 147.136(b)(2)(ii)(F) |

**What a denial notice must contain:**
- The specific reason, the plan provision and any criterion relied on, with a free copy available. For medical-necessity denials, the clinical judgment behind it (2560.503-1(g)(1)).
- Information identifying the claim, and that the diagnosis and treatment codes and their meanings are available on request.
- The denial code and its meaning.
- A description of the internal appeal and external review processes.
- The contact for the state's consumer assistance office (147.136(b)(2)(ii)(E)).

**Not covered by these rules:** Medicare (including Medicare Advantage) and Medicaid use their own appeal processes and timelines, and state laws can add protections. ClaimBack applies whatever the plan documents in a case say.

## 2. What an effective appeal letter contains

Drawn from the rules above and consumer and patient-advocate guides (see Sources). ClaimBack's Writer is instructed to produce each element.

| Element | Why | In ClaimBack |
|---|---|---|
| Member, claim or request number, service, dates | Lets the plan match the appeal to the claim | Header table in every letter |
| A clear request to overturn | States the outcome you want | Opening paragraph |
| The denial reason, quoted, and a direct answer to it | The reviewer decides against the stated reason | "The denial applies a requirement the Plan removed…" |
| The plan's own criteria, point by point | Appeals are decided against plan terms (section 1) | Criteria table: requirement and how it's met, with the source |
| Clinical facts from the records | Medical necessity rests on the documented record | Sourced to the notes; the Fact Checker verifies every claim |
| Letter of medical necessity from the treating clinician | Usually the most important attachment | Requested as an enclosure; uploaded and attached in the case flow |
| Supporting guidelines | Shows the care matches professional standards | ADA, CMS and ACR sources found by the Evidence Researcher |
| A request for the claim file, the criteria used and the reviewer's qualifications | You have the right to these (2560.503-1(h)(2)(iii), (h)(3)) | Requested in every initial appeal |
| The decision timeframe | Holds the plan to its deadline | "Decide within 30 days, or 72 hours if expedited" |
| Numbered enclosures and a signature | A complete, checkable submission | Enclosures list; signature left for the human |

## 3. Verification table

✓ = verified as already correct · **Fixed** = corrected in this audit.

### Appeal process in ClaimBack

| What ClaimBack uses | Status | Source |
|---|---|---|
| 180-day appeal deadline in the packet, counted conservatively from the notice date | ✓ (wording now explains the conservative count) | 2560.503-1(h)(3)(i) |
| Expedited appeal decided within 72 hours, offered when delay could seriously jeopardize health (Planner rule and packet) | ✓ | 2560.503-1(i)(2)(i), (m)(1) |
| Standard pre-service appeal decided within 30 days (synthetic plan documents, simulated insurer) | ✓ | 2560.503-1(i)(2)(ii) |
| External review within 4 months of the final internal denial | ✓ | 147.136(d)(2)(i) |
| Synthetic denial notices contain every required element | **Fixed**: added the codes-on-request statement, external review steps and the state consumer-assistance office (Oregon DFR, Washington OIC) to all four cases; added the denial code's meaning to `weak-cgm` | 147.136(b)(2)(ii)(E); 2560.503-1(g)(1) |
| Simulated final denial ("upheld") | **Fixed**: now says it's the final internal decision and includes free access to the criteria, the external review window, expedited external review and consumer assistance | Same |
| Packet checklist | **Added**: request your claim file and criteria (free); expedited appeal if urgent; external review within 4 months | 2560.503-1(h)(2)(iii); 147.136(d) |
| An insurer asking for records within 14 days during an appeal | ✓ realistic plan practice. The plan must still decide within its 30-day limit, so it asks for a quick response; no federal number is fixed | 2560.503-1(i)(2)(ii) |
| Peer-to-peer review offer (MRI case) | ✓ common plan practice, not a federal requirement | Plan practice; some states require a same or similar specialty reviewer |

### Glucose monitor (CGM) cases: `cgm-denial`, `weak-cgm`, `injection-cgm`

| What ClaimBack uses | Status | Source |
|---|---|---|
| Coverage criteria in synthetic policy MP-DME-031: diabetes; insulin-treated (any insulin) **or** problematic hypoglycemia; FDA indications; training; visit within 6 months; visit every 6 months to continue | ✓ mirrors Medicare's LCD | CMS LCD L33822 |
| The 2026 policy revision that removed "3+ injections" (the error in the strong case's denial) | ✓ mirrors the real Medicare change effective 04/16/2023 | L33822 revision history |
| Problematic hypoglycemia: recurrent (more than one) level 2 events < 54 mg/dL persisting despite multiple adjustment attempts, or one level 3 event needing assistance | ✓ | L33822; ADA 2026 Section 6 |
| Codes: E2103 (non-adjunctive CGM monitor or receiver), A4239 (its monthly supply allowance) | ✓ | L33822; Noridian supply allowance article |
| Diagnosis codes: E11.65, E11.649, E11.42, Z79.4 | ✓ | ICD-10-CM |
| Insulin plus oral diabetes drugs (glargine with metformin and empagliflozin) | **Fixed**: added Z79.84 next to Z79.4, as current coding guidance requires for both; added Z79.84 for metformin-only `weak-cgm` | ICD-10-CM guidelines I.C.4.a.3 (FY2022 onward) |
| ADA 2026: CGM recommended for adults on insulin from diagnosis onward | ✓ Rec 7.15 and Rec 9.25 | ADA Standards of Care 2026, Summary of Revisions |
| ADA 2026: older adults with type 2 diabetes on insulin → CGM | ✓ Rec 13.5 | Same |
| ADA 2026: consider CGM for type 2 diabetes on basal insulin | ✓ Figure 9.5 | Same |
| Over-the-counter CGM as an alternative for people not on insulin (weak case) | ✓ a recognized device type | ADA 2026 Table 7.3 |
| Offline reference library | **Fixed**: updated from the 2025 to the 2026 Standards, with recommendation numbers, DOIs and the full LCD criteria | Same |
| Clinical picture: basal insulin, A1c 9.1%, two nocturnal lows of 48 and 51 mg/dL after a dose cut, neuropathy limiting fingersticks, lives alone | ✓ internally consistent: meets I.B.1 (insulin-treated); I.B.2.a arguable but not needed (only one dose adjustment); the agents flag exactly this | L33822 logic |

### Back MRI case: `mri-red-flag`

| What ClaimBack uses | Status | Source |
|---|---|---|
| CPT 72148, MRI lumbar spine without contrast | ✓ | CPT |
| Plan rule: 6 weeks of conservative therapy first, unless there are red flags such as a progressive neurological deficit | ✓ standard in imaging guidelines | ACR Appropriateness Criteria, Low Back Pain |
| Red flag → MRI without contrast rated "usually appropriate" | ✓ | ACR, as summarized by Applied Radiology |
| Exam: weaker ankle dorsiflexion and great toe extension, numbness on the top of the foot, foot slap, normal reflexes | ✓ consistent with an L5 radiculopathy; there's no reliable L5 reflex, so normal reflexes fit | Standard neurology |

### Market numbers in the deck

| Claim | Status | Source |
|---|---|---|
| 19% of in-network HealthCare.gov claims denied in 2024 (about 85 million); fewer than 1% of denials appealed; insurers upheld 66% of internal appeals | ✓ | KFF, March 2026 |
| README's older figures (17%, under 0.2% appealed, 2021 data) | ✓ for 2021; the deck uses the newer 2024 report | KFF 2021 brief |

## 4. What is synthetic, and what a human still checks

- **Synthetic:** all patients, insurers (Evergreen Mutual, Pinecrest Health Alliance), plan policies (modeled on the real criteria above) and clinicians. Every case document is marked `SYNTHETIC TEST DOCUMENT`, and the public site refuses anything that isn't. The scripted insurer's emails are labelled simulated.
- **Generated per run:** letters and evidence lists. The Fact Checker verifies every claim against the documents and the sources the Evidence Researcher retrieved. It can't open a journal article itself, so the packet asks the human to confirm citations before sending. Alternatives on weak cases (for example, over-the-counter CGM prices) are marked as not fact-checked.
- **Varies by state and plan type:** external review bodies, extra state protections, and Medicare and Medicaid processes. ClaimBack follows the documents provided and says when to check.
- **Not advice:** every packet is a draft for a person to read, correct, sign and send.

## Sources

- [29 CFR 2560.503-1, ERISA claims procedure (Cornell LII)](https://www.law.cornell.edu/cfr/text/29/2560.503-1)
- [45 CFR 147.136, internal claims, appeals and external review (Cornell LII)](https://www.law.cornell.edu/cfr/text/45/147.136)
- [CMS: HHS-administered federal external review process](https://www.cms.gov/CCIIO/Programs-and-Initiatives/Consumer-Support-and-Information/csg-ext-appeals-facts.html)
- [HHS appeals presentation (levels of appeal, timeframes)](https://www.hhs.gov/guidance/sites/default/files/hhs-guidance-documents/Appeals%20presentation%204.2.18_comments%20incorp_CMS%20%28002%29_508_Final.pdf)
- [CMS LCD L33822, Glucose Monitors](https://www.cms.gov/medicare-coverage-database/view/lcd.aspx?lcdid=33822)
- [Noridian: CGM supply allowance](https://med.noridianmedicare.com/web/jadme/article-detail/-/view/6547796/continuous-glucose-monitors-cgms-supply-allowance)
- [ADA Standards of Care in Diabetes 2026: Summary of Revisions (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC12690167)
- [ICD-10-CM guidance: long-term insulin and oral hypoglycemics (IKS Health)](https://ikshealth.com/insights/cracking-the-code/updated-guidance-for-reporting-long-term-use-of-insulin-and-oral-hypoglycemic-medication/)
- [Applied Radiology: ACR Appropriateness Criteria for low back pain](https://appliedradiology.com/articles/an-image-based-review-of-the-acr-appropriateness-criteria-for-low-back-pain)
- [KFF: Claims denials and appeals in ACA Marketplace plans in 2024](https://www.kff.org/health-reform/report/claims-denials-and-appeals-in-aca-marketplace-plans-in-2024/)
- Appeal-letter guides: [Patient Advocate Foundation](https://www.patientadvocate.org/wp-content/uploads/EP-Tips-for-Appealing-Insurance-Denials-1.pdf), [Memorial Sloan Kettering](https://www.mskcc.org/insurance-assistance/insurance-information/steps-take-if-denied-coverage), [GoodRx](https://www.goodrx.com/insurance/health-insurance/writing-a-health-insurance-appeal-letter)
