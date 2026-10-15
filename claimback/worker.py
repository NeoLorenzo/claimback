"""The case worker: a long-running loop that watches the ClaimBack mailbox and
moves each case forward. All progress lives in case.json, so stopping and
restarting it never loses or repeats work."""
import os
import time

from .cases import Case, all_cases, case_id_from_addresses, mailbox_address
from .correspondence import process_pending
from .connectors import InboundEmail, get_connector
from .log import emit


def _simulator_senders() -> set[str]:
    """Addresses allowed to send messages labeled as the simulated insurer."""
    senders = {mailbox_address().lower()}
    if os.environ.get("INSURER_SIM_EMAIL"):
        senders.add(os.environ["INSURER_SIM_EMAIL"].lower())
    return senders


def record_inbound(case: Case, m: InboundEmail) -> dict:
    n = sum(c["direction"] == "in" for c in case.correspondence) + 1
    cid = f"I{n}"
    inbox = case.dir / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / f"{cid}.eml").write_bytes(m.raw)  # raw mail stays on this machine
    saved = []
    for i, (name, data) in enumerate(m.attachments, 1):
        safe = "".join(ch for ch in name if ch.isalnum() or ch in "._-")[:60] or f"attachment{i}"
        (inbox / f"{cid}_{safe}").write_bytes(data)
        saved.append(f"inbox/{cid}_{safe}")

    on_list = m.from_addr in case.insurer_addresses
    # The simulated label is only honored from known simulator or insurer addresses: anyone can set a header
    simulated = m.simulated and m.from_addr in (_simulator_senders() | set(case.insurer_addresses))
    entry = {"id": cid, "direction": "in", "message_id": m.message_id, "from": m.from_addr,
             "subject": m.subject, "date": m.date, "simulated": simulated, "trusted_sender": on_list or simulated,
             "raw_file": f"inbox/{cid}.eml", "attachments": saved, "status": "received"}
    case.correspondence.append(entry)
    case.processed_message_ids.append(m.message_id)
    who = "simulated insurer" if simulated else m.from_addr
    case.emit("connector", "info", f"email {cid} received from {who}: “{m.subject}”"
              + (f" · {len(saved)} attachment(s)" if saved else ""),
              correspondence=cid, direction="in", simulated=simulated)
    if not entry["trusted_sender"]:
        case.emit("connector", "warn", f"{cid}: sender isn't on this case's insurer list; "
                                       "treated as untrusted until a human confirms it")
    case.save()
    return entry


def check_mailbox(connector) -> int:
    """One pass over the mailbox. Returns the number of new case messages."""
    new = 0
    for m in connector.fetch_new():
        case_id = case_id_from_addresses(m.to_addrs)
        if not case_id or not Case.exists(case_id):
            continue
        case = Case.load(case_id)
        if m.message_id in case.processed_message_ids:
            continue  # already handled, including before a restart
        record_inbound(case, m)
        new += 1
    return new


def advance_cases() -> int:
    """Read every received-but-unprocessed message on every open case."""
    n = 0
    for case in all_cases():
        if case.status != "closed" and any(c["direction"] == "in" and c["status"] == "received"
                                           for c in case.correspondence):
            n += process_pending(case)
    return n


def watch(interval: int = 20, once: bool = False) -> None:
    connector = get_connector()
    emit("case_worker", "start", f"watching the {connector.name} mailbox ({mailbox_address()}) every {interval}s")
    failures = 0
    while True:
        try:
            new = check_mailbox(connector)
            if new or once:
                emit("case_worker", "info", f"mailbox checked · {new} new case message(s)")
            advance_cases()
            failures = 0
        except Exception as e:  # network or login trouble: back off and try again
            failures += 1
            emit("case_worker", "retry", f"mailbox check failed ({type(e).__name__}: {str(e)[:120]}); "
                                         f"retrying in {min(interval * 2 ** failures, 300)}s")
            if once:
                raise
            time.sleep(min(interval * 2 ** failures, 300))
            continue
        if once:
            return
        time.sleep(interval)
