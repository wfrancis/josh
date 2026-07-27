"""Microsoft Graph connection for deterministic vendor quote automation."""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote, urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken

from models import _get_conn
from quote_automation import (
    MAX_ATTACHMENT_BYTES,
    attachment_match_text,
    due_followups,
    followup_body,
    followup_send_guard,
    get_request,
    iso_now,
    mark_followup_failed,
    mark_followup_sent,
    mark_followup_uncertain,
    mark_request_send_uncertain,
    mark_request_sent,
    normalize_email,
    preview_incoming_match,
    process_incoming_message,
    record_followup_send_token,
    record_followup_evidence,
    record_sent_request_evidence,
    utc_now,
)


GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
LOGIN_ROOT = "https://login.microsoftonline.com"
SCOPES = (
    "openid",
    "profile",
    "email",
    "offline_access",
    "User.Read",
    "Mail.Read",
    "Mail.Send",
)
SESSION_COOKIE = "si_outlook_session"
CORRELATION_HEADER = "x-si-quote-token"


class OutlookConfigurationError(RuntimeError):
    pass


class OutlookAuthenticationError(RuntimeError):
    pass


class OutlookDeliveryUncertainError(RuntimeError):
    def __init__(self, message: str, *, send_token: str = ""):
        super().__init__(message)
        self.send_token = send_token


class GraphRequestError(RuntimeError):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


def _csv_env(name: str) -> set[str]:
    return {
        normalize_email(value)
        for value in os.environ.get(name, "").split(",")
        if normalize_email(value)
    }


def _config() -> dict:
    return {
        "tenant_id": os.environ.get("OUTLOOK_TENANT_ID", "organizations").strip()
        or "organizations",
        "client_id": os.environ.get("OUTLOOK_CLIENT_ID", "").strip(),
        "client_secret": os.environ.get("OUTLOOK_CLIENT_SECRET", "").strip(),
        "redirect_uri": os.environ.get("OUTLOOK_REDIRECT_URI", "").strip(),
        "token_key": os.environ.get("OUTLOOK_TOKEN_ENCRYPTION_KEY", "").strip(),
        "session_secret": os.environ.get("OUTLOOK_SESSION_SECRET", "").strip(),
        "allowed_emails": _csv_env("OUTLOOK_ALLOWED_EMAILS"),
        "test_recipients": _csv_env("QUOTE_TEST_ALLOWED_RECIPIENTS"),
        "test_senders": _csv_env("QUOTE_TEST_INBOUND_SENDERS")
        or _csv_env("QUOTE_TEST_ALLOWED_RECIPIENTS"),
        "mode": os.environ.get("QUOTE_AUTOMATION_MODE", "disabled").strip().lower(),
        "enabled": os.environ.get("QUOTE_AUTOMATION_ENABLED", "false").strip().lower()
        == "true",
        "notification_url": os.environ.get("OUTLOOK_NOTIFICATION_URL", "").strip(),
    }


def mailbox_is_allowed(email_address: str, config: dict | None = None) -> bool:
    current = config or _config()
    allowed = current["allowed_emails"]
    return bool(
        current["enabled"]
        and len(allowed) == 1
        and normalize_email(email_address) in allowed
    )


def configuration_status() -> dict:
    config = _config()
    missing = [
        label
        for label, value in (
            ("OUTLOOK_CLIENT_ID", config["client_id"]),
            ("OUTLOOK_CLIENT_SECRET", config["client_secret"]),
            ("OUTLOOK_TOKEN_ENCRYPTION_KEY", config["token_key"]),
            ("OUTLOOK_SESSION_SECRET", config["session_secret"]),
        )
        if not value
    ]
    if len(config["allowed_emails"]) != 1:
        missing.append("OUTLOOK_ALLOWED_EMAILS (exactly one mailbox)")
    if config["mode"] != "production":
        if len(config["test_recipients"]) != 1:
            missing.append("QUOTE_TEST_ALLOWED_RECIPIENTS (exactly one address)")
        if len(config["test_senders"]) != 1:
            missing.append("QUOTE_TEST_INBOUND_SENDERS (exactly one address)")
    configured_mailbox = next(iter(config["allowed_emails"]), "")
    replacement_mailbox = (
        f"{configured_mailbox}.replacement"
        if configured_mailbox
        else "replacement@invalid.test"
    )
    return {
        "configured": not missing,
        "enabled": config["enabled"],
        "mode": config["mode"],
        "missing": missing,
        "mailbox_allowlist_count": len(config["allowed_emails"]),
        "test_recipient_allowlist_count": len(config["test_recipients"]),
        "test_sender_allowlist_count": len(config["test_senders"]),
        "permissions": ["Mail.Read", "Mail.Send"],
        "can_modify_mail": False,
        "mailbox_recheck": {
            "configured_mailbox_allowed": mailbox_is_allowed(
                configured_mailbox,
                config,
            ),
            "replacement_mailbox_blocked": not mailbox_is_allowed(
                replacement_mailbox,
                config,
            ),
            "checked_on_every_connection_use": True,
        },
    }


