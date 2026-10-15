# ClaimBack demo script (pre-recorded, about 2:50)

Four scenes, each mapped to the jury criteria. It's recorded in advance: a run takes about 10 minutes and a case takes weeks. We speed up the agent log and label every time jump on screen. Narration runs about 150 words a minute. Every product claim below comes from the repo: [README.md](../README.md), [EVALUATION.md](../EVALUATION.md), [case-workflow-plan.md](case-workflow-plan.md) and the recorded runs.

Jury criteria: ① real output, not a mockup · ② agent design (planning, handoffs, error recovery) · ③ business viability · ④ demo with live agent logs or a sped-up recording · ⑤ demo clarity · ⑥ responsible design (safety, privacy, misuse).

| Time | Scene | Criteria |
|---|---|---|
| 0:00–0:50 | A. Agent timeline replay, strong case | ② ④ ⑤ ⑥ |
| 0:50–1:15 | B. The packet: "Our assessment" + "At a glance" | ① ⑤ |
| 1:15–1:40 | C. Weak case: we tell you when not to appeal | ① ② ⑥ |
| 1:40–2:50 | D. Long-running case in a real Gmail inbox | ① ② ④ ⑥ (and ③: this is what a clinic pays for) |

---

## Before recording

1. **Re-record the strong run with the merit verdict.** The run on Pages (`cgm-denial-20261015-102913`) is from before the merit verdict, so its packet has no "Our assessment" section and the verdict tile stays blank. Re-run it with chaos, kill it during draft 2, then resume (about 10 min, about $2.80):
   ```bash
   python -m claimback run cases/cgm-denial --chaos --run-id cgm-demo
   ```
   Press Ctrl-C after `writer · draft_2 (attempt 1/3)` appears, then:
   ```bash
   python -m claimback resume cgm-demo
   ```
   Publish it next to the weak run. The first run listed auto-plays. Then commit and push `docs/`:
   ```bash
   python -m claimback export-site cgm-demo test-weak-cgm-v2
   ```
   *If the new run is approved in round 1,* keep the old recording for scene A and use only the new packet in scene B. Then cut the "sends it back" line from the narration. *If there's no time to re-run,* show "At a glance" from the current packet and "Our assessment" only in scene C.
2. **Mailbox.** `.env` has `CLAIMBACK_EMAIL` and `CLAIMBACK_EMAIL_APP_PASSWORD` for the dedicated ClaimBack Gmail account. Optionally add `INSURER_SIM_EMAIL` and `INSURER_SIM_APP_PASSWORD` so the insurer has its own address. Never use a personal inbox.
3. **Open the case** from the strong run and note the `case_id` it prints:
   ```bash
   python -m claimback open-case cgm-demo
   ```
4. **Two terminals, both left running.** In the first:
   ```bash
   python -m claimback serve
   ```
   In the second:
   ```bash
   python -m claimback watch --interval 10
   ```
   Keep a third terminal free for the simulator.
5. **Browser.** Tab 1: http://127.0.0.1:8765. Allow notifications when asked. Tab 2: the ClaimBack Gmail inbox. Tab 3: https://neolorenzo.github.io/claimback/. Record at 1920×1080 with the browser at 125% zoom. Hide bookmarks and any personal tabs.
6. **Dry run** scene D with the fake mailbox (`--fake` on `open-case`, `watch`, `simulate-insurer`, `approve`) so the real inbox only gets the takes you record.
7. **Check the case panel labels** against this script. The panel (milestones 3–4) was still being built when this was written. The labels used here are from that work in progress: **Cases** tab, **Waiting for you**, **Upload document**, **Approve & send**, **Confirm outcome**, the "simulated insurer" badge.

**Honesty rules for the edit:** Caption every time jump. Leave the "SIMULATED INSURER MESSAGE" line visible whenever an insurer email is on screen. Don't cut away an error the agents recovered from. Show the recovery instead.

---

## Scene A: the agent timeline (0:00–0:50) · ② ④ ⑤ ⑥

**On screen:** The Pages replay, tab 3. The workflow diagram fills the left side, the live log runs underneath, and the stats are on the right: run time, model calls, tokens, est. cost, failures recovered, claims verified, reviewer score.
**Caption:** *Real run · synthetic patient · replayed from the agent log at 25×*

**Click:** Pick the `cgm-demo` run (or `cgm-denial-20261015-102913`) in the run picker → set speed to **25×** → **Replay**. Press **Pause** at each beat below and **Replay** again to go on, or speed-ramp in the edit.

