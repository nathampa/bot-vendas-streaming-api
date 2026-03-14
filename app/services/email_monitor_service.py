import datetime
import email
import hashlib
import html
import imaplib
import json
import re
import socket
import threading
import time
import uuid
from email import policy
from email.header import decode_header
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from fnmatch import fnmatch
from html.parser import HTMLParser
from typing import Any, Iterable, Optional
from urllib.parse import quote, urlparse

import requests
from sqlalchemy import or_
from sqlmodel import Session, select

from app.core.config import settings
from app.db.database import engine
from app.models.email_monitor_models import (
    AuditLog,
    EmailMonitorAccount,
    EmailMonitorAlertEvent,
    EmailMonitorFolderState,
    EmailMonitorMessage,
    EmailMonitorMessageMatch,
    EmailMonitorRule,
    EmailMonitorSyncRun,
    EmailMonitorSyncRunStatus,
    EmailMonitorSyncStatus,
    EmailMonitorWebhookStatus,
)
from app.services.security import decrypt_data, encrypt_data

_ALLOWED_TAGS = {
    "a",
    "abbr",
    "b",
    "blockquote",
    "br",
    "code",
    "div",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "li",
    "ol",
    "p",
    "pre",
    "span",
    "strong",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
}
_ALLOWED_ATTRS = {"href", "title", "colspan", "rowspan", "target", "rel"}
_ALLOWED_SCHEMES = {"http", "https", "mailto"}
_SYNC_REGISTRY_LOCK = threading.Lock()
_SYNC_LOCKS: dict[str, threading.Lock] = {}


class SanitizedHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        normalized = tag.lower()
        if normalized in {"script", "style", "iframe", "object", "embed", "form"}:
            self.skip_depth += 1
            return
        if self.skip_depth or normalized not in _ALLOWED_TAGS:
            return
        clean_attrs: list[str] = []
        for key, value in attrs:
            attr_name = key.lower()
            if attr_name not in _ALLOWED_ATTRS or value is None:
                continue
            if attr_name == "href":
                parsed = urlparse(value)
                if parsed.scheme and parsed.scheme.lower() not in _ALLOWED_SCHEMES:
                    continue
            safe_value = html.escape(value, quote=True)
            clean_attrs.append(f'{attr_name}="{safe_value}"')
        attrs_str = f" {' '.join(clean_attrs)}" if clean_attrs else ""
        self.parts.append(f"<{normalized}{attrs_str}>")

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in {"script", "style", "iframe", "object", "embed", "form"}:
            if self.skip_depth:
                self.skip_depth -= 1
            return
        if self.skip_depth or normalized not in _ALLOWED_TAGS:
            return
        self.parts.append(f"</{normalized}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() in _ALLOWED_TAGS:
            self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        self.parts.append(html.escape(data))

    def handle_entityref(self, name: str) -> None:
        if self.skip_depth:
            return
        self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self.skip_depth:
            return
        self.parts.append(f"&#{name};")

    def get_html(self) -> str:
        return "".join(self.parts)


def utcnow() -> datetime.datetime:
    return datetime.datetime.utcnow()


def normalize_folder_list(folders: Optional[Iterable[str]]) -> list[str]:
    normalized: list[str] = []
    for folder in folders or ["INBOX"]:
        value = (folder or "").strip()
        if value and value not in normalized:
            normalized.append(value)
    return normalized or ["INBOX"]


def decode_mime_header(value: Optional[str]) -> Optional[str]:
    if not value:
        return value
    fragments: list[str] = []
    for fragment, encoding in decode_header(value):
        if isinstance(fragment, bytes):
            fragments.append(fragment.decode(encoding or "utf-8", errors="replace"))
        else:
            fragments.append(fragment)
    return "".join(fragments).strip() or None


def strip_html_tags(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value or "")).strip()


def sanitize_html_content(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    parser = SanitizedHTMLParser()
    parser.feed(value)
    parser.close()
    sanitized = parser.get_html().strip()
    return sanitized or None


def truncate_text(value: Optional[str], max_chars: int) -> Optional[str]:
    if value is None:
        return None
    compact = value.strip()
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 1].rstrip() + "..."


