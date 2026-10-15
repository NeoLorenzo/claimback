"""Build the public copy of the deck in docs/deck/ (served by GitHub Pages at /claimback/deck/).

Every slide is inlined into one static page with its speaker notes stripped, so the notes
(sources, caveats, rehearsal guidance) stay private. Only the images the slides use are copied,
plus the exported PDF.

    python design/deck/publish.py
"""
import json
import re
import shutil
from pathlib import Path

DECK = Path(__file__).resolve().parent
OUT = DECK.parents[1] / "docs" / "deck"

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
{fonts}
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: #F4F6F1; color: #1D1D1F; font: 18px/1.5 'Geist', 'Helvetica Neue', Arial, sans-serif; }}
  header {{ max-width: 1240px; margin: 0 auto; padding: 28px 20px 8px; display: flex; justify-content: space-between; align-items: center; gap: 16px; flex-wrap: wrap; }}
  header h1 {{ font-size: 24px; margin: 0; }}
  header h1 span {{ color: #B07A1E; }}
  header a {{ color: #1D1D1F; font-weight: 600; text-decoration: none; border: 2px solid #CFE3DA; border-radius: 12px; padding: 10px 18px; background: #fff; }}
  main {{ max-width: 1240px; margin: 0 auto; padding: 12px 20px 64px; display: flex; flex-direction: column; gap: 24px; }}
  .frame {{ position: relative; width: 100%; aspect-ratio: 16 / 9; overflow: hidden; border-radius: 10px; border: 1px solid #DDE3DA; background: #fff; }}
  .frame > section {{ position: absolute; left: 0; top: 0; width: 1920px; height: 1080px; transform-origin: 0 0; overflow: hidden; }}
  section, section * {{ margin: 0; box-sizing: border-box; }}
  section h1, section h2, section h3 {{ font-weight: 600; }}
</style>
</head>
<body>
<header><h1>Claim<span>Back</span> pitch deck</h1><a href="ClaimBack-deck.pdf">Download PDF</a></header>
<main>
{slides}
</main>
<script>
function fit() {{
  for (const f of document.querySelectorAll(".frame")) f.firstElementChild.style.transform = `scale(${{f.clientWidth / 1920}})`;
}}
addEventListener("resize", fit);
fit();
</script>
</body>
</html>
"""


def main() -> None:
    deck = json.loads((DECK / "deck.json").read_text())
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "assets").mkdir(parents=True)
    slides = []
    for sid in deck["order"]:
        html = (DECK / "slides" / f"{sid}.html").read_text()
        html = re.sub(r"\s*<aside>.*?</aside>", "", html, flags=re.S)
        for src in re.findall(r'src="(assets/[^"]+)"', html):
            shutil.copy(DECK / src, OUT / src)
        slides.append(f'<div class="frame">{html.strip()}</div>')
    fonts = "\n".join(f'<link rel="stylesheet" href="{f["href"]}">' for f in deck.get("faces", {}).values() if f.get("href"))
    (OUT / "index.html").write_text(PAGE.format(title=deck["title"], fonts=fonts, slides="\n".join(slides)))
    shutil.copy(DECK / "export" / "ClaimBack-deck.pdf", OUT / "ClaimBack-deck.pdf")
    print(f"wrote {OUT.relative_to(DECK.parents[1])}/ ({len(slides)} slides)")


if __name__ == "__main__":
    main()
