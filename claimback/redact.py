"""PHI redaction. The Intake agent finds identifiers; this module swaps them for
placeholders and verifies nothing leaked. The placeholder map stays on local
disk and is only used by the Packager to fill in the final letter."""
import re

from .schemas import PHIScan

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


def build_map(scan: PHIScan, docs: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """Return ({original_text: placeholder}, {placeholder: display_value}).
    Every spelling of the same identifier ('Dr. Jane Roe, MD', 'Jane Roe')
    shares one placeholder, so agents don't mistake variants for different
    people. Display values are the canonical form used when filling back in."""
    mapping: dict[str, str] = {}
    display: dict[str, str] = {}
    by_canonical: dict[tuple[str, str], str] = {}
    counters: dict[str, int] = {}

    def placeholder_for(category: str, canonical: str) -> str:
        key = (category, canonical.casefold())
        if key not in by_canonical:
            counters[category] = counters.get(category, 0) + 1
            by_canonical[key] = f"[{category}_{counters[category]}]"
            display[by_canonical[key]] = canonical
        return by_canonical[key]

    for ent in sorted(scan.entities, key=lambda e: len(e.text), reverse=True):
        text = ent.text.strip()
        if len(text) < 3 or text in mapping:
            continue
        mapping[text] = placeholder_for(ent.category, _canonical(ent.category, text, ent.refers_to))
    # Deterministic backstop for patterns the model might miss
    for doc in docs.values():
        for m in EMAIL_RE.findall(doc) + SSN_RE.findall(doc):
            if m not in mapping:
                mapping[m] = placeholder_for("OTHER_IDENTIFIER", m)
    return mapping, display


NAME_CATEGORIES = {"PATIENT_NAME", "PROVIDER_NAME"}


def _canonical(category: str, text: str, refers_to: str | None) -> str:
    """Only name variants are merged, and only when the model's canonical name
    shares a word with the text ('Ms. Roe' -> 'Jane Roe'). Every other
    identifier keeps its own text, so a member ID is never filled back in as a name."""
    if category not in NAME_CATEGORIES or not refers_to:
        return text
    words = lambda s: {w for w in re.findall(r"[a-z]+", s.casefold()) if len(w) > 2}
    return refers_to.strip() if words(text) & words(refers_to) else text


def apply(text: str, mapping: dict[str, str]) -> str:
    for original in sorted(mapping, key=len, reverse=True):
        text = text.replace(original, mapping[original])
    return text


def leaks(text: str, mapping: dict[str, str]) -> list[str]:
    """Identifiers still present after redaction (should be empty)."""
    found = [o for o in mapping if o in text]
    found += EMAIL_RE.findall(text) + SSN_RE.findall(text)
    return found


def rehydrate(text: str, display: dict[str, str]) -> str:
    for placeholder, value in display.items():
        text = text.replace(placeholder, value)
        # Also catch tokens the writer embedded in its own brackets, e.g. "[PROVIDER_NAME_1 TO SIGN]"
        text = re.sub(rf"\b{re.escape(placeholder.strip('[]'))}\b", value, text)
    return text