def mask_identifier(value: Optional[str]) -> str:
    raw = (value or "").strip()
    if not raw:
        return "-"
    if "@" in raw:
        local, _, domain = raw.partition("@")
        local_prefix = local[:2]
        return f"{local_prefix}***@{domain}"
    return f"{raw[:2]}***"


def stringify_imap_exception(exc: Exception) -> str:
    if getattr(exc, "args", None):
        parts: list[str] = []
        for arg in exc.args:
            if isinstance(arg, bytes):
                parts.append(arg.decode("utf-8", errors="replace"))
            else:
                parts.append(str(arg))
        rendered = " ".join(part.strip() for part in parts if part).strip()
        if rendered:
            return rendered
    return str(exc).strip() or exc.__class__.__name__


def describe_imap_error(exc: Exception, *, imap_host: str, imap_port: int, use_ssl: bool) -> str:
    raw_message = stringify_imap_exception(exc)
    lower_message = raw_message.lower()
    host_lower = (imap_host or "").strip().lower()
    is_gmail = host_lower in {"imap.gmail.com", "gmail.com", "googlemail.com"} or "gmail" in host_lower

    if isinstance(exc, (socket.timeout, TimeoutError)) or "timed out" in lower_message:
        return f"Tempo limite ao conectar ao servidor IMAP {imap_host}:{imap_port}. Revise host, porta, SSL e conectividade."
    if any(token in lower_message for token in ("authenticationfailed", "invalid credentials", "login failed", "auth failed")):
        if is_gmail:
            return "Falha de autenticacao no Gmail. Para IMAP, o Google normalmente exige IMAP habilitado e senha de app; a senha comum da conta pode ser recusada."
        return "Falha de autenticacao no servidor IMAP. Revise usuario, senha e se a conta permite acesso IMAP."
    if any(token in lower_message for token in ("ssl", "tls", "wrong version number", "certificate")):
        return f"Falha na negociacao SSL/TLS com {imap_host}:{imap_port}. Revise host, porta e se a opcao SSL esta correta."
    if any(token in lower_message for token in ("name or service not known", "nodename nor servname provided", "getaddrinfo failed", "temporary failure in name resolution")):
        return f"Nao foi possivel resolver o host IMAP {imap_host}. Revise o endereco configurado."
    if any(token in lower_message for token in ("connection refused", "network is unreachable", "no route to host")):
        transport = "IMAP SSL" if use_ssl else "IMAP"
        return f"Falha de rede ao conectar via {transport} em {imap_host}:{imap_port}. Revise firewall, porta e conectividade."
    return truncate_text(raw_message, 240) or "Falha ao conectar no servidor IMAP."


def log_imap_failure(context: str, *, imap_host: str, imap_port: int, use_ssl: bool, username: Optional[str], error_message: str) -> None:
    print(
        "EMAIL_MONITOR_IMAP_FAILURE "
        f"context={context} "
        f"host={imap_host} "
        f"port={imap_port} "
        f"ssl={str(use_ssl).lower()} "
        f"user={mask_identifier(username)} "
        f'error="{truncate_text(error_message, 400) or "erro-desconhecido"}"'
    )