| Beat | On screen | Narration |
|---|---|---|
| A1 | Title card, then the diagram at rest | "Insurers deny about one in five claims. Fewer than one in a hundred denials get appealed. ClaimBack is a team of Claude agents that writes the appeal, then works the case." |
| A2 | Intake lights up. The log reads `redacted 10 identifier strings · leak check passed` | "This is a real run, replayed from its log. Intake strips the patient's identifiers before any other agent sees the case." |
| A3 | Planner → Policy Analyst and Evidence Researcher light up together. Two red `retry` rows appear (`simulated API timeout`, `simulated web search outage`) | "The Planner sets the strategy. Two analysts work in parallel. We inject failures on purpose, and each one is retried and recovered." |
| A4 | The `resuming run` row, then `restored from checkpoint` rows. *Failures recovered* reaches 3 | "We even killed the process mid-draft. It resumed from its checkpoint without redoing any work." |
| A5 | Writer ⇄ Reviewer loop animates. `score 9/10 · revise · 4 required changes`, then `round 1 not approved → back to writer`, then `42/42 claims verified` | "The Adversarial Reviewer plays the insurer and sends draft one back with four changes. Draft two passes, and the Fact Checker traces all forty-two claims to a source." |

## Scene B: the packet (0:50–1:15) · ① ⑤

**On screen:** The appeal packet: "Our assessment" at the top, then the "At a glance" table.
**Click:** In the right panel, click **Output → Appeal packet**. It opens `packet.html`. Scroll slowly from the top to "Before you send".
**Caption:** *The real output: printable, a human signs and sends it*

| Beat | On screen | Narration |
|---|---|---|
| B1 | "Our assessment: Strong case: we recommend appealing", with the Planner, Policy Analyst and Reviewer lines | "The output is a packet a person can sign and send. It opens with our honest assessment. Three agents rate the case, and here they say: appeal." *(Read the verdict the re-recorded run actually gives.)* |
| B2 | "At a glance": the denial reason row with the 01/01/2026 note, appeal type, **March 21, 2027**, send-to | "At a glance: the insurer applied a rule the plan removed in January. Expedited appeal, the deadline, where to send it, and a checklist of what to sign and attach." |

## Scene C: when not to appeal (1:15–1:40) · ① ② ⑥

**On screen:** The weak run's replay: the verdict tile turns **Weak** and the log shows `reviewer scored 2/10 → stopping revisions`. Then its packet: "Appeal assessment · Weak case: this appeal is unlikely to succeed" and "Better options to try first".
**Click:** Run picker → `test-weak-cgm-v2` → speed **60×** → **Replay**. When it finishes, click **Output → Appeal packet**.
**Caption:** *Same agents, a denial that is correct*

| Beat | On screen | Narration |
|---|---|---|
| C1 | Replay. The `merit: weak` rows from the Planner and the Policy Analyst, then `score 2/10` | "Not every denial is wrong. This patient isn't on insulin and has never had a low, so the plan's rules aren't met. Two agents rate it weak, and the reviewer gives the draft two out of ten." |
| C2 | Packet top: the Weak verdict and the alternatives list | "So the team stops after one round, for about a dollar forty, and says it plainly: this appeal is unlikely to succeed. Here's what to try instead." |

## Scene D: the long-running case (1:40–2:50) · ① ② ④ ⑥ ③

**On screen:** The local web view, tab 1, on the **Cases** tab, with the case for `cgm-demo` selected. On the left is the case list. The main panel shows the status pill, the **Waiting for you** banner and its tasks, the correspondence timeline, the outbox draft with its recipient, and the case log. The Gmail inbox is in tab 2.
**Caption at the start:** *Case worker watching a real Gmail inbox · insurer messages come from a scripted simulator and are labeled SIMULATED*

| Beat | Caption | Do this | On screen | Narration |
|---|---|---|---|---|
| D1 | *Day 0* | Click **Cases**, then the case. In the outbox draft, check the recipient, then click **Approve & send** | The status changes from **Waiting for you** to **Waiting for insurer**. The log shows `sent O1 to …`. Cut to Gmail: the appeal in Sent | "An appeal isn't one letter. It's weeks of back-and-forth. ClaimBack opens a case with its own reply address. Nothing leaves without a person, so I approve the appeal, and it's sent." |
| D2 | *3 days later* | Terminal 3: `python -m claimback simulate-insurer <case_id> ack` | Gmail: "Appeal received", with the SIMULATED line on top. Back in the case: the email arrives with the **simulated insurer** badge. The Correspondence agent reads it: *acknowledgment … not a decision*. The status stays **Waiting for insurer** | "The insurer replies. This is our labeled simulator. The Correspondence agent reads the email after redaction: it's an acknowledgment, not a decision, so the case keeps waiting." |
| D3 | *5 days later* | `python -m claimback simulate-insurer <case_id> evidence-request` | Gmail: "Additional information needed". In the case: two tasks with due dates 14 days out, the **Waiting for you** banner and the tab badge. The browser notification says "Action needed on your ClaimBack case" | "Now they want a letter of medical necessity and glucose readings within fourteen days. That becomes two tasks with deadlines checked against the email, plus a notification with no medical details." |
| D4 | *Same day* | On each task, click **Upload document** and pick `cases/cgm-denial/evidence/letter_of_medical_necessity.txt`, then `cases/cgm-denial/evidence/glucose_meter_log.txt`. When the draft shows **Needs your approval**, check the recipient and click **Approve & send** | The log shows `drafting the reply to I2 with 2 enclosure(s)`, then `N/N claims verified`, then `Waiting for you: a fact-checked reply is ready to approve`. The draft preview shows its To: line. After sending: `sent O2 …` | "I upload the doctor's letter and the meter log. The Writer drafts the reply and the Fact Checker verifies it. I approve it, and it can only go to the insurer on this case." |
| D5 | *2 weeks later* | `python -m claimback simulate-insurer <case_id> overturned`. When the **Confirm outcome** task appears, click it | Gmail: "Appeal decision … OVERTURNED". In the case: *decision (overturned)*, then the **Confirm outcome** task. After the click: status **Closed**, `case closed · outcome: … (confirmed by you)` | "Denial overturned. ClaimBack won't close the case on its own word. I confirm, and it closes with every message, task and deadline on the record." |
| End | — | Hold on the closed case, then end card: repo + replay URLs | — | "ClaimBack: the agents do the work, and people make the decisions." |