def _require_config() -> dict:
    status = configuration_status()
    if not status["enabled"]:
        raise OutlookConfigurationError("Microsoft quote automation is disabled.")
    if not status["configured"]:
        raise OutlookConfigurationError(
            "Microsoft Outlook is not configured. Missing: " + ", ".join(status["missing"])
        )
    return _config()


def _fernet() -> Fernet:
    config = _require_config()
    key = config["token_key"].encode("ascii")
    try:
        return Fernet(key)
    except (ValueError, TypeError) as exc:
        raise OutlookConfigurationError(
            "OUTLOOK_TOKEN_ENCRYPTION_KEY must be a valid Fernet key."
        ) from exc


def generate_fernet_key() -> str:
    return Fernet.generate_key().decode("ascii")


def _encrypt_json(value: dict) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _fernet().encrypt(payload).decode("ascii")


def _decrypt_json(value: str) -> dict:
    try:
        payload = _fernet().decrypt(value.encode("ascii"))
        parsed = json.loads(payload)
    except (InvalidToken, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise OutlookAuthenticationError(
            "The saved Microsoft connection cannot be decrypted."
        ) from exc
    return parsed if isinstance(parsed, dict) else {}


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _sign_payload(payload: dict, *, expires_in: int) -> str:
    config = _require_config()
    value = dict(payload)
    value["exp"] = int(time.time()) + expires_in
    encoded = _b64(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    signature = _b64(
        hmac.new(
            config["session_secret"].encode("utf-8"),
            encoded.encode("ascii"),
            hashlib.sha256,
        ).digest()
    )
    return f"{encoded}.{signature}"


def _verify_payload(token: str) -> dict | None:
    config = _require_config()
    try:
        encoded, supplied = token.split(".", 1)
        expected = _b64(
            hmac.new(
                config["session_secret"].encode("utf-8"),
                encoded.encode("ascii"),
                hashlib.sha256,
            ).digest()
        )
        if not hmac.compare_digest(supplied, expected):
            return None
        payload = json.loads(_unb64(encoded))
        if int(payload.get("exp") or 0) < int(time.time()):
            return None
        return payload
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def create_session(email_address: str) -> str:
    return _sign_payload(
        {"email": normalize_email(email_address), "kind": "session"},
        expires_in=12 * 60 * 60,
    )


def verify_session(token: str | None) -> str | None:
    if not token:
        return None
    payload = _verify_payload(token)
    if not payload or payload.get("kind") != "session":
        return None
    email_address = normalize_email(payload.get("email"))
    return email_address if email_address and _connection(email_address) else None


def _safe_return_to(value: str | None) -> str:
    path = str(value or "/").strip()
    if not path.startswith("/") or path.startswith("//") or "://" in path:
        return "/"
    return path[:1000]


def authorization_url(*, redirect_uri: str, return_to: str = "/") -> str:
    config = _require_config()
    state = _sign_payload(
        {
            "kind": "oauth_state",
            "nonce": secrets.token_urlsafe(24),
            "return_to": _safe_return_to(return_to),
            "redirect_uri": redirect_uri,
        },
        expires_in=10 * 60,
    )
    query = urlencode(
        {
            "client_id": config["client_id"],
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "response_mode": "query",
            "scope": " ".join(SCOPES),
            "state": state,
            "prompt": "select_account",
        }
    )
    return f"{LOGIN_ROOT}/{config['tenant_id']}/oauth2/v2.0/authorize?{query}"


def verify_oauth_state(state: str) -> dict:
    payload = _verify_payload(state)
    if not payload or payload.get("kind") != "oauth_state":
        raise OutlookAuthenticationError("Microsoft sign-in state is invalid or expired.")
    return payload


def _token_endpoint() -> str:
    config = _require_config()
    return f"{LOGIN_ROOT}/{config['tenant_id']}/oauth2/v2.0/token"


def _http_client() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=False)


def _token_request(data: dict) -> dict:
    with _http_client() as client:
        response = client.post(_token_endpoint(), data=data)
    if response.status_code >= 400:
        detail = response.json().get("error_description") if response.content else ""
        raise OutlookAuthenticationError(
            detail or f"Microsoft token request failed ({response.status_code})."
        )
    result = response.json()
    result["expires_at"] = (
        utc_now() + timedelta(seconds=max(60, int(result.get("expires_in") or 3600)))
    ).isoformat()
    return result


def _graph_raw(
    method: str,
    path_or_url: str,
    *,
    access_token: str,
    params: dict | None = None,
    json_body: dict | None = None,
    headers: dict | None = None,
) -> httpx.Response:
    url = path_or_url if path_or_url.startswith("https://") else GRAPH_ROOT + path_or_url
    request_headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        **(headers or {}),
    }
    with _http_client() as client:
        response = client.request(
            method,
            url,
            params=params,
            json=json_body,
            headers=request_headers,
        )
    if response.status_code >= 400:
        try:
            detail = response.json().get("error", {}).get("message")
        except (ValueError, AttributeError):
            detail = ""
        raise GraphRequestError(
            detail or f"Microsoft Graph request failed ({response.status_code}).",
            response.status_code,
        )
    return response


