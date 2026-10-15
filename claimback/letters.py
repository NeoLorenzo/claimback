"""Turning a drafted letter into an email that's safe to send: notes meant for
the human reviewer are split out, send-time dates are filled in, unfilled blanks
block sending, and the markdown is rendered as HTML with a plain-text twin."""
import html
import re
from datetime import datetime

import markdown as md

NOTE_MARKERS = re.compile(r"delete before sending|drafting note|reviewer note|note for the human reviewer|"
                          r"notes for (the )?human reviewer|for the human reviewer", re.IGNORECASE)
DATE_BLANKS = re.compile(r"\[(DATE(_OF)?_(LETTER|SIGNATURE|SIGNED|SENDING)|DATE_SIGNED|DATE|TODAY)\]", re.IGNORECASE)
# Bracketed text with a run of capitals, not a markdown link or checkbox: "[EXPEDITED / STANDARD - select one]"
BLANK = re.compile(r"\[(?=[^\]\n]*[A-Z]{3,})[^\]\n]{3,}\](?!\()")


def split_reviewer_notes(text: str) -> tuple[str, list[str]]:
    """Separate blocks addressed to the human reviewer from the letter itself."""
    blocks = re.split(r"\n\s*\n", text.strip())
    letter, notes, in_notes = [], [], False
    for block in blocks:
        stripped = block.strip()
        is_quote = stripped.startswith(">")
        heading_note = bool(re.match(r"^[*_#\s>\[]*" + NOTE_MARKERS.pattern, stripped, re.IGNORECASE))
        if NOTE_MARKERS.search(stripped) and (is_quote or stripped.startswith(("[", "*", "_")) or heading_note):
            notes.append(stripped)
            in_notes = stripped.endswith(":") or heading_note  # a notes heading: following list items are notes too
            continue
        if in_notes and re.match(r"^(\d+\.|[-*]|\s{2,}[-*])\s", stripped):
            notes.append(stripped)
            continue
        in_notes = False
        letter.append(block)
    clean = lambda s: re.sub(r"^>\s?", "", s, flags=re.MULTILINE).strip()
    return "\n\n".join(letter).strip() + "\n", [clean(n) for n in notes]


def fill_send_time(text: str, when: datetime | None = None) -> str:
    return DATE_BLANKS.sub((when or datetime.now()).strftime("%B %d, %Y"), text)


def unresolved_blanks(text: str) -> list[str]:
    seen = []
    for m in BLANK.findall(fill_send_time(text)):
        if m not in seen:
            seen.append(m)
    return seen


def to_html(text: str) -> str:
    # Escape first: the draft is model-written, and nothing in it should become live HTML
    return md.markdown(html.escape(text, quote=False), extensions=["tables"])


def to_plain(text: str) -> str:
    out = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), text)
    out = re.sub(r"(?m)^#{1,6}\s*", "", out)
    out = re.sub(r"(?m)^>\s?", "", out)
    out = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 (\2)", out)
    return out.strip() + "\n"