**CLI fallback for D4–D5** if a button misbehaves on the day. Get the task and outbox ids from `python -m claimback cases` or the panel:
```bash
python -m claimback upload <case_id> <task_id> cases/cgm-denial/evidence/letter_of_medical_necessity.txt
```
```bash
python -m claimback approve <case_id> <outbox_id>
```
```bash
python -m claimback confirm <case_id> <task_id>
```

**What's real vs. simulated (say it if asked, and keep it in the video description):** The Gmail inbox, IMAP fetch, SMTP send, redaction, Correspondence agent, Writer and Fact Checker are real and use live model calls. The insurer is a script that sends real email marked `X-ClaimBack-Simulated: true`. Its dates are the recording date. The on-screen captions show how long each step takes in real life.

---

## Deck ↔ jury criteria

The deck: https://claude.ai/artifact/BnDNbC45KgskAbtqW8mXjF. The editable source is in [deck/](deck/README.md).

| # | Slide | Criteria |
|---|---|---|
| 1 | Insurers deny 1 in 5 claims; fewer than 1 in 100 denials are appealed (KFF 2024 data) | ③ |
| 2 | Customer: clinic billing teams pay; patients get the same help (Premier 2024) | ③ |
| 3 | Product: what one run produces (real "At a glance" values) | ① |
| 4 | Agent architecture: planning, handoffs, error recovery | ② |
| 5 | Long-running case workflow (built vs. in progress, roadmap labeled) | ② |
| 6 | The demo: four scenes | ④ ⑤ |
| 7 | Results and evaluation: five live tests, time and cost | ① ② ⑥ |
| 8 | Responsible design, including the known gaps | ⑥ |
| 9 | Business model and competition | ③ |
| 10 | The ask and next steps | ③ ⑥ |

## Sources behind the numbers

- KFF, [Claims Denials and Appeals in ACA Marketplace Plans in 2024](https://www.kff.org/patient-consumer-protections/claims-denials-and-appeals-in-aca-marketplace-plans-in-2024/) (March 24, 2026): 19% of in-network claims denied (about 85M); fewer than 1% of denied claims appealed; 66% of internal appeals upheld; 5,881 external appeals.
- KFF, [Medicare Advantage Insurers Made Nearly 53 Million Prior Authorization Determinations in 2024](https://www.kff.org/medicare/medicare-advantage-insurers-made-nearly-53-million-prior-authorization-determinations-in-2024/): 80.7% of appealed denials fully or partially overturned.
- Premier Inc., [Trend alert: private payers retain profits by refusing or delaying legitimate medical claims](https://premierinc.com/newsroom/blog/trend-alert-private-payers-retain-profits-by-refusing-or-delaying-legitimate-medical-claims) (March 21, 2024): $19.7B a year spent fighting denials; $43.84 average cost per denied claim; 54.3% of private-payer denials eventually paid after multiple rounds.
- Competitors, checked on their own sites in October 2026: [Claimable](https://www.getclaimable.com/) ($39.95 per appeal, 85+ drugs, mails and faxes appeals and tracks them); [Counterforce Health](https://www.counterforcehealth.org/) (free, grant-funded, appeal letters, voice assistant in beta); [Fight Health Insurance](https://www.fighthealthinsurance.com/) (free or pay what you want, several drafts, on-device OCR); [Waystar AltitudeAI](https://investors.waystar.com/news-releases/news-release-details/waystar-advances-ai-leadership-next-generation-denial-prevention) (enterprise revenue-cycle software, bulk appeal packages). Their success rates are self-reported, so the deck doesn't compare against them.
- Model cost per run: $1.39–$3.10, measured in [EVALUATION.md](../EVALUATION.md). The $25-per-appeal price is a hypothesis to test in pilots.
