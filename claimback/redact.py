"""PHI redaction. The Intake agent finds identifiers; this module swaps them for
placeholders and verifies nothing leaked. The placeholder map stays on local
disk and is only used by the Packager to fill in the final letter."""
import re

from .schemas import PHIScan

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


def build_map(scan: PHIScan, docs: dict[str, str]) -> dict[str, str]:
    """Return {original_text: placeholder}. Longest strings first, so a full
    name is replaced before a surname on its own."""
    mapping: dict[str, str] = {}
    counters: dict[str, int] = {}
    entities = sorted(scan.entities, key=lambda e: len(e.text), reverse=True)
    for ent in entities:
        text = ent.text.strip()
        if len(text) < 3 or text in mapping:
            continue
        counters[ent.category] = counters.get(ent.category, 0) + 1
        mapping[text] = f"[{ent.category}_{counters[ent.category]}]"
    # Deterministic backstop for patterns the model might miss
    for doc in docs.values():
        for m in EMAIL_RE.findall(doc) + SSN_RE.findall(doc):
            if m not in mapping:
                counters["OTHER_IDENTIFIER"] = counters.get("OTHER_IDENTIFIER", 0) + 1
                mapping[m] = f"[OTHER_IDENTIFIER_{counters['OTHER_IDENTIFIER']}]"
    return mapping


def apply(text: str, mapping: dict[str, str]) -> str:
    for original in sorted(mapping, key=len, reverse=True):
        text = text.replace(original, mapping[original])
    return text


def leaks(text: str, mapping: dict[str, str]) -> list[str]:
    """Identifiers still present after redaction (should be empty)."""
    found = [o for o in mapping if o in text]
    found += EMAIL_RE.findall(text) + SSN_RE.findall(text)
    return found


def rehydrate(text: str, mapping: dict[str, str]) -> str:
    for original, placeholder in mapping.items():
        text = text.replace(placeholder, original)
    return text
