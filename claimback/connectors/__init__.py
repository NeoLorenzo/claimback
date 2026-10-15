"""Email connectors. Both implement the same interface:

  fetch_new() -> list[InboundEmail]   only mail addressed to a case (+cb-) address
  send(OutboundEmail) -> str          returns the Message-ID that was sent

`get_connector()` picks the real IMAP/SMTP connector when credentials are in
.env, and the local FakeConnector otherwise (or when CLAIMBACK_FAKE_MAIL=1)."""
import os

from .base import InboundEmail, OutboundEmail  # noqa: F401


def get_connector():
    from .. import llm  # noqa: F401  loads .env
    if os.environ.get("CLAIMBACK_FAKE_MAIL") != "1" and os.environ.get("CLAIMBACK_EMAIL_APP_PASSWORD"):
        from .email_imap import IMAPConnector
        # Google displays app passwords in groups of four; the spaces aren't part of it
        return IMAPConnector(os.environ["CLAIMBACK_EMAIL"].strip(),
                             os.environ["CLAIMBACK_EMAIL_APP_PASSWORD"].replace(" ", ""))
    from .fake import FakeConnector
    return FakeConnector()
