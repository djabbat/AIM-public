"""agents/email_agent.py — Gmail integration for AIM.

Uses google-api-python-client with OAuth2; reuses ~/.aim_env credentials:

    GMAIL_CLIENT_SECRET_PATH=~/.aim_env/gmail_client_secret.json
    GMAIL_TOKEN_PATH=~/.aim_env/gmail_token.json

On first run, opens a local browser flow (or prints a URL for SSH boxes).
After consent the token is cached and refreshed automatically.

Public API:
    list_threads(q="newer_than:7d", n=20)   → list[dict]
    get_thread(thread_id)                   → dict
    search(query, n=20)                     → list[dict]
    draft(to, subject, body, *,             → dict   (NOT sent)
          thread_id=None, cc=None, bcc=None)
    send(to, subject, body, *,              → dict   (sent)
         thread_id=None, cc=None, bcc=None,
         user_confirmed=False)
    list_labels()                           → list[dict]

Sending is gated by the kernel L_CONSENT (user_confirmed=True required) and
L_PRIVACY (Patients/ paths in body blocked).
"""
from __future__ import annotations

import base64
import logging
import os
from email.message import EmailMessage
from pathlib import Path
from typing import Optional

log = logging.getLogger("aim.email")

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
]

CLIENT_SECRET_PATH = Path(os.getenv(
    "GMAIL_CLIENT_SECRET_PATH",
    str(Path.home() / ".aim_env_gmail_client_secret.json"))).expanduser()
TOKEN_PATH = Path(os.getenv(
    "GMAIL_TOKEN_PATH",
    str(Path.home() / ".aim_env_gmail_token.json"))).expanduser()


# ── OAuth bootstrap ────────────────────────────────────────────────────────


_SERVICE = None
_LOCK_OBJ = None


def _service():
    global _SERVICE
    if _SERVICE is not None:
        return _SERVICE
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        raise RuntimeError(
            "google-api-python-client + google-auth-oauthlib not installed. "
            "Run:  venv/bin/pip install google-api-python-client "
            "google-auth-httplib2 google-auth-oauthlib")

    creds = None
    if TOKEN_PATH.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH),
                                                          GMAIL_SCOPES)
        except Exception as e:
            log.warning(f"failed to load token: {e}")
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CLIENT_SECRET_PATH.exists():
                raise RuntimeError(
                    f"GMAIL_CLIENT_SECRET_PATH not found at {CLIENT_SECRET_PATH}.\n"
                    "Get OAuth client JSON from console.cloud.google.com → "
                    "APIs & Services → Credentials, save it there.")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CLIENT_SECRET_PATH), GMAIL_SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        try:
            os.chmod(TOKEN_PATH, 0o600)
        except OSError:
            pass
    _SERVICE = build("gmail", "v1", credentials=creds, cache_discovery=False)
    return _SERVICE


# ── Read ───────────────────────────────────────────────────────────────────


def list_threads(q: str = "newer_than:7d", n: int = 20) -> list[dict]:
    svc = _service()
    out = svc.users().threads().list(userId="me", q=q, maxResults=n).execute()
    threads = out.get("threads", [])
    enriched: list[dict] = []
    for t in threads:
        meta = svc.users().threads().get(userId="me", id=t["id"],
                                         format="metadata",
                                         metadataHeaders=["Subject", "From", "Date"]
                                         ).execute()
        msgs = meta.get("messages", [])
        last = msgs[-1] if msgs else {}
        headers = {h["name"]: h["value"]
                   for h in last.get("payload", {}).get("headers", [])}
        enriched.append({
            "thread_id": t["id"],
            "n_messages": len(msgs),
            "subject": headers.get("Subject", ""),
            "from": headers.get("From", ""),
            "date": headers.get("Date", ""),
            "snippet": last.get("snippet", ""),
        })
    return enriched


def search(query: str, n: int = 20) -> list[dict]:
    return list_threads(q=query, n=n)


def get_thread(thread_id: str) -> dict:
    svc = _service()
    return svc.users().threads().get(userId="me", id=thread_id,
                                      format="full").execute()


def list_labels() -> list[dict]:
    svc = _service()
    return svc.users().labels().list(userId="me").execute().get("labels", [])


# ── Compose ────────────────────────────────────────────────────────────────


def _build_message(to: str, subject: str, body: str,
                   *, cc: Optional[str] = None, bcc: Optional[str] = None,
                   thread_id: Optional[str] = None) -> dict:
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    if cc:  msg["Cc"]  = cc
    if bcc: msg["Bcc"] = bcc
    msg.set_content(body)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    out = {"raw": raw}
    if thread_id:
        out["threadId"] = thread_id
    return out


def draft(to: str, subject: str, body: str, *,
          thread_id: Optional[str] = None,
          cc: Optional[str] = None, bcc: Optional[str] = None) -> dict:
    """Create a Gmail draft. NOT sent — safe by default."""
    _kernel_check_privacy(body, "email_draft")
    svc = _service()
    msg = _build_message(to, subject, body, cc=cc, bcc=bcc, thread_id=thread_id)
    return svc.users().drafts().create(userId="me", body={"message": msg}).execute()


def send(to: str, subject: str, body: str, *,
         thread_id: Optional[str] = None,
         cc: Optional[str] = None, bcc: Optional[str] = None,
         user_confirmed: bool = False) -> dict:
    """Send an email. Hard-gated by L_CONSENT + L_PRIVACY."""
    if not user_confirmed:
        raise PermissionError(
            "L_CONSENT: email_send requires user_confirmed=True. "
            "Pass user_confirmed=True only AFTER explicit user approval.")
    _kernel_check_privacy(body, "email_send")
    svc = _service()
    msg = _build_message(to, subject, body, cc=cc, bcc=bcc, thread_id=thread_id)
    return svc.users().messages().send(userId="me", body=msg).execute()


def _kernel_check_privacy(body: str, action: str) -> None:
    """Gate: block leaking Patients/ data, phone numbers, DoB."""
    from agents.kernel import Decision, evaluate_l_privacy
    d = Decision(id="email", description=action,
                 action_type="email_send", payload={"body": body})
    ok, reason = evaluate_l_privacy(d, patient={}, context={})
    if not ok:
        raise PermissionError(reason)
