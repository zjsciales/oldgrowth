"""IMAP client for polling the Gmail label that collects Zillow alert
emails (see canopy/config.py's GMAIL_IMAP_LABEL). Uses stdlib imaplib/email
-- no new dependency.

Tracks what's already been ingested with a custom IMAP keyword flag
($CanopyProcessed) rather than Gmail's own \\Seen flag -- coupling
ingestion state to whether the user has personally read an alert on their
phone would silently stop ingestion the moment they do that.
"""

import imaplib
import logging

from canopy.config import GMAIL_IMAP_LABEL, SMTP_USER, SMTP_PASS

logger = logging.getLogger(__name__)

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
PROCESSED_FLAG = "CanopyProcessed"


class GmailImapError(RuntimeError):
    pass


def _connect() -> imaplib.IMAP4_SSL:
    if not SMTP_USER or not SMTP_PASS:
        raise GmailImapError("SMTP_USER/SMTP_PASS are not set (reused for IMAP login)")
    conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    conn.login(SMTP_USER, SMTP_PASS)
    status, _ = conn.select(f'"{GMAIL_IMAP_LABEL}"')
    if status != "OK":
        raise GmailImapError(f"could not select IMAP label {GMAIL_IMAP_LABEL!r}")
    return conn


def fetch_unprocessed_messages() -> list[tuple[bytes, bytes]]:
    """Returns a list of (uid, raw_message_bytes) for every message in the
    configured label that hasn't been marked processed yet."""
    conn = _connect()
    try:
        status, data = conn.uid("search", None, f"UNKEYWORD {PROCESSED_FLAG}")
        if status != "OK":
            raise GmailImapError("IMAP search failed")
        uids = data[0].split()

        messages: list[tuple[bytes, bytes]] = []
        for uid in uids:
            fetch_status, fetch_data = conn.uid("fetch", uid, "(RFC822)")
            if fetch_status != "OK" or not fetch_data or fetch_data[0] is None:
                logger.warning("gmail: failed to fetch uid %s, skipping", uid)
                continue
            raw = fetch_data[0][1]
            messages.append((uid, raw))
        logger.info("gmail: %d unprocessed messages in %s", len(messages), GMAIL_IMAP_LABEL)
        return messages
    finally:
        conn.logout()


def mark_processed(uid: bytes) -> None:
    conn = _connect()
    try:
        conn.uid("store", uid, "+FLAGS", f"({PROCESSED_FLAG})")
    finally:
        conn.logout()
