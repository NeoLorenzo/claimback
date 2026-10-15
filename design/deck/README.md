# ClaimBack pitch deck

The pitch deck has 10 slides. The demo narration that goes with it is in [../demo-script.md](../demo-script.md). The script also maps every slide and scene to the jury criteria.

## Files

| File | What it is |
|---|---|
| `deck.json` | Slide order (`order`), outline sections and fonts |
| `slides/<id>.html` | One slide each: a single `<section>` on a 1920×1080 canvas with inline styles. The speaker notes are in the `<aside>` at the end |
| `index.html` | A browser viewer that shows every slide in order with its notes |

## View it

From the repo root:

```bash
python -m http.server 8000 -d design/deck
```

Then open http://localhost:8000. The viewer loads the files over HTTP, so opening `index.html` directly from disk won't work.

## Edit it

- **Text:** edit the slide's file in `slides/`, then reload the viewer. Keep the `<section id>` the same as the file name.
- **Speaker notes:** edit the `<aside>`, which must stay the last thing in the `<section>`.
- **Reorder, add or remove a slide:** change `order` in `deck.json`. Add or delete the matching file in `slides/`.
- **Style rules:** these files are also the source of the presentable version, a Slides artifact on claude.ai. Keep every style inline (no classes, no `<style>`, no `margin`), and keep text at 24px or larger. Colors: ink green `#0E2421`, paper `#F5F3EC`, green `#1F6F5C`, amber `#E39A3B` (amber on dark backgrounds only). Fonts: Source Serif 4 for headings, IBM Plex Sans for body text.

## The presentable version

The presented deck is a claude.ai Slides artifact that was built from these files: https://claude.ai/artifact/BnDNbC45KgskAbtqW8mXjF. It has Present mode and exports to PDF and PPTX. It's private until its owner shares it from its Share menu. Changes made in the repo don't reach it automatically. To update it, ask Claude to publish the changed slide files to that artifact.

## Facts on the slides

Every product number comes from [EVALUATION.md](../../EVALUATION.md), [README.md](../../README.md) or [case-workflow-plan.md](../case-workflow-plan.md). Market and competitor sources are listed at the end of [demo-script.md](../demo-script.md). Keep that split when you edit:
- Milestones 1–2 are built.
- Milestones 3–5 were in progress when the deck was written.
- Phone calls and reminders are roadmap. Don't present them as done.
- The $25 price is a hypothesis.