def parse_email_addresses(raw_value: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if not raw_value:
        return None, None
    addresses = getaddresses([raw_value])
    if not addresses:
        return None, None
    name, address = addresses[0]
    return decode_mime_header(name), address.strip() or None


def parse_sent_datetime(raw_value: Optional[str]) -> Optional[datetime.datetime]:
    if not raw_value:
        return None
    try:
        parsed = parsedate_to_datetime(raw_value)
    except Exception:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return parsed


def get_text_payload(part: email.message.Message) -> str:
    try:
        content = part.get_content()
        if isinstance(content, str):
            return content
        if isinstance(content, bytes):
            charset = part.get_content_charset() or "utf-8"
            return content.decode(charset, errors="replace")
    except Exception:
        payload = part.get_payload(decode=True)
        if isinstance(payload, bytes):
            charset = part.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace")
    return ""


def extract_message_bodies(message: email.message.Message) -> tuple[Optional[str], Optional[str]]:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    for part in message.walk():
        if part.is_multipart():
            continue
        if (part.get_content_disposition() or "").lower() == "attachment":
            continue
        content_type = part.get_content_type().lower()
        content = get_text_payload(part)
        if not content:
            continue
        if content_type == "text/plain":
            plain_parts.append(content)
        elif content_type == "text/html":
            html_parts.append(content)
    plain_text = truncate_text("\n\n".join(plain_parts).strip() or None, settings.EMAIL_MONITOR_MAX_BODY_CHARS)
    html_text = truncate_text("\n".join(html_parts).strip() or None, settings.EMAIL_MONITOR_MAX_BODY_CHARS)
    return plain_text, sanitize_html_content(html_text)


def compute_secondary_hash(*parts: Any) -> str:
    serialized = json.dumps(parts, default=str, ensure_ascii=True, sort_keys=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def build_message_hash(message_id: Optional[str], sender_email: Optional[str], subject: Optional[str], sent_at: Optional[datetime.datetime], body_preview: Optional[str]) -> str:
    if message_id:
        return hashlib.sha256(message_id.strip().lower().encode("utf-8")).hexdigest()
    return compute_secondary_hash(sender_email or "", subject or "", sent_at.isoformat() if sent_at else "", body_preview or "")


def build_provider_message_url(account_email: str, message_id: Optional[str]) -> Optional[str]:
    if not message_id:
        return None
    local, _, domain = account_email.lower().partition("@")
    if domain in {"gmail.com", "googlemail.com"}:
        query = quote(f"rfc822msgid:{message_id.strip('<>')}")
        return f"https://mail.google.com/mail/u/0/#search/{query}"
    if domain in {"outlook.com", "hotmail.com", "live.com"}:
        query = quote(message_id.strip("<>"))
        return f"https://outlook.live.com/mail/0/search?q={query}"
    if domain.endswith("office365.com") or domain.endswith("outlook.office.com"):
        query = quote(message_id.strip("<>"))
        return f"https://outlook.office.com/mail/search?q={query}"
    return None


def mask_sensitive_values(metadata: Optional[dict[str, Any]]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in (metadata or {}).items():
        if any(token in key.lower() for token in ("password", "secret", "token")):
            clean[key] = "***"
            continue
        clean[key] = value
    return clean


def log_audit(
    session: Session,
    *,
    actor_usuario_id: Optional[uuid.UUID],
    event_type: str,
    resource_type: str,
    message: str,
    resource_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    ip_address: Optional[str] = None,
) -> AuditLog:
    audit = AuditLog(
        actor_usuario_id=actor_usuario_id,
        event_type=event_type,
        resource_type=resource_type,
        resource_id=resource_id,
        message=truncate_text(message, 400) or "Evento",
        metadata_json=mask_sensitive_values(metadata),
        ip_address=ip_address,
    )
    session.add(audit)
    return audit


def get_account_lock(account_id: uuid.UUID) -> threading.Lock:
    key = str(account_id)
    with _SYNC_REGISTRY_LOCK:
        if key not in _SYNC_LOCKS:
            _SYNC_LOCKS[key] = threading.Lock()
        return _SYNC_LOCKS[key]


def normalize_rule_keywords(keywords: Optional[Iterable[str]]) -> list[str]:
    normalized: list[str] = []
    for keyword in keywords or []:
        value = (keyword or "").strip()
        if value and value.lower() not in [item.lower() for item in normalized]:
            normalized.append(value)
    return normalized


def pattern_matches(pattern: Optional[str], value: Optional[str]) -> bool:
    if not pattern:
        return True
    haystack = (value or "").strip().lower()
    needle = pattern.strip().lower()
    if not haystack:
        return False
    if "*" in needle or "?" in needle:
        return fnmatch(haystack, needle)
    return needle in haystack


def rule_matches_message(rule: EmailMonitorRule, *, folder_name: str, sender: Optional[str], subject: Optional[str], body_text: Optional[str]) -> Optional[str]:
    reasons: list[str] = []
    if rule.sender_pattern:
        sender_blob = " ".join(filter(None, [sender]))
        if not pattern_matches(rule.sender_pattern, sender_blob):
            return None
        reasons.append("remetente")
    if rule.subject_pattern:
        if not pattern_matches(rule.subject_pattern, subject):
            return None
        reasons.append("assunto")
    if rule.folder_pattern:
        if not pattern_matches(rule.folder_pattern, folder_name):
            return None
        reasons.append("pasta")
    keywords = normalize_rule_keywords(rule.body_keywords_json)
    if keywords:
        body_lower = (body_text or "").lower()
        matched_keywords = [keyword for keyword in keywords if keyword.lower() in body_lower]
        if not matched_keywords:
            return None
        reasons.append(f"palavras-chave ({', '.join(matched_keywords[:3])})")
    if not reasons:
        reasons.append("regra global")
    return ", ".join(reasons)


def sorted_rules(rules: list[EmailMonitorRule], account_id: uuid.UUID) -> list[EmailMonitorRule]:
    return sorted(
        rules,
        key=lambda rule: (
            1 if rule.account_id is None else 0,
            rule.priority,
            rule.created_at,
        ),
    )


def select_incremental_uids(all_uids: list[int], last_seen_uid: Optional[int], batch_size: int) -> list[int]:
    candidates = [uid for uid in all_uids if last_seen_uid is None or uid > last_seen_uid]
    return candidates[-batch_size:] if batch_size > 0 else candidates


def get_folder_state(session: Session, account_id: uuid.UUID, folder_name: str) -> EmailMonitorFolderState:
    state = session.exec(
        select(EmailMonitorFolderState).where(
            EmailMonitorFolderState.account_id == account_id,
            EmailMonitorFolderState.folder_name == folder_name,
        )
    ).first()
    if state:
        return state
    state = EmailMonitorFolderState(account_id=account_id, folder_name=folder_name)
    session.add(state)
    session.flush()
    return state


def extract_fetch_payload(fetch_data: list[Any]) -> tuple[Optional[bytes], str, Optional[datetime.datetime]]:
    raw_bytes: Optional[bytes] = None
    response_meta = ""
    for item in fetch_data:
        if isinstance(item, tuple):
            response_meta = item[0].decode("utf-8", errors="replace") if isinstance(item[0], bytes) else str(item[0])
            raw_bytes = item[1] if isinstance(item[1], bytes) else None
            break
    flags_match = re.search(r"FLAGS \((.*?)\)", response_meta)
    flags_blob = flags_match.group(1) if flags_match else ""
    internal_date_match = re.search(r'INTERNALDATE "([^"]+)"', response_meta)
    internal_date = None
    if internal_date_match:
        try:
            parsed = datetime.datetime.strptime(internal_date_match.group(1), "%d-%b-%Y %H:%M:%S %z")
            internal_date = parsed.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        except ValueError:
            internal_date = None
    return raw_bytes, flags_blob, internal_date


def build_message_headers(message: email.message.Message) -> dict[str, Any]:
    headers_of_interest = [
        "From",
        "To",
        "Cc",
        "Reply-To",
        "Subject",
        "Date",
        "Message-ID",
        "In-Reply-To",
        "References",
        "Return-Path",
    ]
    result: dict[str, Any] = {}
    for header_name in headers_of_interest:
        value = message.get(header_name)
        if value is not None:
            result[header_name] = decode_mime_header(value)
    return result


def build_connection(account_host: str, account_port: int, use_ssl: bool) -> imaplib.IMAP4:
    if use_ssl:
        return imaplib.IMAP4_SSL(account_host, account_port, timeout=settings.EMAIL_MONITOR_IMAP_TIMEOUT_SECONDS)
    return imaplib.IMAP4(account_host, account_port, timeout=settings.EMAIL_MONITOR_IMAP_TIMEOUT_SECONDS)


def list_mailboxes(connection: imaplib.IMAP4) -> list[str]:
    status, mailboxes = connection.list()
    if status != "OK":
        return []
    folders: list[str] = []
    for mailbox in mailboxes or []:
        raw = mailbox.decode("utf-8", errors="replace") if isinstance(mailbox, bytes) else str(mailbox)
        parts = raw.split(' "/" ')
        folder_name = parts[-1].strip().strip('"') if parts else raw.strip()
        if folder_name and folder_name not in folders:
            folders.append(folder_name)
    return folders


def test_imap_connection(*, imap_host: str, imap_port: int, imap_username: str, password: str, use_ssl: bool) -> tuple[bool, str, list[str]]:
    connection = None
    try:
        connection = build_connection(imap_host, imap_port, use_ssl)
        connection.login(imap_username, password)
        folders = list_mailboxes(connection)
        status, _ = connection.select("INBOX", readonly=True)
        if status != "OK":
            return False, "Conexao IMAP autenticada, mas nao foi possivel abrir a pasta INBOX.", folders
        return True, "Conexão IMAP validada com sucesso.", folders
    except Exception as exc:
        raw_error = stringify_imap_exception(exc)
        friendly_error = describe_imap_error(exc, imap_host=imap_host, imap_port=imap_port, use_ssl=use_ssl)
        log_imap_failure(
            "connection_test",
            imap_host=imap_host,
            imap_port=imap_port,
            use_ssl=use_ssl,
            username=imap_username,
            error_message=raw_error,
        )
        return False, friendly_error, []
    finally:
        if connection is not None:
            try:
                connection.logout()
            except Exception:
                pass


def cleanup_old_irrelevant_messages(session: Session, account: EmailMonitorAccount) -> None:
    if account.retain_irrelevant_days <= 0:
        return
    cutoff = utcnow() - datetime.timedelta(days=account.retain_irrelevant_days)
    stale_messages = session.exec(
        select(EmailMonitorMessage).where(
            EmailMonitorMessage.account_id == account.id,
            EmailMonitorMessage.is_relevant == False,
            EmailMonitorMessage.created_at < cutoff,
        )
    ).all()
    for message in stale_messages:
        related_matches = session.exec(
            select(EmailMonitorMessageMatch).where(EmailMonitorMessageMatch.message_id == message.id)
        ).all()
        related_alerts = session.exec(
            select(EmailMonitorAlertEvent).where(EmailMonitorAlertEvent.message_id == message.id)
        ).all()
        for match in related_matches:
            session.delete(match)
        for alert in related_alerts:
            session.delete(alert)
        session.delete(message)


def dispatch_internal_webhook(alert: EmailMonitorAlertEvent, account: EmailMonitorAccount, message: EmailMonitorMessage, rule: Optional[EmailMonitorRule]) -> None:
    if not rule or not rule.webhook_url:
        alert.webhook_status = EmailMonitorWebhookStatus.SKIPPED
        return
    payload = {
        "event": "email_monitor_alert",
        "account_id": str(account.id),
        "account_display_name": account.display_name,
        "message_id": str(message.id),
        "category": message.category,
        "sender_email": message.sender_email,
        "subject": message.subject,
        "sent_at": message.sent_at.isoformat() if message.sent_at else None,
        "matched_rule": rule.name,
    }
    try:
        response = requests.post(rule.webhook_url, json=payload, timeout=settings.EMAIL_MONITOR_WEBHOOK_TIMEOUT_SECONDS)
        response.raise_for_status()
        alert.webhook_status = EmailMonitorWebhookStatus.SENT
        alert.webhook_error = None
    except Exception as exc:
        alert.webhook_status = EmailMonitorWebhookStatus.FAILED
        alert.webhook_error = truncate_text(str(exc), 400)


def upsert_message(
    session: Session,
    *,
    account: EmailMonitorAccount,
    folder_name: str,
    message_uid: int,
    flags_blob: str,
    parsed_message: email.message.Message,
    internal_date: Optional[datetime.datetime],
    rules: list[EmailMonitorRule],
) -> tuple[Optional[EmailMonitorMessage], bool, bool]:
    sender_name, sender_email = parse_email_addresses(parsed_message.get("From"))
    _, recipient_email = parse_email_addresses(parsed_message.get("To"))
    subject = decode_mime_header(parsed_message.get("Subject"))
    sent_at = parse_sent_datetime(parsed_message.get("Date")) or internal_date
    body_text, body_html_sanitized = extract_message_bodies(parsed_message)
    body_preview = truncate_text(body_text or strip_html_tags(body_html_sanitized or ""), 220)
    message_id = decode_mime_header(parsed_message.get("Message-ID"))
    message_hash = build_message_hash(message_id, sender_email, subject, sent_at, body_preview)
    body_hash = compute_secondary_hash(body_text or "", body_html_sanitized or "")
    headers = build_message_headers(parsed_message)

    existing = session.exec(
        select(EmailMonitorMessage).where(
            EmailMonitorMessage.account_id == account.id,
            EmailMonitorMessage.folder_name == folder_name,
            EmailMonitorMessage.message_uid == message_uid,
        )
    ).first()
    if existing is not None:
        existing.is_read_remote = "\\Seen" in flags_blob
        existing.internal_date = internal_date or existing.internal_date
        existing.sent_at = sent_at or existing.sent_at
        existing.updated_at = utcnow()
        session.add(existing)
        return existing, False, existing.is_relevant

    duplicate = session.exec(
        select(EmailMonitorMessage).where(
            EmailMonitorMessage.account_id == account.id,
            EmailMonitorMessage.message_id_hash == message_hash,
        )
    ).first()
    if duplicate is not None:
        return None, False, duplicate.is_relevant

    matching_rules: list[tuple[EmailMonitorRule, str]] = []
    sender_blob = " ".join(filter(None, [sender_name, sender_email]))
    for rule in sorted_rules(rules, account.id):
        reason = rule_matches_message(
            rule,
            folder_name=folder_name,
            sender=sender_blob,
            subject=subject,
            body_text=body_text,
        )
        if reason:
            matching_rules.append((rule, reason))

    primary_rule = matching_rules[0][0] if matching_rules else None
    now = utcnow()
    is_relevant = primary_rule.mark_relevant if primary_rule else False
    category = primary_rule.category if primary_rule and primary_rule.category else None
    matched_rule_name = primary_rule.name if primary_rule else None
    message = EmailMonitorMessage(
        account_id=account.id,
        matched_rule_id=primary_rule.id if primary_rule else None,
        folder_name=folder_name,
        message_uid=message_uid,
        message_id=message_id,
        message_id_hash=message_hash,
        sender_name=sender_name,
        sender_email=sender_email,
        recipient_email=recipient_email,
        subject=subject,
        sent_at=sent_at,
        internal_date=internal_date,
        headers_json=headers,
        body_text=body_text,
        body_html_sanitized=body_html_sanitized,
        body_preview=body_preview,
        raw_size_bytes=len(parsed_message.as_bytes()),
        body_hash=body_hash,
        is_relevant=is_relevant,
        is_read_remote="\\Seen" in flags_blob,
        is_read_internal=False,
        is_archived=False,
        is_highlighted=primary_rule.highlight if primary_rule else False,
        category=category,
        matched_rule_name=matched_rule_name,
        matched_at=now if primary_rule else None,
        provider_message_url=build_provider_message_url(account.email, message_id),
    )
    session.add(message)
    session.flush()

    for rule, reason in matching_rules:
        session.add(
            EmailMonitorMessageMatch(
                message_id=message.id,
                rule_id=rule.id,
                matched_at=now,
                reason_summary=truncate_text(reason, 255) or rule.name,
            )
        )

    if primary_rule and primary_rule.raise_dashboard_alert:
        alert = EmailMonitorAlertEvent(
            account_id=account.id,
            message_id=message.id,
            rule_id=primary_rule.id,
            category=category,
            sender_email=sender_email,
            subject=subject,
        )
        session.add(alert)
        session.flush()
        dispatch_internal_webhook(alert, account, message, primary_rule)

    return message, True, is_relevant


def sync_account(session: Session, account: EmailMonitorAccount, *, trigger_source: str = "manual", force: bool = False) -> EmailMonitorSyncRun:
    lock = get_account_lock(account.id)
    if not lock.acquire(blocking=False):
        raise RuntimeError("A conta já está em sincronização.")

    sync_run = EmailMonitorSyncRun(account_id=account.id, trigger_source=trigger_source)
    session.add(sync_run)
    session.flush()

    connection = None
    try:
        account.sync_status = EmailMonitorSyncStatus.SYNCING
        account.last_synced_at = utcnow()
        session.add(account)
        session.commit()
        session.refresh(account)
        session.refresh(sync_run)

        password = decrypt_data(account.imap_password_encrypted)
        if not password:
            raise RuntimeError("Não foi possível descriptografar a senha IMAP armazenada.")

        connection = build_connection(account.imap_host, account.imap_port, account.use_ssl)
        connection.login(account.imap_username, password)

        rules = session.exec(
            select(EmailMonitorRule).where(
                EmailMonitorRule.enabled == True,
                or_(EmailMonitorRule.account_id == None, EmailMonitorRule.account_id == account.id),
            )
        ).all()

        total_scanned = 0
        total_saved = 0
        total_relevant = 0
        now = utcnow()

        for folder_name in normalize_folder_list(account.selected_folders_json):
            folder_state = get_folder_state(session, account.id, folder_name)
            if trigger_source == "scheduler" and not force and folder_state.next_retry_at and folder_state.next_retry_at > now:
                continue

            status, _ = connection.select(folder_name, readonly=True)
            if status != "OK":
                folder_state.last_error_at = now
                folder_state.last_error_message = f"Nao foi possivel abrir a pasta {folder_name}."
                folder_state.consecutive_failures += 1
                session.add(folder_state)
                continue

            status, data = connection.uid("search", None, "ALL")
            if status != "OK":
                raise RuntimeError(f"Falha ao listar mensagens da pasta {folder_name}.")

            all_uids = [int(item) for item in (data[0].split() if data and data[0] else [])]
            batch_uids = select_incremental_uids(all_uids, folder_state.last_seen_uid, settings.EMAIL_MONITOR_SYNC_BATCH_SIZE)
            sync_run.folders_scanned += 1

            for uid in batch_uids:
                status, fetch_data = connection.uid("fetch", str(uid), "(RFC822 FLAGS INTERNALDATE)")
                if status != "OK":
                    continue
                raw_bytes, flags_blob, internal_date = extract_fetch_payload(fetch_data)
                if raw_bytes is None:
                    continue
                parsed_message = BytesParser(policy=policy.default).parsebytes(raw_bytes)
                _, saved, relevant = upsert_message(
                    session,
                    account=account,
                    folder_name=folder_name,
                    message_uid=uid,
                    flags_blob=flags_blob,
                    parsed_message=parsed_message,
                    internal_date=internal_date,
                    rules=rules,
                )
                total_scanned += 1
                if saved:
                    total_saved += 1
                if relevant:
                    total_relevant += 1
                folder_state.last_seen_uid = max(uid, folder_state.last_seen_uid or 0)
                folder_state.last_seen_internaldate = internal_date or folder_state.last_seen_internaldate
                folder_state.last_seen_message_id = decode_mime_header(parsed_message.get("Message-ID")) or folder_state.last_seen_message_id

            folder_state.last_synced_at = now
            folder_state.last_success_at = now
            folder_state.last_error_at = None
            folder_state.last_error_message = None
            folder_state.consecutive_failures = 0
            folder_state.next_retry_at = None
            session.add(folder_state)

        account.last_synced_at = now
        account.last_success_at = now
        account.last_error_at = None
        account.last_error_message = None
        account.consecutive_failures = 0
        account.next_retry_at = None
        account.sync_status = EmailMonitorSyncStatus.SUCCESS
        sync_run.status = EmailMonitorSyncRunStatus.SUCCESS
        sync_run.messages_scanned = total_scanned
        sync_run.messages_saved = total_saved
        sync_run.relevant_messages = total_relevant
        sync_run.finished_at = now
        session.add(account)
        session.add(sync_run)
        cleanup_old_irrelevant_messages(session, account)
        session.commit()
        return sync_run

    except Exception as exc:
        now = utcnow()
        raw_error = stringify_imap_exception(exc)
        friendly_error = describe_imap_error(
            exc,
            imap_host=account.imap_host,
            imap_port=account.imap_port,
            use_ssl=account.use_ssl,
        )
        account.sync_status = EmailMonitorSyncStatus.FAILED
        account.last_synced_at = now
        account.last_error_at = now
        account.last_error_message = truncate_text(friendly_error, 500)
        account.consecutive_failures += 1
        account.next_retry_at = now + datetime.timedelta(minutes=min(60, 2 ** max(0, account.consecutive_failures - 1)))
        sync_run.status = EmailMonitorSyncRunStatus.FAILED
        sync_run.error_message = truncate_text(friendly_error, 500)
        sync_run.finished_at = now
        log_imap_failure(
            f"sync:{trigger_source}",
            imap_host=account.imap_host,
            imap_port=account.imap_port,
            use_ssl=account.use_ssl,
            username=account.imap_username,
            error_message=raw_error,
        )
        session.add(account)
        session.add(sync_run)
        session.commit()
        return sync_run
    finally:
        if connection is not None:
            try:
                connection.logout()
            except Exception:
                pass
        lock.release()


def sync_active_accounts(trigger_source: str = "scheduler", force: bool = False) -> list[EmailMonitorSyncRun]:
    results: list[EmailMonitorSyncRun] = []
    with Session(engine) as session:
        accounts = session.exec(select(EmailMonitorAccount).where(EmailMonitorAccount.is_active == True)).all()
        for account in accounts:
            if trigger_source == "scheduler" and not force:
                if account.next_retry_at and account.next_retry_at > utcnow():
                    continue
                if account.last_success_at:
                    next_due_at = account.last_success_at + datetime.timedelta(minutes=account.sync_interval_minutes)
                    if next_due_at > utcnow():
                        continue
            try:
                sync_run = sync_account(session, account, trigger_source=trigger_source, force=force)
            except RuntimeError:
                continue
            results.append(sync_run)
            session.expire_all()
    return results


def delete_account_permanently(session: Session, account: EmailMonitorAccount) -> dict[str, int]:
    lock = get_account_lock(account.id)
    if not lock.acquire(blocking=False):
        raise RuntimeError("A conta ja esta em sincronizacao e nao pode ser excluida agora.")

    try:
        messages = session.exec(select(EmailMonitorMessage).where(EmailMonitorMessage.account_id == account.id)).all()
        rules = session.exec(select(EmailMonitorRule).where(EmailMonitorRule.account_id == account.id)).all()
        folder_states = session.exec(select(EmailMonitorFolderState).where(EmailMonitorFolderState.account_id == account.id)).all()
        sync_runs = session.exec(select(EmailMonitorSyncRun).where(EmailMonitorSyncRun.account_id == account.id)).all()
        alerts = session.exec(select(EmailMonitorAlertEvent).where(EmailMonitorAlertEvent.account_id == account.id)).all()

        for alert in alerts:
            session.delete(alert)

        for message in messages:
            matches = session.exec(
                select(EmailMonitorMessageMatch).where(EmailMonitorMessageMatch.message_id == message.id)
            ).all()
            for match in matches:
                session.delete(match)
            session.delete(message)

        for sync_run in sync_runs:
            session.delete(sync_run)

        for folder_state in folder_states:
            session.delete(folder_state)

        for rule in rules:
            session.delete(rule)

        session.delete(account)

        return {
            "messages": len(messages),
            "rules": len(rules),
            "folder_states": len(folder_states),
            "sync_runs": len(sync_runs),
            "alerts": len(alerts),
        }
    finally:
        lock.release()
        with _SYNC_REGISTRY_LOCK:
            _SYNC_LOCKS.pop(str(account.id), None)


def start_scheduler(stop_event: threading.Event) -> threading.Thread:
    interval_seconds = max(30, settings.IMAP_SYNC_INTERVAL_SECONDS)

    def runner() -> None:
        while not stop_event.is_set():
            try:
                sync_active_accounts(trigger_source="scheduler", force=False)
            except Exception as exc:
                print(f"EMAIL_MONITOR_SCHEDULER_ERROR: {exc}")
            stop_event.wait(interval_seconds)

    thread = threading.Thread(target=runner, name="email-monitor-scheduler", daemon=True)
    thread.start()
    return thread


def account_to_schema_payload(account: EmailMonitorAccount) -> dict[str, Any]:
    return {
        "id": account.id,
        "display_name": account.display_name,
        "email": account.email,
        "imap_host": account.imap_host,
        "imap_port": account.imap_port,
        "imap_username": account.imap_username,
        "use_ssl": account.use_ssl,
        "is_active": account.is_active,
        "selected_folders": normalize_folder_list(account.selected_folders_json),
        "sync_interval_minutes": account.sync_interval_minutes,
        "retain_irrelevant_days": account.retain_irrelevant_days,
        "last_synced_at": account.last_synced_at,
        "last_success_at": account.last_success_at,
        "last_error_at": account.last_error_at,
        "last_error_message": account.last_error_message,
        "consecutive_failures": account.consecutive_failures,
        "next_retry_at": account.next_retry_at,
        "sync_status": account.sync_status,
        "created_at": account.created_at,
        "updated_at": account.updated_at,
        "has_password": bool(account.imap_password_encrypted),
    }