def _graph_json(
    method: str,
    path_or_url: str,
    *,
    access_token: str,
    params: dict | None = None,
    json_body: dict | None = None,
    headers: dict | None = None,
) -> dict:
    response = _graph_raw(
        method,
        path_or_url,
        access_token=access_token,
        params=params,
        json_body=json_body,
        headers=headers,
    )
    return response.json() if response.content else {}


def _save_connection(email_address: str, user: dict, token: dict) -> None:
    now = iso_now()
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM outlook_connections WHERE email!=?", (email_address,))
        conn.execute(
            """INSERT INTO outlook_connections
               (email, microsoft_user_id, tenant_id, encrypted_token_json,
                scopes, status, last_sync_at, connected_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'connected', ?, ?, ?)
               ON CONFLICT(email) DO UPDATE SET
                   microsoft_user_id=excluded.microsoft_user_id,
                   tenant_id=excluded.tenant_id,
                   encrypted_token_json=excluded.encrypted_token_json,
                   scopes=excluded.scopes,
                   status='connected',
                   last_sync_at=excluded.last_sync_at,
                   updated_at=excluded.updated_at""",
            (
                email_address,
                str(user.get("id") or ""),
                _config()["tenant_id"],
                _encrypt_json(token),
                str(token.get("scope") or ""),
                now,
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def exchange_code(*, code: str, redirect_uri: str) -> dict:
    config = _require_config()
    token = _token_request(
        {
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "scope": " ".join(SCOPES),
        }
    )
    user = _graph_json(
        "GET",
        "/me",
        access_token=token["access_token"],
        params={"$select": "id,displayName,mail,userPrincipalName"},
    )
    email_address = normalize_email(
        user.get("mail") or user.get("userPrincipalName")
    )
    if not email_address:
        raise OutlookAuthenticationError("Microsoft did not return an email address.")
    allowed = config["allowed_emails"]
    if allowed and email_address not in allowed:
        raise OutlookAuthenticationError(
            f"{email_address} is not approved for this environment."
        )
    _save_connection(email_address, user, token)
    return {
        "email": email_address,
        "display_name": user.get("displayName") or email_address,
        "session": create_session(email_address),
    }


def _connection(email_address: str | None = None) -> dict | None:
    config = _config()
    conn = _get_conn()
    try:
        if email_address:
            row = conn.execute(
                """SELECT * FROM outlook_connections
                   WHERE email=? AND status='connected'""",
                (normalize_email(email_address),),
            ).fetchone()
        else:
            row = conn.execute(
                """SELECT * FROM outlook_connections
                   WHERE status='connected' ORDER BY updated_at DESC LIMIT 1"""
            ).fetchone()
        connection = dict(row) if row else None
        if not connection:
            return None
        if not mailbox_is_allowed(connection.get("email"), config):
            return None
        return connection
    finally:
        conn.close()


def outlook_status(session_email: str | None = None) -> dict:
    config_status = configuration_status()
    connection = _connection(session_email) if session_email else None
    return {
        **config_status,
        "connected": bool(connection),
        "email": connection.get("email") if connection else None,
        "connected_at": connection.get("connected_at") if connection else None,
        "last_sync_at": connection.get("last_sync_at") if connection else None,
        "subscription_expires_at": (
            connection.get("subscription_expires_at") if connection else None
        ),
        "session_authenticated": bool(
            session_email and connection and connection.get("email") == session_email
        ),
    }


def _save_token(email_address: str, token: dict) -> None:
    conn = _get_conn()
    try:
        conn.execute(
            """UPDATE outlook_connections
               SET encrypted_token_json=?, scopes=?, updated_at=?
               WHERE email=?""",
            (
                _encrypt_json(token),
                str(token.get("scope") or ""),
                iso_now(),
                email_address,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def access_token(email_address: str | None = None) -> tuple[str, dict]:
    _require_config()
    connection = _connection(email_address)
    if not connection:
        raise OutlookAuthenticationError("Outlook is not connected.")
    token = _decrypt_json(connection["encrypted_token_json"])
    expires_at = _parse_datetime(token.get("expires_at"))
    if not expires_at or expires_at <= utc_now() + timedelta(minutes=5):
        refresh_token = token.get("refresh_token")
        if not refresh_token:
            raise OutlookAuthenticationError(
                "Microsoft connection expired. Connect Outlook again."
            )
        config = _require_config()
        refreshed = _token_request(
            {
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": " ".join(SCOPES),
            }
        )
        if not refreshed.get("refresh_token"):
            refreshed["refresh_token"] = refresh_token
        token = refreshed
        _save_token(connection["email"], token)
    return str(token["access_token"]), connection


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc)


def disconnect(email_address: str) -> bool:
    conn = _get_conn()
    try:
        cursor = conn.execute(
            "DELETE FROM outlook_connections WHERE email=?",
            (normalize_email(email_address),),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def _validate_recipient(recipient: str) -> str:
    address = normalize_email(recipient)
    config = _config()
    if not address:
        raise ValueError("Vendor email is required.")
    if config["mode"] != "production":
        if not config["test_recipients"]:
            raise ValueError(
                "Staging email is blocked until QUOTE_TEST_ALLOWED_RECIPIENTS is set."
            )
        if address not in config["test_recipients"]:
            raise ValueError(f"Staging is not allowed to email {address}.")
    return address


def generate_send_token() -> str:
    return secrets.token_urlsafe(24)


def send_mail(
    recipient: str,
    subject: str,
    body: str,
    *,
    send_token: str,
    connection_email: str | None = None,
) -> dict:
    address = _validate_recipient(recipient)
    correlation_token = str(send_token or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,100}", correlation_token):
        raise ValueError("A valid quote send token is required.")
    token, connection = access_token(connection_email)
    try:
        _graph_raw(
            "POST",
            "/me/sendMail",
            access_token=token,
            json_body={
                "message": {
                    "subject": str(subject or "").strip(),
                    "body": {"contentType": "Text", "content": str(body or "")},
                    "toRecipients": [{"emailAddress": {"address": address}}],
                    "internetMessageHeaders": [
                        {
                            "name": CORRELATION_HEADER,
                            "value": correlation_token,
                        }
                    ],
                },
                "saveToSentItems": True,
            },
        )
    except httpx.TransportError as exc:
        raise OutlookDeliveryUncertainError(
            "Microsoft may have accepted the email, so it was not sent again.",
            send_token=correlation_token,
        ) from exc
    except GraphRequestError as exc:
        if exc.status_code >= 500:
            raise OutlookDeliveryUncertainError(
                "Microsoft may have accepted the email, so it was not sent again.",
                send_token=correlation_token,
            ) from exc
        raise
    return {
        "accepted": True,
        "send_token": correlation_token,
        "recipient": address,
        "sender": connection["email"],
        "sent_at": iso_now(),
        "proof_reconciled": False,
    }


def _message_mime(graph_message_id: str, token: str) -> bytes | None:
    encoded_id = quote(graph_message_id, safe="")
    try:
        response = _graph_raw(
            "GET",
            f"/me/messages/{encoded_id}/$value",
            access_token=token,
            headers={
                "Accept": "message/rfc822",
                "Prefer": 'IdType="ImmutableId"',
            },
        )
    except (GraphRequestError, httpx.TransportError):
        return None
    return response.content or None


def _strip_html(value: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", value or "", flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(html.unescape(text).split())


def _message_detail(graph_id: str, token: str) -> dict:
    encoded_id = quote(str(graph_id), safe="")
    return _graph_json(
        "GET",
        f"/me/messages/{encoded_id}",
        access_token=token,
        params={
            "$select": (
                "id,internetMessageId,conversationId,subject,body,from,toRecipients,"
                "receivedDateTime,sentDateTime,internetMessageHeaders,hasAttachments,"
                "isDraft,parentFolderId,size"
            )
        },
        headers={"Prefer": 'IdType="ImmutableId"'},
    )


def _message_attachments(graph_id: str, token: str) -> list[dict]:
    encoded_id = quote(str(graph_id), safe="")
    result = _graph_json(
        "GET",
        f"/me/messages/{encoded_id}/attachments",
        access_token=token,
        params={"$select": "id,name,contentType,size,contentBytes"},
        headers={"Prefer": 'IdType="ImmutableId"'},
    )
    items = list(result.get("value") or [])
    seen_pages = set()
    while result.get("@odata.nextLink"):
        next_link = str(result["@odata.nextLink"])
        if next_link in seen_pages:
            break
        seen_pages.add(next_link)
        result = _graph_json("GET", next_link, access_token=token)
        items.extend(result.get("value") or [])
    attachments = []
    for item in items:
        declared_size = int(item.get("size") or 0)
        if declared_size > MAX_ATTACHMENT_BYTES:
            attachments.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name") or "attachment",
                    "content_type": item.get("contentType") or "",
                    "size": declared_size,
                    "error": "Attachment is larger than 25 MB.",
                }
            )
            continue
        content = item.get("contentBytes")
        if not content:
            continue
        try:
            data = base64.b64decode(content)
        except (ValueError, TypeError):
            continue
        if len(data) > MAX_ATTACHMENT_BYTES:
            continue
        attachments.append(
            {
                "id": item.get("id"),
                "name": item.get("name") or "attachment",
                "content_type": item.get("contentType") or "",
                "size": len(data),
                "data": data,
            }
        )
    return attachments


def _incoming_allowed(sender: str) -> bool:
    config = _config()
    if config["mode"] == "production":
        return True
    return normalize_email(sender) in config["test_senders"]


def sync_inbox_once(connection_email: str | None = None) -> dict:
    token, connection = access_token(connection_email)
    last_sync = _parse_datetime(connection.get("last_sync_at")) or utc_now()
    start = last_sync - timedelta(minutes=5)
    response = _graph_json(
        "GET",
        "/me/mailFolders/inbox/messages",
        access_token=token,
        params={
            "$filter": f"receivedDateTime ge {start.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
            "$orderby": "receivedDateTime asc",
            "$top": "100",
            "$select": "id,from,subject,receivedDateTime",
        },
        headers={"Prefer": 'IdType="ImmutableId"'},
    )
    summaries = []
    seen_pages = set()
    while True:
        summaries.extend(response.get("value") or [])
        next_link = str(response.get("@odata.nextLink") or "")
        if not next_link or next_link in seen_pages:
            break
        seen_pages.add(next_link)
        response = _graph_json("GET", next_link, access_token=token)
    processed = []
    skipped = 0
    for summary in summaries:
        sender = normalize_email(
            ((summary.get("from") or {}).get("emailAddress") or {}).get("address")
        )
        if not _incoming_allowed(sender):
            skipped += 1
            continue
        detail = _message_detail(str(summary["id"]), token)
        message = {
            "mailbox_email": connection["email"],
            "graph_message_id": detail.get("id") or summary["id"],
            "internet_message_id": detail.get("internetMessageId") or "",
            "conversation_id": detail.get("conversationId") or "",
            "sender_email": normalize_email(
                ((detail.get("from") or {}).get("emailAddress") or {}).get("address")
            ),
            "recipients": [
                normalize_email((item.get("emailAddress") or {}).get("address"))
                for item in detail.get("toRecipients") or []
            ],
            "subject": detail.get("subject") or "",
            "body_text": _strip_html((detail.get("body") or {}).get("content") or ""),
            "received_at": detail.get("receivedDateTime"),
            "sent_at": detail.get("sentDateTime"),
            "headers": detail.get("internetMessageHeaders") or [],
            "attachments": [],
            "attachment_text": "",
        }
        preview = preview_incoming_match(message)
        attachment_probe_needed = bool(
            detail.get("hasAttachments")
            and preview.get("status") == "ignored"
            and preview.get("method") == "no_exact_job_fact"
        )
        if preview["status"] == "ignored" and not attachment_probe_needed:
            skipped += 1
            continue
        attachments = (
            _message_attachments(str(summary["id"]), token)
            if detail.get("hasAttachments")
            else []
        )
        if attachments:
            message["attachments"] = attachments
            message["attachment_text"] = attachment_match_text(attachments)
            preview = preview_incoming_match(message)
            if preview["status"] == "ignored":
                skipped += 1
                continue
        if int(detail.get("size") or 0) <= MAX_ATTACHMENT_BYTES * 2:
            message["raw_bytes"] = _message_mime(str(summary["id"]), token)
        processed.append(process_incoming_message(message))
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE outlook_connections SET last_sync_at=?, updated_at=? WHERE email=?",
            (iso_now(), iso_now(), connection["email"]),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "status": "ok",
        "processed": processed,
        "processed_count": len(processed),
        "skipped_count": skipped,
        "page_count": len(seen_pages) + 1,
        "matching_engine": "deterministic-v1",
        "ai_calls": 0,
    }


def reconcile_sent_requests(connection_email: str | None = None) -> dict:
    token, connection = access_token(connection_email)
    conn = _get_conn()
    try:
        requests = [
            dict(row)
            for row in conn.execute(
                """SELECT * FROM quote_requests
                   WHERE status IN ('sending','send_uncertain','sent','waiting',
                                    'overdue','received_partial')
                     AND mailbox_email=?
                   ORDER BY COALESCE(sent_at, approved_at, created_at) DESC
                   LIMIT 100""",
                (connection["email"],),
            ).fetchall()
        ]
        followups = [
            dict(row)
            for row in conn.execute(
                """SELECT qfe.*, qr.vendor_email, qr.subject, qr.mailbox_email
                   FROM quote_followup_events qfe
                   JOIN quote_requests qr ON qr.id=qfe.quote_request_id
                   WHERE qfe.status IN ('sending','sent','uncertain')
                     AND qfe.send_token!=''
                     AND qr.mailbox_email=?
                   ORDER BY COALESCE(qfe.sent_at, qfe.claimed_at, qfe.created_at) DESC
                   LIMIT 100""",
                (connection["email"],),
            ).fetchall()
        ]
    finally:
        conn.close()
    if not requests and not followups:
        return {"matched": 0}

    timestamps = []
    for item in [*requests, *followups]:
        parsed = _parse_datetime(
            item.get("sent_at")
            or item.get("claimed_at")
            or item.get("approved_at")
            or item.get("created_at")
        )
        if parsed:
            timestamps.append(parsed)
    earliest = (min(timestamps) if timestamps else utc_now()) - timedelta(minutes=10)
    response = _graph_json(
        "GET",
        "/me/mailFolders/sentitems/messages",
        access_token=token,
        params={
            "$filter": f"sentDateTime ge {earliest.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
            "$orderby": "sentDateTime desc",
            "$top": "100",
            "$select": (
                "id,internetMessageId,conversationId,subject,body,toRecipients,sentDateTime"
            ),
        },
        headers={"Prefer": 'IdType="ImmutableId"'},
    )
    sent_summaries = list(response.get("value") or [])
    seen_pages = set()
    while response.get("@odata.nextLink") and len(seen_pages) < 10:
        next_link = str(response["@odata.nextLink"])
        if next_link in seen_pages:
            break
        seen_pages.add(next_link)
        response = _graph_json(
            "GET",
            next_link,
            access_token=token,
            headers={"Prefer": 'IdType="ImmutableId"'},
        )
        sent_summaries.extend(response.get("value") or [])

    request_tokens = {
        str(request.get("send_token") or ""): request
        for request in requests
        if str(request.get("send_token") or "")
    }
    followup_tokens = {
        str(event.get("send_token") or ""): event
        for event in followups
        if str(event.get("send_token") or "")
    }
    expected_tokens = set(request_tokens) | set(followup_tokens)
    matched_details: dict[str, dict] = {}
    for summary in sent_summaries:
        recipients = {
            normalize_email((item.get("emailAddress") or {}).get("address"))
            for item in summary.get("toRecipients") or []
        }
        subject = str(summary.get("subject") or "").strip()
        possible = any(
            normalize_email(request.get("vendor_email")) in recipients
            and str(request.get("subject") or "").strip() == subject
            for request in request_tokens.values()
        ) or any(
            normalize_email(event.get("vendor_email")) in recipients
            and f"Re: {event.get('subject') or 'Quote Request'}" == subject
            for event in followup_tokens.values()
        )
        if expected_tokens and not possible:
            continue
        try:
            detail = _message_detail(str(summary.get("id") or ""), token)
        except (GraphRequestError, httpx.TransportError):
            continue
        headers = {
            str(item.get("name") or "").strip().lower(): str(
                item.get("value") or ""
            ).strip()
            for item in detail.get("internetMessageHeaders") or []
        }
        correlation = headers.get(CORRELATION_HEADER, "")
        if correlation in expected_tokens:
            matched_details[correlation] = detail

    matched = 0
    for correlation, request in request_tokens.items():
        message = matched_details.get(correlation)
        if not message:
            approved = _parse_datetime(
                request.get("approved_at") or request.get("created_at")
            )
            if (
                request.get("status") == "sending"
                and approved
                and approved <= utc_now() - timedelta(minutes=30)
            ):
                mark_request_send_uncertain(
                    int(request["id"]),
                    "Microsoft delivery proof is pending; this email was not sent again.",
                )
            continue
        sent_at = _parse_datetime(message.get("sentDateTime")) or utc_now()
        graph_id = str(message.get("id") or "")
        record_sent_request_evidence(
            int(request["id"]),
            sender_email=connection["email"],
            sent_at=sent_at.isoformat(),
            raw_message=_message_mime(graph_id, token),
        )
        mark_request_sent(
            int(request["id"]),
            graph_message_id=graph_id,
            internet_message_id=str(message.get("internetMessageId") or ""),
            conversation_id=str(message.get("conversationId") or ""),
            sent_at=sent_at,
        )
        matched += 1

    for correlation, event in followup_tokens.items():
        message = matched_details.get(correlation)
        if not message:
            continue
        sent_at = _parse_datetime(message.get("sentDateTime")) or utc_now()
        graph_id = str(message.get("id") or "")
        subject = f"Re: {event.get('subject') or 'Quote Request'}"
        body = followup_body(
            int(event["quote_request_id"]),
            int(event["followup_number"]),
        )
        record_followup_evidence(
            int(event["id"]),
            sender_email=connection["email"],
            recipient_email=str(event.get("vendor_email") or ""),
            subject=subject,
            body=body,
            sent_at=sent_at.isoformat(),
            raw_message=_message_mime(graph_id, token),
        )
        mark_followup_sent(int(event["id"]), graph_id)
        matched += 1

    legacy_requests = [
        request
        for request in requests
        if not str(request.get("send_token") or "") and request.get("sent_at")
    ]
    for request in legacy_requests:
        recipient = normalize_email(request.get("vendor_email"))
        subject = str(request.get("subject") or "").strip()
        sent_at = _parse_datetime(request.get("sent_at")) or utc_now()
        body_key = re.sub(r"\s+", "", str(request.get("request_text") or "").lower())
        candidates = []
        for message in sent_summaries:
            recipients = {
                normalize_email((item.get("emailAddress") or {}).get("address"))
                for item in message.get("toRecipients") or []
            }
            message_time = _parse_datetime(message.get("sentDateTime"))
            message_body = re.sub(
                r"\s+",
                "",
                _strip_html((message.get("body") or {}).get("content") or "").lower(),
            )
            if (
                recipient in recipients
                and str(message.get("subject") or "").strip() == subject
                and message_time
                and abs((message_time - sent_at).total_seconds()) <= 15 * 60
                and (not body_key or body_key[:200] in message_body)
            ):
                candidates.append(message)
        if len(candidates) == 1:
            message = candidates[0]
            record_sent_request_evidence(
                int(request["id"]),
                sender_email=connection["email"],
                sent_at=sent_at.isoformat(),
                raw_message=_message_mime(str(message.get("id") or ""), token),
            )
            mark_request_sent(
                int(request["id"]),
                graph_message_id=str(message.get("id") or ""),
                internet_message_id=str(message.get("internetMessageId") or ""),
                conversation_id=str(message.get("conversationId") or ""),
                sent_at=sent_at,
            )
            matched += 1
    return {
        "matched": matched,
        "tracked_tokens": len(expected_tokens),
        "page_count": len(seen_pages) + 1,
    }


def send_due_followups(connection_email: str | None = None) -> dict:
    sent = 0
    failed = 0
    uncertain = 0
    for event in due_followups():
        request = get_request(int(event["quote_request_id"]))
        if not request:
            continue
        accepted = False
        try:
            subject = f"Re: {event.get('subject') or 'Quote Request'}"
            mailbox_email = str(
                event.get("mailbox_email") or connection_email or ""
            ) or None
            send_token = str(event.get("send_token") or "").strip()
            if not send_token:
                send_token = generate_send_token()
                record_followup_send_token(int(event["id"]), send_token)
            with followup_send_guard(int(event["id"])) as sendable:
                if not sendable:
                    continue
                body = followup_body(
                    int(event["quote_request_id"]),
                    int(event["followup_number"]),
                )
                result = send_mail(
                    str(event["vendor_email"]),
                    subject,
                    body,
                    send_token=send_token,
                    connection_email=mailbox_email,
                )
            accepted = True
            mark_followup_sent(int(event["id"]))
            sent += 1
        except OutlookDeliveryUncertainError as exc:
            mark_followup_uncertain(int(event["id"]), str(exc))
            uncertain += 1
        except Exception as exc:
            if accepted:
                mark_followup_uncertain(int(event["id"]), str(exc))
                uncertain += 1
            else:
                mark_followup_failed(int(event["id"]), str(exc))
                failed += 1
    return {"sent": sent, "failed": failed, "uncertain": uncertain}


def ensure_subscription(connection_email: str | None = None) -> dict:
    config = _config()
    if not config["notification_url"]:
        return {"status": "disabled", "reason": "OUTLOOK_NOTIFICATION_URL is not set"}
    token, connection = access_token(connection_email)
    expires = _parse_datetime(connection.get("subscription_expires_at"))
    if connection.get("subscription_id") and expires and expires > utc_now() + timedelta(hours=12):
        return {
            "status": "active",
            "subscription_id": connection["subscription_id"],
            "expires_at": expires.isoformat(),
        }
    expiration = utc_now() + timedelta(days=2)
    client_state = hmac.new(
        _config()["session_secret"].encode("utf-8"),
        connection["email"].encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if connection.get("subscription_id"):
        try:
            result = _graph_json(
                "PATCH",
                f"/subscriptions/{connection['subscription_id']}",
                access_token=token,
                json_body={"expirationDateTime": expiration.isoformat()},
            )
        except RuntimeError:
            result = {}
    else:
        result = {}
    if not result.get("id"):
        result = _graph_json(
            "POST",
            "/subscriptions",
            access_token=token,
            json_body={
                "changeType": "created",
                "notificationUrl": config["notification_url"],
                "resource": f"users/{connection['microsoft_user_id']}/mailFolders('Inbox')/messages",
                "expirationDateTime": expiration.isoformat(),
                "clientState": client_state,
            },
        )
    conn = _get_conn()
    try:
        conn.execute(
            """UPDATE outlook_connections
               SET subscription_id=?, subscription_expires_at=?, updated_at=?
               WHERE email=?""",
            (
                result.get("id") or "",
                result.get("expirationDateTime") or expiration.isoformat(),
                iso_now(),
                connection["email"],
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "status": "active",
        "subscription_id": result.get("id"),
        "expires_at": result.get("expirationDateTime"),
    }


def notification_payload_is_valid(payload: dict) -> bool:
    values = payload.get("value") if isinstance(payload, dict) else None
    if not isinstance(values, list) or not values:
        return False
    connection = _connection()
    if not connection:
        return False
    expected = hmac.new(
        _config()["session_secret"].encode("utf-8"),
        connection["email"].encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return all(
        isinstance(item, dict)
        and hmac.compare_digest(str(item.get("clientState") or ""), expected)
        for item in values
    )


class OutlookWorker:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.running or not _config()["enabled"]:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="outlook-quote-worker",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
        self._thread = None

    def _run(self) -> None:
        interval = max(
            60,
            min(
                int(os.environ.get("QUOTE_AUTOMATION_POLL_SECONDS", "600")),
                3600,
            ),
        )
        while not self._stop.is_set():
            if _connection():
                for operation in (
                    reconcile_sent_requests,
                    sync_inbox_once,
                    send_due_followups,
                    ensure_subscription,
                ):
                    try:
                        operation()
                    except Exception as exc:
                        print(f"[OutlookQuoteWorker] {operation.__name__}: {exc}")
            self._stop.wait(interval)


outlook_worker = OutlookWorker()
