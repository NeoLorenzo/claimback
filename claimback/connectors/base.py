"""Shared email types and parsing."""
import email
import email.policy
import email.utils
from dataclasses import dataclass, field
from email.message import EmailMessage

SIM_HEADER = "X-ClaimBack-Simulated"


@dataclass
class InboundEmail:
    message_id: str
    from_addr: str
    to_addrs: list[str]
    subject: str
    date: str
    text: str
    simulated: bool
    raw: bytes
    attachments: list[tuple[str, bytes]] = field(default_factory=list)


@dataclass
class OutboundEmail:
    from_addr: str
    to: str
    subject: str
    body: str
    reply_to: str | None = None
    in_reply_to: str | None = None
    simulated: bool = False
    attachments: list[tuple[str, bytes, str]] = field(default_factory=list)  # (filename, data, mime type)
    message_id: str = ""

    def to_message(self) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = self.from_addr
        msg["To"] = self.to
        msg["Subject"] = self.subject
        msg["Date"] = email.utils.formatdate(localtime=True)
        msg["Message-ID"] = self.message_id or email.utils.make_msgid(domain="claimback.local")
        if self.reply_to:
            msg["Reply-To"] = self.reply_to
        if self.in_reply_to:
            msg["In-Reply-To"] = self.in_reply_to
            msg["References"] = self.in_reply_to
        if self.simulated:
            msg[SIM_HEADER] = "true"
        msg.set_content(self.body)
        for name, data, mime in self.attachments:
            maintype, _, subtype = mime.partition("/")
            msg.add_attachment(data, maintype=maintype, subtype=subtype or "octet-stream", filename=name)
        return msg


def parse(raw: bytes) -> InboundEmail:
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    to = [a for _, a in email.utils.getaddresses(
        msg.get_all("To", []) + msg.get_all("Cc", []) + msg.get_all("Delivered-To", []))]
    body = msg.get_body(preferencelist=("plain", "html"))
    text = body.get_content() if body else ""
    attachments = [(part.get_filename() or "attachment", part.get_payload(decode=True) or b"")
                   for part in msg.iter_attachments()]
    return InboundEmail(
        message_id=(msg.get("Message-ID") or "").strip() or email.utils.make_msgid(domain="claimback.missing"),
        from_addr=email.utils.parseaddr(msg.get("From", ""))[1].lower(),
        to_addrs=[a.lower() for a in to],
        subject=str(msg.get("Subject", "")),
        date=str(msg.get("Date", "")),
        text=text,
        simulated=str(msg.get(SIM_HEADER, "")).lower() == "true",
        raw=raw,
        attachments=attachments,
    )
