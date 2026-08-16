from unittest.mock import MagicMock

import pytest

from canopy.clients import gmail
from canopy.clients.gmail import GmailImapError


def _stub_imap_class(monkeypatch, mock_conn):
    monkeypatch.setattr(gmail.imaplib, "IMAP4_SSL", lambda host, port: mock_conn)


def _configured(monkeypatch):
    monkeypatch.setattr(gmail, "SMTP_USER", "zach@example.com")
    monkeypatch.setattr(gmail, "SMTP_PASS", "app-password")


def test_connect_raises_without_credentials(monkeypatch):
    monkeypatch.setattr(gmail, "SMTP_USER", "")
    monkeypatch.setattr(gmail, "SMTP_PASS", "")
    with pytest.raises(GmailImapError):
        gmail._connect()


def test_fetch_unprocessed_messages_returns_uid_and_raw_bytes(monkeypatch):
    _configured(monkeypatch)
    mock_conn = MagicMock()
    mock_conn.select.return_value = ("OK", [b"1"])
    mock_conn.uid.side_effect = [
        ("OK", [b"101 102"]),  # search
        ("OK", [(b"101 (RFC822 {10}", b"raw-message-1")]),  # fetch uid 101
        ("OK", [(b"102 (RFC822 {10}", b"raw-message-2")]),  # fetch uid 102
    ]
    _stub_imap_class(monkeypatch, mock_conn)

    messages = gmail.fetch_unprocessed_messages()

    assert messages == [(b"101", b"raw-message-1"), (b"102", b"raw-message-2")]
    mock_conn.login.assert_called_once_with("zach@example.com", "app-password")
    mock_conn.logout.assert_called_once()


def test_fetch_unprocessed_messages_skips_failed_fetch(monkeypatch):
    _configured(monkeypatch)
    mock_conn = MagicMock()
    mock_conn.select.return_value = ("OK", [b"1"])
    mock_conn.uid.side_effect = [
        ("OK", [b"101"]),
        ("NO", [None]),
    ]
    _stub_imap_class(monkeypatch, mock_conn)

    messages = gmail.fetch_unprocessed_messages()

    assert messages == []


def test_mark_processed_stores_custom_flag(monkeypatch):
    _configured(monkeypatch)
    mock_conn = MagicMock()
    mock_conn.select.return_value = ("OK", [b"1"])
    _stub_imap_class(monkeypatch, mock_conn)

    gmail.mark_processed(b"101")

    mock_conn.uid.assert_called_once_with("store", b"101", "+FLAGS", f"({gmail.PROCESSED_FLAG})")
    mock_conn.logout.assert_called_once()


def test_connect_raises_when_label_select_fails(monkeypatch):
    _configured(monkeypatch)
    mock_conn = MagicMock()
    mock_conn.select.return_value = ("NO", [b"label not found"])
    _stub_imap_class(monkeypatch, mock_conn)

    with pytest.raises(GmailImapError):
        gmail._connect()
