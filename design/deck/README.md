# ClaimBack pitch deck

The pitch deck has 11 slides, in a clean, Apple-like style: white background, Geist type, lots of whitespace, light-green and gold accents. Most slides carry an inline SVG diagram (flow, timeline, chart) instead of text. The demo narration that goes with it is in [../demo-script.md](../demo-script.md). The script also maps every slide and scene to the jury criteria.

## Files

| File | What it is |
|---|---|
| `deck.json` | Slide order (`order`), outline sections and fonts |
| `slides/<id>.html` | One slide each: a single `<section>` on a 1920×1080 canvas with inline styles. The speaker notes are in the `<aside>` at the end |
| `index.html` | A browser viewer that shows every slide in order with its notes |
| `print.html` | Every slide at full 1920×1080, one per page, for PDF export (`?only=cover,product` renders a subset) |
| `assets/` | Real product screenshots used on the slides (see “Screenshots” below) |
| `export/` | `ClaimBack-deck.pdf` (16:9, one slide per page) and `ClaimBack-speaker-notes.pdf` (16:9, slide + timed notes per page) |

## View it

From the repo root:

```bash
python -m http.server 8000 -d design/deck
```

Then open http://localhost:8000. The viewer loads the files over HTTP, so opening `index.html` directly from disk won't work.

## Edit it

- **Text:** edit the slide's file in `slides/`, then reload the viewer. Keep the `<section id>` the same as the file name.
- **Speaker notes:** edit the `<aside>`, which must stay the last thing in the `<section>`. Each note starts with `[m:ss–m:ss · say]` (timings are computed from word count at 150 wpm) and the spoken script (about 150 words a minute, 3:00 in total), then `[Background, don’t read]` with the sources, caveats and details that were moved off the slide.
- **Keep slides sparse:** one short headline, one visual (a screenshot, a simple diagram or big numbers) and a few 2–4-word labels. Sources go in the notes, not on the slide. Explanations go in the notes.
- **Glyphs:** use only characters in Geist. Symbols like ✓, ⇄ and ≠ fall back to system fonts in the PDF; draw them as inline SVG or use words.
- **Export the PDF:** open `print.html` in Chrome or Brave and print to PDF (the page size is set to 1920×1080, no margins, background graphics on).
- **Reorder, add or remove a slide:** change `order` in `deck.json`. Add or delete the matching file in `slides/`.
- **Style rules:** these files are also the source of the presentable version, a Slides artifact on claude.ai. Keep every style inline (no classes, no `<style>`, no `margin`), and keep text at 24px or larger. Colors: white `#FFFFFF` background, near-black `#1D1D1F` text, grays `#6E6E73` / `#86868B` / `#A1A1A6` for secondary text, sources and slide numbers, light green `#E4F1EB` panels and `#CFE3DA` lines, teal `#6DBA9F` fills and `#2C8569` text for “built/approved”, gold `#E3A43B` fills and `#B07A1E` text for emphasis. Font: Geist everywhere (700 with tight tracking for headlines and hero numbers, 400–600 for body). Sentence case, no uppercase eyebrows; headlines centered. No footer: no source lines or slide numbers on the slides. Sources go in the speaker notes (“Source line (removed from the slide)” at the start of the background).

## Public link

The deck is published at https://neolorenzo.github.io/claimback/deck/ (GitHub Pages serves `docs/` from main), with the PDF at https://neolorenzo.github.io/claimback/deck/ClaimBack-deck.pdf. After editing slides, re-export the PDF, then rebuild the public copy:

```bash
python design/deck/publish.py
```

It inlines every slide into `docs/deck/index.html` with the speaker notes stripped (they stay private), copies only the images the slides use, and copies `export/ClaimBack-deck.pdf`. Commit `docs/deck/` and push to main to update the link.

## The presentable version

The presented deck is a claude.ai Slides artifact that was built from these files: https://claude.ai/artifact/BnDNbC45KgskAbtqW8mXjF. It has Present mode and exports to PDF and PPTX. It's private until its owner shares it from its Share menu. Changes made in the repo don't reach it automatically. To update it, ask Claude to publish the changed slide files to that artifact.

## Facts on the slides

Every product number comes from [EVALUATION.md](../../EVALUATION.md), [README.md](../../README.md) or [case-workflow-plan.md](../case-workflow-plan.md). Market and competitor sources are listed at the end of [demo-script.md](../demo-script.md). Keep that split when you edit:
- Milestones 1–4 are built and on GitHub (case store, Gmail connector, case worker, Correspondence agent, upload, follow-up reply, Approve & send with the allow-list, confirm outcome, case panel), plus the October 15 rehearsal fixes. Milestone 5’s end-to-end recording rehearsal isn’t finished.
- The insurer is simulated. Say so wherever it appears.
- The patient app is live at neolorenzo.github.io/claimback/app (GitHub Pages + Supabase + Modal): guest sign-in, synthetic documents only, Quick preview free, Full review capped per user per day.
- The merit verdict (Good chance / Worth trying / Unlikely to succeed) follows [merit-criteria.md](../merit-criteria.md) and `final_verdict` in `claimback/orchestrator.py`. It’s a judgment call, not calibrated on real outcomes; say so.
- Accuracy claims: use the wording in [accuracy.md](../accuracy.md) (“What the deck can say”); never “100% medically accurate”.
- Phone calls and reminders are roadmap. Don't present them as done.
- Pricing is a hypothesis: a success fee charged only after a confirmed win; the rate isn’t set yet. Don’t present a rate as decided.
- Insurer-AI claims (Cigna PXDX, the Senate report) are reporting and allegations; Cigna disputes ProPublica’s description. Keep that framing.

## Screenshots

| File | Source |
|---|---|
| `assets/replay-stats.png` | Public replay of run `cgm-denial-20261015-102913` (`docs/`), stats panel after the replay finishes |
| `assets/packet-at-a-glance.png` | The same run’s `packet.html`, “At a glance” section |
| `assets/packet-denial-reason.png` | The Denial reason cell of the same run’s packet (`docs/data/runs/cgm-denial-20261015-102913/packet.html`), rendered in light mode at 600 px wide and 2× scale so it wraps into a legible block (used on the product slide) |
| `assets/app-task.png` | The patient app (`docs/app/index.html`) at phone width (640 px, 2×) on Rosa’s test case after the simulated evidence request: “What we need from you”. Rendered locally from the app’s own code with a stand-in for Supabase that serves the demo case data (same task, quote and dates as `case-task.png`), so no account or job was created on the hosted backend (used on the casework slide) |
| `assets/packet-weak-verdict.png` | Run `test-weak-cgm-v2`’s packet, “Our assessment” (not on a slide right now) |
| `assets/case-correspondence.png`, `assets/case-task.png` | The real case panel (`python -m claimback serve`, **Cases** tab) on a case opened from a `--mock` run with the fake mailbox (`CLAIMBACK_MOCK=1`, `--fake`) after the simulated `ack` and `evidence-request` emails. Mock agents, so no API calls. Not on a slide right now (the casework slide uses `app-task.png`) |

Pages were zoomed (CSS zoom 1.3–1.6) before capture so the text stays legible on a 1920×1080 slide. Nothing in the screenshots was edited.
