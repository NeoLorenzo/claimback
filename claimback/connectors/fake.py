"""Local stand-in for a mailbox, for offline tests and rehearsal. Mail "sent"
to a case address lands in inbox/; anything else is kept in sent/."""
import re
from pathlib import Path

from .base import InboundEmail, OutboundEmail, parse

FAKE_DIR = Path(__file__).resolve().parent.parent.parent / "casefiles" / "_fake_mailbox"


class FakeConnector:
    name = "fake"

    def __init__(self, root: Path = FAKE_DIR):
        self.inbox, self.sent = root / "inbox", root / "sent"
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.sent.mkdir(parents=True, exist_ok=True)

    def fetch_new(self) -> list[InboundEmail]:
        return [parse(p.read_bytes()) for p in sorted(self.inbox.glob("*.eml"))]

    def send(self, mail: OutboundEmail) -> str:
        msg = mail.to_message()
        folder = self.inbox if "+cb-" in mail.to else self.sent
        safe = re.sub(r"[^A-Za-z0-9]+", "_", msg["Message-ID"]).strip("_")[:60]
        n = len(list(folder.glob("*.eml"))) + 1
        (folder / f"{n:04d}_{safe}.eml").write_bytes(bytes(msg))
        return msg["Message-ID"]
