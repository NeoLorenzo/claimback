"""Real mailbox over IMAP (read) and SMTP (send) with an app password.
Only messages addressed to a case plus address are ever downloaded."""
import imaplib
import smtplib

from .base import InboundEmail, OutboundEmail, parse


class IMAPConnector:
    name = "imap"

    def __init__(self, address: str, app_password: str,
                 imap_host: str = "imap.gmail.com", smtp_host: str = "smtp.gmail.com"):
        self.address, self._password = address, app_password
        self.imap_host, self.smtp_host = imap_host, smtp_host

    def fetch_new(self) -> list[InboundEmail]:
        local = self.address.split("@")[0]
        out = []
        with imaplib.IMAP4_SSL(self.imap_host) as imap:
            imap.login(self.address, self._password)
            imap.select("INBOX", readonly=True)  # never changes the mailbox; dedupe is by Message-ID
            status, data = imap.search(None, "TO", f'"{local}+cb-"')
            if status != "OK":
                return []
            for num in data[0].split()[-200:]:  # most recent 200 case messages
                status, parts = imap.fetch(num, "(BODY.PEEK[])")
                if status == "OK" and parts and isinstance(parts[0], tuple):
                    out.append(parse(parts[0][1]))
        return out

    def send(self, mail: OutboundEmail) -> str:
        msg = mail.to_message()
        with smtplib.SMTP_SSL(self.smtp_host, 465) as smtp:
            smtp.login(self.address, self._password)
            smtp.send_message(msg)
        return msg["Message-ID"]
