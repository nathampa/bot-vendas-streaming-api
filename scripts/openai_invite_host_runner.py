#!/usr/bin/env python3

import argparse
import email
import html
import imaplib
import json
import os
import re
import secrets
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from email import policy
from email.parser import BytesParser
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

OTP_REGEX = re.compile(r"(?<!\d)(\d{6})(?!\d)")
OPENAI_SENDER_HINTS = ("openai", "chatgpt")
OPENAI_SUBJECT_HINTS = ("code", "verification", "login", "security")
EMAIL_INPUT_SELECTORS = [
    'input[type="email"]',
    'input[autocomplete="email"]',
    'input[name="email"]',
    'input[id*="email"]',
    'input[placeholder*="email" i]',
    'input[aria-label*="email" i]',
    'input[type="text"]',
]
PASSWORD_INPUT_SELECTORS = [
    'input[type="password"]',
    'input[autocomplete="current-password"]',
    'input[name="password"]',
    'input[placeholder*="password" i]',
    'input[aria-label*="password" i]',
]
OTP_INPUT_SELECTORS = [
    'input[autocomplete="one-time-code"]',
    'input[inputmode="numeric"]',
    'input[name*="code"]',
    'input[id*="code"]',
]
ABOUT_YOU_NAME_SELECTORS = [
    'input[name="name"]',
    'input[autocomplete="name"]',
    'input[placeholder*="full name" i]',
]
ABOUT_YOU_AGE_SELECTORS = [
    'input[name="age"]',
    'input[placeholder="Age"]',
    'input[type="number"]',
]
ABOUT_YOU_BIRTHDAY_SELECTORS = [
    'input[name="birthday"]',
    'input[id*="birthday"]',
    'input[autocomplete="bday"]',
]
SIGNUP_TRIGGER_LABELS = [
    "sign up",
    "create account",
    "get started",
    "cadastrar",
    "cadastre",
    "criar conta",
]
CONTINUE_BUTTON_LABELS = [
    "continue",
    "next",
    "proceed",
    "confirm",
    "verify",
    "entrar",
    "login",
    "sign in",
    "sign up",
    "create account",
]
COOKIE_BUTTON_LABELS = [
    "reject non-essential",
    "accept all",
    "manage cookie preferences",
    "accept",
    "reject",
]
INVITE_INPUT_SELECTORS = [
    'input[placeholder*="email" i]',
    'input[name*="email" i]',
    'input[type="email"]',
    "textarea",
]
MEMBER_SEARCH_SELECTORS = [
    'input[placeholder*="search" i]',
    'input[aria-label*="search" i]',
    'input[name*="search" i]',
    'input[type="search"]',
]
REMOVE_MEMBER_LABELS = [
    "remove member",
    "remove user",
    "deactivate member",
    "deactivate user",
    "delete member",
    "cancel invite",
    "remove",
    "deactivate",
    "delete",
    "remover",
    "desativar",
    "excluir",
    "cancelar convite",
]
CONFIRM_REMOVE_LABELS = [
    "remove",
    "confirm",
    "deactivate",
    "delete",
    "yes",
    "remover",
    "confirmar",
    "desativar",
    "excluir",
    "sim",
]
OUTLOOK_URL = "https://outlook.live.com/mail/0/"
OUTLOOK_LOGIN_URL = "https://login.live.com/"
OUTLOOK_EMAIL_INPUT_SELECTORS = [
    'input[type="email"]',
    'input[name="loginfmt"]',
    'input[name*="email"]',
    'input[placeholder*="email" i]',
]
OUTLOOK_PASSWORD_INPUT_SELECTORS = [
    'input[type="password"]',
    'input[name="passwd"]',
    'input[placeholder*="password" i]',
]
OUTLOOK_SEARCH_INPUT_SELECTORS = [
    'input[placeholder*="search" i]',
    'input[aria-label*="search" i]',
    'input[type="search"]',
]
REMOVAL_SUCCESS_HINTS = (
    "removed",
    "deactivated",
    "deleted",
    "cancelled",
    "removido",
    "desativado",
    "excluido",
    "excluído",
    "cancelado",
)
SUCCESS_TEXT_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"invite sent",
        r"invitation sent",
        r"pending invitation",
        r"already invited",
    )
]
CHALLENGE_TEXT_HINTS = (
    "just a moment",
    "verify you are human",
    "enable javascript and cookies to continue",
    "cf-turnstile",
    "challenge-platform",
)
CHALLENGE_STABILIZATION_ATTEMPTS = 4
CHALLENGE_STABILIZATION_WAIT_MS = 3000
GENERIC_WORKSPACE_TEXTS = {
    "chatgpt",
    "admin",
    "back to chat",
    "members",
    "users",
    "settings",
    "workspace",
    "workspaces",
    "invite",
    "invite member",
    "invite members",
    "pending invites",
}
GENERIC_WORKSPACE_TEXT_TOKENS = (
    "workspace settings",
    "permissions & roles",
    "workspace analytics",
    "identity & access",
)
WORKSPACE_NAME_PATTERNS = (
    re.compile(r"invite members? to the (?P<name>.+?) workspace", re.IGNORECASE),
)
WORKSPACE_NAME_HTML_PATTERNS = (
    re.compile(r'"workspaceName","(?P<name>[^"]+)"', re.IGNORECASE),
    re.compile(r'\\"workspaceName\\",\\"(?P<name>[^\\"]+)\\"', re.IGNORECASE),
    re.compile(r'"workspaceName"\s*:\s*"(?P<name>[^"]+)"', re.IGNORECASE),
    re.compile(r'\\"workspaceName\\"\s*:\s*\\"(?P<name>[^\\"]+)\\"', re.IGNORECASE),
)
WORKSPACE_RENAME_MARKER_FILENAME = ".fstr_workspace_renamed.json"
WORKSPACE_RENAME_PREFIX = "FStr"
WORKSPACE_RENAME_SYMBOLS = "#_-"
WORKSPACE_NAME_INPUT_SELECTORS = [
    'input[name*="workspace" i]',
    'input[id*="workspace" i]',
    'input[placeholder*="workspace" i]',
    'input[name*="organization" i]',
    'input[id*="organization" i]',
    'input[name*="name" i]',
    'input[id*="name" i]',
    'input[placeholder*="name" i]',
]
WORKSPACE_SETTINGS_BUTTON_LABELS = [
    "workspace settings",
    "settings",
    "general",
    "workspace",
    "configuracoes",
    "configurações",
    "geral",
]
WORKSPACE_EDIT_BUTTON_LABELS = [
    "edit",
    "rename",
    "change name",
    "editar",
    "renomear",
    "alterar nome",
]
WORKSPACE_SAVE_BUTTON_LABELS = [
    "save",
    "update",
    "confirm",
    "done",
    "salvar",
    "atualizar",
    "confirmar",
    "concluir",
    "concluido",
    "concluído",
]


class HostRunnerError(Exception):
    pass


class ManualReviewRequired(HostRunnerError):
    pass


class OTPTimeoutError(HostRunnerError):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)


def decode_mime_header(raw_value: str | None) -> str:
    if not raw_value:
        return ""
    try:
        return str(email.header.make_header(email.header.decode_header(raw_value)))
    except Exception:
        return raw_value


def slugify(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("_") or "default"


def capture(page, evidence_dir: Path, name: str) -> str | None:
    try:
        path = evidence_dir / f"{slugify(name)}.png"
        page.screenshot(path=str(path), full_page=True)
        return str(path)
    except Exception:
        return None


def write_html_snapshot(page, evidence_dir: Path, name: str) -> str | None:
    try:
        path = evidence_dir / f"{slugify(name)}.html"
        path.write_text(page.content(), encoding="utf-8")
        return str(path)
    except Exception:
        return None


def first_visible_locator(page, selectors: list[str]):
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.count() > 0 and locator.is_visible():
                return locator
        except Exception:
            continue
    return None


def first_existing_locator(page, selectors: list[str]):
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.count() > 0:
                return locator
        except Exception:
            continue
    return None


def fill_visible(page, selectors: list[str], value: str) -> bool:
    locator = first_visible_locator(page, selectors)
    if not locator:
        return False
    try:
        current_value = locator.input_value(timeout=1000)
        if current_value == value:
            return True
    except Exception:
        pass
    try:
        locator.click(timeout=2000)
    except Exception:
        pass
    try:
        locator.fill(value, timeout=5000)
    except Exception:
        try:
            current_value = locator.input_value(timeout=1000)
            if current_value == value:
                return True
        except Exception:
            pass
        raise
    return True


def fill_input_by_label(page, labels: list[str], value: str) -> bool:
    for label in labels:
        try:
            locator = page.get_by_label(re.compile(label, re.IGNORECASE)).first
            if locator.count() > 0 and locator.is_visible():
                try:
                    current_value = locator.input_value(timeout=1000)
                    if current_value == value:
                        return True
                except Exception:
                    pass
                try:
                    locator.click(timeout=2000)
                except Exception:
                    pass
                locator.fill(value, timeout=5000)
                return True
        except Exception:
            continue
    return False


def fill_email_input(page, value: str) -> bool:
    return fill_visible(page, EMAIL_INPUT_SELECTORS, value) or fill_input_by_label(
        page,
        ["email", "email address", "work email", "e-mail", "endereco de email"],
        value,
    )


def fill_password_input(page, value: str) -> bool:
    return fill_visible(page, PASSWORD_INPUT_SELECTORS, value) or fill_input_by_label(
        page,
        ["password", "senha"],
        value,
    )


def fill_otp_input(page, value: str) -> bool:
    return fill_visible(page, OTP_INPUT_SELECTORS, value) or fill_input_by_label(
        page,
        ["code", "verification code", "one-time code", "codigo", "código"],
        value,
    )


def build_about_you_full_name(signup_email: str) -> str:
    local_part = signup_email.split("@", 1)[0]
    normalized = re.sub(r"[^a-zA-Z]+", " ", local_part).strip()
    if not normalized:
        return "OpenAI User"
    parts = [part.capitalize() for part in normalized.split() if part]
    if len(parts) >= 2:
        return " ".join(parts[:2])
    token = parts[0]
    if len(token) > 10:
        return f"{token[:6]} {token[6:10]}"
    return f"{token} User"


def set_input_value(locator, value: str) -> bool:
    try:
        locator.evaluate(
            """(el, val) => {
                el.value = val;
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
            }""",
            value,
        )
        return True
    except Exception:
        return False


def fill_about_you_form(page, signup_email: str) -> bool:
    full_name = build_about_you_full_name(signup_email)
    if not (
        fill_visible(page, ABOUT_YOU_NAME_SELECTORS, full_name)
        or fill_input_by_label(page, ["full name", "name", "nome completo", "nome"], full_name)
    ):
        return False

    if (
        fill_visible(page, ABOUT_YOU_AGE_SELECTORS, "30")
        or fill_input_by_label(page, ["age", "idade"], "30")
    ):
        return True

    birthday_value = "1994-01-15"
    birthday_locator = first_existing_locator(page, ABOUT_YOU_BIRTHDAY_SELECTORS)
    if birthday_locator and set_input_value(birthday_locator, birthday_value):
        return True

    birthday_fields = {
        "month": ["select[name*='month' i]", "input[name*='month' i]"],
        "day": ["select[name*='day' i]", "input[name*='day' i]"],
        "year": ["select[name*='year' i]", "input[name*='year' i]"],
    }
    values = {"month": "1", "day": "15", "year": "1994"}
    handled_any = False
    for key, selectors in birthday_fields.items():
        locator = first_existing_locator(page, selectors)
        if not locator:
            continue
        handled_any = True
        try:
            tag_name = locator.evaluate("(el) => el.tagName.toLowerCase()")
        except Exception:
            tag_name = ""
        try:
            if tag_name == "select":
                locator.select_option(values[key])
            else:
                if not set_input_value(locator, values[key]):
                    locator.fill(values[key], timeout=5000)
        except Exception:
            return False
    return handled_any


def click_first_button(page, labels: list[str]) -> bool:
    for label in labels:
        try:
            button = page.get_by_role("button", name=re.compile(label, re.IGNORECASE)).first
            if button.count() > 0 and button.is_visible():
                button.click()
                return True
        except Exception:
            continue
    return False


def click_first_button_or_link(page, labels: list[str]) -> bool:
    for label in labels:
        pattern = re.compile(label, re.IGNORECASE)
        for role in ("button", "link"):
            try:
                control = page.get_by_role(role, name=pattern).first
                if control.count() > 0 and control.is_visible():
                    control.click()
                    return True
            except Exception:
                continue
    return False


def click_primary_continue_button(page) -> bool:
    candidates = [
        r"^continue$",
        r"^next$",
        r"^sign up$",
        r"^create account$",
        r"^log in$",
        r"^entrar$",
        r"^continuar$",
        r"^proximo$",
        r"^próximo$",
    ]
    for pattern_text in candidates:
        pattern = re.compile(pattern_text, re.IGNORECASE)
        try:
            button = page.get_by_role("button", name=pattern).first
            if button.count() > 0 and button.is_visible():
                button.click()
                return True
        except Exception:
            continue
    return False


def dismiss_openai_cookie_banner(page) -> bool:
    return click_first_button_or_link(page, COOKIE_BUTTON_LABELS)


def click_openai_signup_cta(page) -> bool:
    return click_first_button_or_link(page, ["sign up for free", "sign up", "get started"])


def page_body_text(page, timeout_ms: int = 1000) -> str:
    try:
        return page.locator("body").inner_text(timeout=timeout_ms).lower()
    except Exception:
        return ""


def page_title_safe(page) -> str:
    try:
        return page.title()
    except Exception:
        return ""


def current_url_safe(page) -> str:
    try:
        return page.url or ""
    except Exception:
        return ""


def log_host_step(subject: str, step: str, page=None) -> None:
    url = current_url_safe(page) if page is not None else ""
    title = page_title_safe(page) if page is not None else ""
    print(f"[{subject}] {step} | url={url[:180]} | title={title[:120]}", flush=True)


def is_signup_landing(page, body_text: str | None = None, page_title: str | None = None) -> bool:
    body = body_text if body_text is not None else page_body_text(page)
    title = page_title if page_title is not None else ""
    signup_markers = (
        "get started",
        "sign up for free",
        "try it first",
        "log in or sign up",
    )
    return any(marker in body for marker in signup_markers) or "get started" in title


def is_google_signin(page, body_text: str | None = None, page_title: str | None = None) -> bool:
    body = body_text if body_text is not None else page_body_text(page)
    title = page_title if page_title is not None else ""
    current_url = (page.url or "").lower()
    return (
        "accounts.google.com" in current_url
        or "google.com/signin" in current_url
        or "googleusercontent.com" in current_url
        or
        "sign in - google accounts" in title
        or "sign in with google" in body
        or "couldn't find your google account" in body
        or "could not find your google account" in body
    )


def is_retryable_auth_error(page, body_text: str | None = None, page_title: str | None = None) -> bool:
    body = body_text if body_text is not None else page_body_text(page)
    title = page_title if page_title is not None else ""
    return (
        "oops, an error occurred" in title
        or "max_check_attempts" in body
        or "an error occurred during authentication" in body
        or "try again" in body and "authentication" in body
    )


def is_about_you_page(page, body_text: str | None = None, page_title: str | None = None) -> bool:
    body = body_text if body_text is not None else page_body_text(page)
    title = page_title if page_title is not None else ""
    return (
        "how old are you" in title
        or ("full name" in body and "finish creating account" in body)
        or ("date of birth" in body and "full name" in body)
        or ("birthday" in body and "full name" in body)
    )


def is_login_or_signup_email_page(
    page,
    body_text: str | None = None,
    page_title: str | None = None,
    page_html: str | None = None,
) -> bool:
    body = body_text if body_text is not None else page_body_text(page)
    title = page_title if page_title is not None else ""
    html_text = page_html if page_html is not None else ""
    auth_markers = (
        "log in or sign up",
        "continue with google",
        "continue with apple",
        "continue with microsoft",
        "continue with phone",
    )
    email_markers = (
        'name="email"',
        'type="email"',
        'placeholder="email address"',
        'action="/log-in-or-create-account"',
        'value="email"',
        "email address",
    )
    return (
        any(marker in title for marker in ("log in or sign up", "get started"))
        or any(marker in body for marker in auth_markers)
    ) and any(marker in html_text or marker in body for marker in email_markers)


def recover_signup_surface(page, launch_url: str) -> bool:
    for _ in range(4):
        if is_google_signin(page):
            page.goto(launch_url, wait_until="domcontentloaded")
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(1200)
            wait_for_spinner_to_settle(page, timeout_ms=3000)
        dismiss_openai_cookie_banner(page)
        if click_openai_signup_cta(page):
            page.wait_for_timeout(1200)
            wait_for_spinner_to_settle(page, timeout_ms=3000)
            return True
        page.goto(launch_url, wait_until="domcontentloaded")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(1200)
        wait_for_spinner_to_settle(page, timeout_ms=3000)
        dismiss_openai_cookie_banner(page)
        if click_openai_signup_cta(page):
            page.wait_for_timeout(1200)
            wait_for_spinner_to_settle(page, timeout_ms=3000)
            return True
    return False


def recover_retryable_auth_error(page, launch_url: str) -> bool:
    dismiss_openai_cookie_banner(page)
    if click_first_button_or_link(page, ["try again", "retry", "tentar novamente"]):
        page.wait_for_timeout(1500)
        wait_for_spinner_to_settle(page, timeout_ms=4000)
        current_title = ""
        try:
            current_title = (page.title() or "").lower()
        except Exception:
            current_title = ""
        if "oops, an error occurred" not in current_title:
            return True
    return recover_signup_surface(page, launch_url)


def normalize_workspace_name(raw_value: str | None) -> str | None:
    if not raw_value:
        return None
    value = re.sub(r"\s+", " ", raw_value).strip(" -|:\n\t")
    for pattern in WORKSPACE_NAME_PATTERNS:
        match = pattern.search(value)
        if match:
            value = match.group("name").strip(" -|:\n\t")
            break
    if not value or len(value) > 80:
        return None
    lowered = value.lower()
    if lowered in GENERIC_WORKSPACE_TEXTS:
        return None
    if lowered.startswith("chatgpt - admin"):
        return None
    if "@" in value:
        return None
    if any(token in lowered for token in GENERIC_WORKSPACE_TEXT_TOKENS):
        return None
    if any(token in lowered for token in ("invite member", "pending invites")):
        return None
    return value


def extract_workspace_name_from_html(html_content: str | None) -> str | None:
    if not html_content:
        return None
    for pattern in WORKSPACE_NAME_HTML_PATTERNS:
        match = pattern.search(html_content)
        if not match:
            continue
        candidate = normalize_workspace_name(html.unescape(match.group("name")))
        if candidate:
            return candidate
    return None


def extract_workspace_name(page) -> str | None:
    try:
        title = normalize_workspace_name(page.title())
        if title and "admin" not in title.lower():
            return title
    except Exception:
        pass

    selector_candidates = [
        '[data-testid*="workspace"]',
        '[aria-label*="workspace" i]',
        '[id*="workspace" i]',
        'button[aria-haspopup="menu"]',
    ]
    for selector in selector_candidates:
        try:
            locator = page.locator(selector)
            for index in range(min(locator.count(), 10)):
                candidate = normalize_workspace_name(locator.nth(index).inner_text(timeout=500))
                if candidate:
                    return candidate
        except Exception:
            continue

    try:
        buttons = page.locator("button")
        for index in range(min(buttons.count(), 12)):
            candidate = normalize_workspace_name(buttons.nth(index).inner_text(timeout=300))
            if candidate:
                return candidate
    except Exception:
        pass
    try:
        candidate = extract_workspace_name_from_html(page.content())
        if candidate:
            return candidate
    except Exception:
        pass
    return None


def generate_fstr_workspace_name() -> str:
    digits_count = secrets.randbelow(3) + 4
    digits = "".join(secrets.choice("0123456789") for _ in range(digits_count))
    return f"{WORKSPACE_RENAME_PREFIX}{secrets.choice(WORKSPACE_RENAME_SYMBOLS)}{digits}"


def workspace_rename_marker_path(session_path: Path) -> Path:
    return session_path / WORKSPACE_RENAME_MARKER_FILENAME


def workspace_rename_already_done(session_path: Path) -> bool:
    return workspace_rename_marker_path(session_path).exists()


def write_workspace_rename_marker(session_path: Path, workspace_name: str) -> None:
    marker = workspace_rename_marker_path(session_path)
    marker.write_text(
        json.dumps(
            {
                "workspace_name": workspace_name,
                "renamed_at": utcnow().isoformat(),
            },
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )
    marker.chmod(0o600)


def build_openai_admin_settings_urls(members_url: str) -> list[str]:
    parsed = urllib.parse.urlsplit(members_url)
    query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    locale_query = urllib.parse.urlencode(
        [(key, value) for key, value in query_pairs if key.lower() == "locale"],
        doseq=True,
    )
    paths = ["/admin/settings", "/admin/settings/general", "/admin/settings/workspace"]
    return [
        urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, locale_query, ""))
        for path in paths
    ]


def workspace_name_input_locator(page):
    label_patterns = [
        "workspace name",
        "organization name",
        "name",
        "nome do workspace",
        "nome do espaço de trabalho",
        "nome do espaço de trabalho",
        "nome",
    ]
    for label in label_patterns:
        try:
            locator = page.get_by_label(re.compile(label, re.IGNORECASE)).first
            if locator.count() > 0 and locator.is_visible():
                return locator
        except Exception:
            continue
    return first_visible_locator(page, WORKSPACE_NAME_INPUT_SELECTORS)


def has_workspace_name_input(page) -> bool:
    return workspace_name_input_locator(page) is not None


def open_workspace_settings(page, members_url: str) -> bool:
    for url in build_openai_admin_settings_urls(members_url):
        try:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(1500)
            wait_for_spinner_to_settle(page, timeout_ms=5000)
            if has_workspace_name_input(page):
                return True
            if click_first_button(page, WORKSPACE_EDIT_BUTTON_LABELS):
                page.wait_for_timeout(800)
                if has_workspace_name_input(page):
                    return True
        except Exception:
            continue

    goto_openai_members(page, members_url)
    wait_for_spinner_to_settle(page)
    for label in WORKSPACE_SETTINGS_BUTTON_LABELS:
        if click_first_button(page, [label]):
            page.wait_for_timeout(1000)
            wait_for_spinner_to_settle(page, timeout_ms=5000)
            if has_workspace_name_input(page):
                return True
    if click_first_button(page, WORKSPACE_EDIT_BUTTON_LABELS):
        page.wait_for_timeout(800)
        return has_workspace_name_input(page)
    return has_workspace_name_input(page)


def confirm_workspace_rename(page, members_url: str, new_workspace_name: str) -> bool:
    try:
        body_text = page.locator("body").inner_text(timeout=1500)
        if new_workspace_name.lower() in body_text.lower():
            return True
    except Exception:
        pass
    try:
        if new_workspace_name.lower() in page.content().lower():
            return True
    except Exception:
        pass
    try:
        navigate_to_invite_surface(page, members_url)
        extracted = extract_workspace_name(page)
        return bool(extracted and extracted.startswith(WORKSPACE_RENAME_PREFIX))
    except Exception:
        return False


def rename_workspace_once(page, request: dict, evidence_dir: Path) -> str | None:
    session_path = Path(request["session_path"])
    session_path.mkdir(parents=True, exist_ok=True)
    if workspace_rename_already_done(session_path):
        return None

    current_name = extract_workspace_name(page)
    if current_name and current_name.startswith(WORKSPACE_RENAME_PREFIX):
        write_workspace_rename_marker(session_path, current_name)
        return current_name

    new_workspace_name = generate_fstr_workspace_name()
    if not open_workspace_settings(page, request["members_url"]):
        capture(page, evidence_dir, "workspace_rename_settings_not_found")
        write_html_snapshot(page, evidence_dir, "workspace_rename_settings_not_found")
        raise ManualReviewRequired("Sessão autenticada, mas a tela de configurações do workspace não foi localizada.")

    if not click_first_button(page, WORKSPACE_EDIT_BUTTON_LABELS):
        page.wait_for_timeout(300)
    input_locator = workspace_name_input_locator(page)
    if not input_locator:
        capture(page, evidence_dir, "workspace_rename_input_not_found")
        write_html_snapshot(page, evidence_dir, "workspace_rename_input_not_found")
        raise ManualReviewRequired("Sessão autenticada, mas o campo de nome do workspace não foi localizado.")

    input_locator.fill(new_workspace_name)
    page.wait_for_timeout(500)
    if not click_first_button(page, WORKSPACE_SAVE_BUTTON_LABELS):
        input_locator.press("Enter")
    page.wait_for_timeout(1800)
    wait_for_spinner_to_settle(page, timeout_ms=5000)

    body_text = ""
    try:
        body_text = page.locator("body").inner_text(timeout=1500).lower()
    except Exception:
        body_text = ""
    if any(token in body_text for token in ("error", "failed", "invalid", "erro", "falha", "invalido", "inválido")):
        capture(page, evidence_dir, "workspace_rename_error")
        write_html_snapshot(page, evidence_dir, "workspace_rename_error")
        raise ManualReviewRequired("A OpenAI retornou erro ao renomear o workspace.")

    if not confirm_workspace_rename(page, request["members_url"], new_workspace_name):
        capture(page, evidence_dir, "workspace_rename_not_confirmed")
        write_html_snapshot(page, evidence_dir, "workspace_rename_not_confirmed")
        raise ManualReviewRequired("Renomeação do workspace enviada, mas não foi possível confirmar o novo nome.")

    capture(page, evidence_dir, "workspace_renamed")
    write_workspace_rename_marker(session_path, new_workspace_name)
    return new_workspace_name


def page_contains_workspace_payload(page) -> bool:
    try:
        return extract_workspace_name_from_html(page.content()) is not None
    except Exception:
        return False


def stabilize_challenge_state(page, members_url: str) -> str:
    state = detect_auth_state(page)
    if state != "captcha_required":
        return state

    revisited_admin = False
    for _ in range(CHALLENGE_STABILIZATION_ATTEMPTS):
        try:
            page.wait_for_timeout(CHALLENGE_STABILIZATION_WAIT_MS)
            page.wait_for_load_state("domcontentloaded", timeout=3000)
        except Exception:
            pass
        wait_for_spinner_to_settle(page, timeout_ms=3000)
        state = detect_auth_state(page)
        if state != "captcha_required":
            return state
        if not revisited_admin and page_contains_workspace_payload(page):
            try:
                goto_openai_members(page, members_url)
                revisited_admin = True
            except Exception:
                pass
    return detect_auth_state(page)


def wait_for_spinner_to_settle(page, timeout_ms: int = 10000) -> None:
    spinner = page.locator('[class*="animate-spin"]').first
    deadline = time.time() + (timeout_ms / 1000)
    while time.time() < deadline:
        try:
            if spinner.count() == 0 or not spinner.is_visible():
                return
        except Exception:
            return
        time.sleep(0.2)


def wait_until_button_visible(page, labels: list[str], timeout_ms: int = 10000) -> bool:
    deadline = time.time() + (timeout_ms / 1000)
    while time.time() < deadline:
        for label in labels:
            try:
                button = page.get_by_role("button", name=re.compile(f"^{re.escape(label)}$", re.IGNORECASE)).first
                if button.count() > 0 and button.is_visible():
                    return True
            except Exception:
                continue
        time.sleep(0.2)
    return False


def detect_auth_state(page) -> str:
    page_html = ""
    page_title = ""
    try:
        page_html = page.content().lower()
    except Exception:
        page_html = ""
    try:
        page_title = (page.title() or "").lower()
    except Exception:
        page_title = ""

    body_text = page_body_text(page)
    if is_google_signin(page, body_text, page_title):
        return "google_signin"
    if is_about_you_page(page, body_text, page_title):
        return "about_you_required"
    if is_login_or_signup_email_page(page, body_text, page_title, page_html):
        return "email_required"
    if is_retryable_auth_error(page, body_text, page_title):
        return "auth_error_retryable"
    if first_visible_locator(page, OTP_INPUT_SELECTORS):
        return "otp_required"
    if first_visible_locator(page, PASSWORD_INPUT_SELECTORS):
        return "password_required"
    if first_visible_locator(page, EMAIL_INPUT_SELECTORS):
        return "email_required"
    if is_signup_landing(page, body_text, page_title):
        return "signup_landing"

    if any(hint in body_text for hint in CHALLENGE_TEXT_HINTS):
        return "captcha_required"
    if any(hint in page_html for hint in CHALLENGE_TEXT_HINTS):
        return "captcha_required"
    if any(hint in page_title for hint in CHALLENGE_TEXT_HINTS):
        return "captcha_required"
    if "captcha" in body_text or "verify you are human" in body_text:
        return "captcha_required"
    if "check your inbox" in body_text or "verification code" in body_text or "resend email" in body_text:
        return "otp_required"
    if "email address" in body_text or "work email" in body_text:
        return "email_required"
    if "members" in body_text or "invite" in body_text or "workspace" in body_text:
        return "logged_in"
    if "welcome" in body_text or "what should we call you" in body_text or "tell us about" in body_text:
        return "logged_in"
    if any(fragment in page.url.lower() for fragment in ("login", "auth", "signin")):
        return "unknown_auth_state"
    return "logged_in"


def build_openai_home_url(members_url: str) -> str:
    parsed = urllib.parse.urlsplit(members_url)
    query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    locale_query = urllib.parse.urlencode(
        [(key, value) for key, value in query_pairs if key.lower() == "locale"],
        doseq=True,
    )
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/", locale_query, ""))


def goto_openai_home(page, members_url: str) -> None:
    page.goto(build_openai_home_url(members_url), wait_until="domcontentloaded")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(1500)


def goto_openai_members(page, members_url: str) -> None:
    page.goto(members_url, wait_until="domcontentloaded")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(1500)


def prewarm_openai_session(page, members_url: str) -> None:
    goto_openai_home(page, members_url)
    wait_for_spinner_to_settle(page, timeout_ms=3000)
    state = detect_auth_state(page)
    if state == "captcha_required":
        stabilize_challenge_state(page, members_url)
    wait_for_spinner_to_settle(page, timeout_ms=3000)
    goto_openai_members(page, members_url)


def navigate_to_invite_surface(page, members_url: str) -> None:
    goto_openai_members(page, members_url)
    if first_visible_locator(page, INVITE_INPUT_SELECTORS):
        return
    wait_for_spinner_to_settle(page)
    click_first_button(page, ["members", "manage members", "team", "workspace"])
    page.wait_for_timeout(1000)
    wait_for_spinner_to_settle(page)
    click_first_button(page, ["users"])
    wait_until_button_visible(page, ["Invite member"], timeout_ms=12000)
    if first_visible_locator(page, INVITE_INPUT_SELECTORS):
        return
    click_first_button(page, ["invite member", "invite members", "add member", "add members", "invite"])
    page.wait_for_timeout(1000)
    wait_for_spinner_to_settle(page)


def extract_message_bodies(message: email.message.Message) -> tuple[str, str]:
    plain_parts: list[str] = []
    html_parts: list[str] = []

    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                try:
                    plain_parts.append(part.get_content())
                except Exception:
                    pass
            elif content_type == "text/html":
                try:
                    html_parts.append(part.get_content())
                except Exception:
                    pass
    else:
        content_type = message.get_content_type()
        try:
            payload = message.get_content()
        except Exception:
            payload = ""
        if content_type == "text/plain":
            plain_parts.append(payload)
        elif content_type == "text/html":
            html_parts.append(payload)

    return ("\n".join(plain_parts), "\n".join(html_parts))


def is_openai_message(message: email.message.Message) -> bool:
    subject = decode_mime_header(message.get("Subject")).lower()
    sender = decode_mime_header(message.get("From")).lower()
    return any(hint in sender for hint in OPENAI_SENDER_HINTS) or any(
        hint in subject for hint in OPENAI_SUBJECT_HINTS
    )


def parse_sent_datetime(raw_value: str | None) -> datetime | None:
    if not raw_value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(raw_value)
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except Exception:
        return None


def extract_otp_from_message(message: email.message.Message) -> str | None:
    subject = decode_mime_header(message.get("Subject")) or ""
    plain_text, html_text = extract_message_bodies(message)
    combined = "\n".join(part for part in (subject, plain_text or "", html_text or "") if part)
    match = OTP_REGEX.search(combined)
    return match.group(1) if match else None


def fetch_openai_otp(imap_config: dict | None) -> str:
    if not imap_config:
        raise ManualReviewRequired("Nenhuma configuração IMAP disponível para buscar o OTP da OpenAI.")

    deadline = time.time() + int(imap_config.get("otp_timeout_seconds", 120))
    poll_interval = int(imap_config.get("poll_interval_seconds", 5))
    fetch_limit = int(imap_config.get("fetch_limit", 20))
    folders = imap_config.get("selected_folders") or ["INBOX"]
    last_error = None

    while time.time() < deadline:
        connection = None
        try:
            if imap_config.get("use_ssl", True):
                connection = imaplib.IMAP4_SSL(
                    imap_config["imap_host"],
                    int(imap_config["imap_port"]),
                    ssl_context=ssl.create_default_context(),
                )
            else:
                connection = imaplib.IMAP4(
                    imap_config["imap_host"],
                    int(imap_config["imap_port"]),
                )
            connection.login(imap_config["imap_username"], imap_config["imap_password"])

            for folder_name in folders:
                status, _ = connection.select(folder_name, readonly=True)
                if status != "OK":
                    continue
                status, data = connection.uid("search", None, "ALL")
                if status != "OK" or not data or not data[0]:
                    continue
                raw_uids = data[0].decode("utf-8", errors="replace").strip().split()
                for uid in reversed(raw_uids[-fetch_limit:]):
                    fetch_status, fetch_data = connection.uid("fetch", uid, "(RFC822)")
                    if fetch_status != "OK" or not fetch_data:
                        continue
                    raw_bytes = None
                    for item in fetch_data:
                        if isinstance(item, tuple) and isinstance(item[1], bytes):
                            raw_bytes = item[1]
                            break
                    if not raw_bytes:
                        continue
                    message = BytesParser(policy=policy.default).parsebytes(raw_bytes)
                    if not is_openai_message(message):
                        continue
                    sent_at = parse_sent_datetime(message.get("Date"))
                    if sent_at and sent_at < utcnow() - timedelta(minutes=15):
                        continue
                    otp = extract_otp_from_message(message)
                    if otp:
                        return otp
        except Exception as exc:
            last_error = str(exc)
        finally:
            if connection is not None:
                try:
                    connection.logout()
                except Exception:
                    pass
        time.sleep(poll_interval)

    raise OTPTimeoutError(last_error or "Código OTP da OpenAI não encontrado a tempo.")


def ensure_logged_in(page, request: dict, evidence_dir: Path) -> str:
    auth_path: list[str] = []
    prewarm_openai_session(page, request["members_url"])

    for _ in range(10):
        state = detect_auth_state(page)
        if state == "captcha_required":
            state = stabilize_challenge_state(page, request["members_url"])
        if state == "logged_in":
            return "session_reused" if not auth_path else "_then_".join(auth_path)
        if state == "captcha_required":
            capture(page, evidence_dir, "captcha_required")
            write_html_snapshot(page, evidence_dir, "captcha_required")
            raise ManualReviewRequired("Captcha detectado no fluxo host-side da OpenAI.")
        if state == "email_required":
            if not fill_visible(page, EMAIL_INPUT_SELECTORS, request["login_email"]):
                break
            auth_path.append("email")
            if not click_first_button(page, ["continue", "next", "proceed", "entrar", "login", "sign in"]):
                page.keyboard.press("Enter")
            page.wait_for_timeout(1200)
            continue
        if state == "password_required":
            if not fill_visible(page, PASSWORD_INPUT_SELECTORS, request["login_password"]):
                break
            auth_path.append("password")
            if not click_first_button(page, ["continue", "next", "entrar", "login", "sign in"]):
                page.keyboard.press("Enter")
            page.wait_for_timeout(1500)
            continue
        if state == "otp_required":
            auth_path.append("otp")
            otp = fetch_openai_otp(request.get("imap"))
            if not fill_visible(page, OTP_INPUT_SELECTORS, otp):
                raise ManualReviewRequired("A tela pediu OTP, mas nenhum campo compatível foi encontrado.")
            if not click_first_button(page, ["continue", "verify", "confirm", "next"]):
                page.keyboard.press("Enter")
            page.wait_for_timeout(1500)
            continue

        capture(page, evidence_dir, "unknown_auth_state")
        write_html_snapshot(page, evidence_dir, "unknown_auth_state")
        raise ManualReviewRequired(f"Estado de autenticação não reconhecido: {state}")

    capture(page, evidence_dir, "auth_loop_exhausted")
    write_html_snapshot(page, evidence_dir, "auth_loop_exhausted")
    raise ManualReviewRequired("Fluxo de autenticação não convergiu para uma sessão logada.")


def send_invite(page, request: dict, evidence_dir: Path) -> str | None:
    navigate_to_invite_surface(page, request["members_url"])
    if not first_visible_locator(page, INVITE_INPUT_SELECTORS):
        capture(page, evidence_dir, "invite_surface_not_found")
        write_html_snapshot(page, evidence_dir, "invite_surface_not_found")
        raise ManualReviewRequired("Não foi possível localizar a interface de convite da OpenAI.")

    if not fill_visible(page, INVITE_INPUT_SELECTORS, request["invite_email"]):
        raise ManualReviewRequired("Campo de email de convite não encontrado.")

    page.wait_for_timeout(500)
    if not click_first_button(page, ["invite", "send invite", "add member", "add members", "send"]):
        page.keyboard.press("Enter")
    page.wait_for_timeout(2000)

    body_text = page.locator("body").inner_text(timeout=1500).lower()
    if any(pattern.search(body_text) for pattern in SUCCESS_TEXT_PATTERNS):
        capture(page, evidence_dir, "invite_sent")
        return extract_workspace_name(page)
    if "error" in body_text or "invalid" in body_text:
        capture(page, evidence_dir, "invite_error")
        write_html_snapshot(page, evidence_dir, "invite_error")
        raise HostRunnerError("A OpenAI retornou erro ao enviar o convite.")
    capture(page, evidence_dir, "invite_post_submit")
    return extract_workspace_name(page)


def click_labeled_action(page, labels: list[str]) -> bool:
    for label in labels:
        pattern = re.compile(label, re.IGNORECASE)
        for role in ("menuitem", "button"):
            try:
                item = page.get_by_role(role, name=pattern).first
                if item.count() > 0 and item.is_visible():
                    item.click()
                    return True
            except Exception:
                continue
    return False


def find_member_email_locator(page, email_cliente: str):
    exact_pattern = re.compile(f"^{re.escape(email_cliente)}$", re.IGNORECASE)
    loose_pattern = re.compile(re.escape(email_cliente), re.IGNORECASE)
    for pattern in (exact_pattern, loose_pattern):
        try:
            locator = page.get_by_text(pattern).first
            if locator.count() > 0 and locator.is_visible():
                return locator
        except Exception:
            continue
    return None


def fill_member_search_if_available(page, email_cliente: str) -> None:
    search = first_visible_locator(page, MEMBER_SEARCH_SELECTORS)
    if not search:
        return
    try:
        search.fill(email_cliente)
        page.wait_for_timeout(1000)
        wait_for_spinner_to_settle(page, timeout_ms=3000)
    except Exception:
        return


def navigate_to_members_surface(page, members_url: str) -> None:
    goto_openai_members(page, members_url)
    wait_for_spinner_to_settle(page)
    click_first_button(page, ["members", "manage members", "team", "workspace"])
    page.wait_for_timeout(800)
    wait_for_spinner_to_settle(page)
    click_first_button(page, ["users", "members"])
    page.wait_for_timeout(800)
    wait_for_spinner_to_settle(page)


def open_member_actions_menu(page, email_cliente: str) -> bool:
    email_locator = find_member_email_locator(page, email_cliente)
    if not email_locator:
        return False

    row = email_locator.locator(
        "xpath=ancestor::*[@role='row' or self::tr or self::li or self::div][1]"
    )
    menu_selectors = [
        'button[aria-haspopup="menu"]',
        'button[aria-label*="more" i]',
        'button[aria-label*="options" i]',
        'button[aria-label*="actions" i]',
        'button:has-text("...")',
    ]
    for selector in menu_selectors:
        try:
            button = row.locator(selector).last
            if button.count() > 0 and button.is_visible():
                button.click()
                page.wait_for_timeout(400)
                return True
        except Exception:
            continue

    try:
        buttons = row.locator("button")
        count = buttons.count()
        if count > 0:
            buttons.nth(count - 1).click()
            page.wait_for_timeout(400)
            return True
    except Exception:
        pass
    return False


def confirm_member_removal(page) -> None:
    page.wait_for_timeout(500)
    click_labeled_action(page, CONFIRM_REMOVE_LABELS)
    page.wait_for_timeout(1500)
    wait_for_spinner_to_settle(page, timeout_ms=5000)


def remove_member(page, request: dict, evidence_dir: Path) -> str:
    email_cliente = request["member_email"]
    navigate_to_members_surface(page, request["members_url"])
    fill_member_search_if_available(page, email_cliente)

    if not find_member_email_locator(page, email_cliente):
        capture(page, evidence_dir, "member_not_found")
        return "NOT_FOUND"

    if not open_member_actions_menu(page, email_cliente):
        capture(page, evidence_dir, "member_actions_not_found")
        write_html_snapshot(page, evidence_dir, "member_actions_not_found")
        raise ManualReviewRequired("Membro localizado, mas o menu de ações não foi encontrado.")
    if not click_labeled_action(page, REMOVE_MEMBER_LABELS):
        capture(page, evidence_dir, "remove_action_not_found")
        write_html_snapshot(page, evidence_dir, "remove_action_not_found")
        raise ManualReviewRequired("Menu de membro aberto, mas a ação de remoção não foi localizada.")

    confirm_member_removal(page)
    body_text = page.locator("body").inner_text(timeout=1500).lower()
    fill_member_search_if_available(page, email_cliente)
    if not find_member_email_locator(page, email_cliente):
        capture(page, evidence_dir, "member_removed")
        return "REMOVED"
    if any(hint in body_text for hint in REMOVAL_SUCCESS_HINTS):
        capture(page, evidence_dir, "member_removed_success_hint")
        return "REMOVED"

    capture(page, evidence_dir, "member_removal_uncertain")
    write_html_snapshot(page, evidence_dir, "member_removal_uncertain")
    raise ManualReviewRequired("A remoção foi enviada, mas não foi possível confirmar que o membro saiu da lista.")


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def clear_stale_profile_locks(session_path: Path) -> None:
    lock_path = session_path / "SingletonLock"
    if not lock_path.exists() and not lock_path.is_symlink():
        return

    current_hostname = socket.gethostname()
    lock_target = ""
    try:
        lock_target = os.readlink(lock_path)
    except OSError:
        try:
            lock_target = lock_path.read_text(encoding="utf-8")
        except Exception:
            lock_target = ""

    pid = None
    host = None
    if "-" in lock_target:
        host, _, raw_pid = lock_target.rpartition("-")
        if raw_pid.isdigit():
            pid = int(raw_pid)

    if host == current_hostname and pid and process_exists(pid):
        raise HostRunnerError(
            f"O perfil da OpenAI ainda está em uso pelo processo {pid}. Feche o Chrome dessa conta na VM e tente novamente."
        )

    for name in ("SingletonCookie", "SingletonLock", "SingletonSocket", "DevToolsActivePort"):
        target = session_path / name
        if target.exists() or target.is_symlink():
            target.unlink(missing_ok=True)


def wait_for_devtools(port: int, process: subprocess.Popen) -> str:
    deadline = time.time() + 20
    version_url = f"http://127.0.0.1:{port}/json/version"
    while time.time() < deadline:
        if process.poll() is not None:
            raise HostRunnerError("O Google Chrome host-side encerrou antes de expor o DevTools.")
        try:
            with urllib.request.urlopen(version_url, timeout=1) as response:
                payload = json.loads(response.read().decode("utf-8"))
                websocket_url = payload.get("webSocketDebuggerUrl")
                if websocket_url:
                    return f"http://127.0.0.1:{port}"
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
            pass
        time.sleep(0.2)
    raise HostRunnerError("Tempo esgotado ao conectar no DevTools do Google Chrome host-side.")


@contextmanager
def virtual_display(width: int = 1440, height: int = 960, depth: int = 24):
    xvfb_binary = shutil.which("Xvfb")
    if not xvfb_binary:
        raise HostRunnerError("Xvfb não encontrado no host.")

    display_number = 90
    while Path(f"/tmp/.X11-unix/X{display_number}").exists():
        display_number += 1
    display = f":{display_number}"
    process = subprocess.Popen(
        [
            xvfb_binary,
            display,
            "-screen",
            "0",
            f"{width}x{height}x{depth}",
            "-nolisten",
            "tcp",
            "-ac",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 5
        socket_path = Path(f"/tmp/.X11-unix/X{display_number}")
        while time.time() < deadline:
            if process.poll() is not None:
                raise HostRunnerError("O Xvfb do host encerrou antes de iniciar.")
            if socket_path.exists():
                break
            time.sleep(0.1)
        else:
            raise HostRunnerError("Tempo esgotado ao iniciar o Xvfb do host.")
        yield display
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)


@contextmanager
def launched_host_chrome(request: dict):
    chrome_binary = shutil.which("google-chrome") or shutil.which("google-chrome-stable")
    if not chrome_binary:
        raise HostRunnerError("Google Chrome não encontrado no host.")

    session_path = Path(request["session_path"])
    session_path.mkdir(parents=True, exist_ok=True)
    clear_stale_profile_locks(session_path)
    evidence_dir = Path(request["evidence_dir"])
    evidence_dir.mkdir(parents=True, exist_ok=True)
    debug_port = find_free_port()

    with virtual_display() as display:
        env = dict(os.environ)
        env["DISPLAY"] = display
        env.setdefault("HOME", str(Path("/opt/bot-vendas/runtime/openai-host-home")))
        Path(env["HOME"]).mkdir(parents=True, exist_ok=True)
        args = [
            chrome_binary,
            "--disable-gpu",
            "--use-gl=swiftshader",
            "--ozone-platform=x11",
            "--no-first-run",
            "--no-default-browser-check",
            "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={debug_port}",
            f"--user-data-dir={session_path}",
            request.get("launch_url") or request["members_url"],
        ]
        process = subprocess.Popen(
            args,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            endpoint = wait_for_devtools(debug_port, process)
            yield endpoint, process
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)


@contextmanager
def launch_host_chrome_profile(profile_dir: Path, launch_url: str):
    chrome_binary = shutil.which("google-chrome") or shutil.which("google-chrome-stable")
    if not chrome_binary:
        raise HostRunnerError("Google Chrome nao encontrado no host.")
    profile_dir.mkdir(parents=True, exist_ok=True)
    clear_stale_profile_locks(profile_dir)
    debug_port = find_free_port()
    with virtual_display() as display:
        env = dict(os.environ)
        env["DISPLAY"] = display
        env.setdefault("HOME", str(Path("/opt/bot-vendas/runtime/openai-host-home")))
        Path(env["HOME"]).mkdir(parents=True, exist_ok=True)
        args = [
            chrome_binary,
            "--disable-gpu",
            "--use-gl=swiftshader",
            "--ozone-platform=x11",
            "--no-first-run",
            "--no-default-browser-check",
            "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={debug_port}",
            f"--user-data-dir={profile_dir}",
            launch_url,
        ]
        process = subprocess.Popen(
            args,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            endpoint = wait_for_devtools(debug_port, process)
            yield endpoint, process
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)


def is_outlook_mail_experience(page) -> bool:
    url = current_url_safe(page).lower()
    text = page_body_text(page)
    if "outlook.live.com/mail" not in url and "outlook.office.com/mail" not in url:
        return False
    return any(marker in text for marker in ("inbox", "focused", "other", "search", "junk email", "drafts"))


def click_outlook_text(page, labels: list[str]) -> bool:
    for label in labels:
        pattern = re.compile(label, re.IGNORECASE)
        for role in ("button", "link"):
            try:
                locator = page.get_by_role(role, name=pattern).first
                if locator.count() > 0 and locator.is_visible():
                    locator.click()
                    return True
            except Exception:
                continue
        try:
            locator = page.get_by_text(pattern).first
            if locator.count() > 0 and locator.is_visible():
                locator.click()
                return True
        except Exception:
            continue
    return False


def outlook_body_text(page, timeout_ms: int = 2000) -> str:
    try:
        return page.locator("body").inner_text(timeout=timeout_ms)
    except Exception:
        return ""


def login_outlook_web(page, email_value: str, password_value: str) -> None:
    log_host_step(email_value, "start_login", page)
    page.goto(OUTLOOK_LOGIN_URL, wait_until="domcontentloaded")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(1500)

    for _ in range(12):
        current_body = outlook_body_text(page).lower()
        if is_outlook_mail_experience(page):
            log_host_step(email_value, "mail_experience_ready_from_login", page)
            return

        if "manage cookie" in current_body or "cookie preferences" in current_body or "accept reject" in current_body:
            if click_outlook_text(page, ["reject", "accept"]):
                log_host_step(email_value, "cookie_banner_handled", page)
                page.wait_for_timeout(1500)
                continue

        if (
            "create free account" in current_body
            or "continue to sign in" in current_body
            or ("download the free app" in current_body and "sign in" in current_body)
        ):
            if click_outlook_text(page, ["continue to sign in", "sign in", "continue"]):
                log_host_step(email_value, "clicked_continue_to_sign_in", page)
                page.wait_for_timeout(2000)
                continue

        email_input = first_visible_locator(page, OUTLOOK_EMAIL_INPUT_SELECTORS)
        if email_input:
            email_input.fill(email_value)
            if not click_outlook_text(page, ["next", "continue", "sign in", "entrar", "avancar"]):
                page.keyboard.press("Enter")
            log_host_step(email_value, "submitted_email", page)
            page.wait_for_timeout(1500)
            continue

        password_input = first_visible_locator(page, OUTLOOK_PASSWORD_INPUT_SELECTORS)
        if password_input:
            password_input.fill(password_value)
            if not click_outlook_text(page, ["sign in", "log in", "next", "entrar", "continuar"]):
                page.keyboard.press("Enter")
            log_host_step(email_value, "submitted_password", page)
            page.wait_for_timeout(2000)
            continue

        state = detect_auth_state(page)
        if state == "captcha_required":
            raise ManualReviewRequired("Captcha/challenge detectado no login do Outlook.")

        current_url = current_url_safe(page).lower()
        if "account.microsoft.com" in current_url or "privacynotice.account.microsoft.com" in current_url:
            log_host_step(email_value, "handoff_to_inbox_ready_from_account_home", page)
            return

        if "sign in" in current_body and "microsoft" in current_body:
            log_host_step(email_value, "redirecting_from_generic_sign_in", page)
            page.goto(OUTLOOK_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            continue

        if click_outlook_text(page, ["no", "not now", "skip", "maybe later", "nao", "não"]):
            log_host_step(email_value, "dismissed_prompt_negative", page)
            page.wait_for_timeout(1500)
            continue
        if click_outlook_text(page, ["yes", "ok", "continue", "entendi"]):
            log_host_step(email_value, "accepted_prompt_positive", page)
            page.wait_for_timeout(1500)
            continue

        page.wait_for_timeout(1500)

    raise HostRunnerError("Fluxo de login do Outlook nao convergiu para a inbox.")


def click_outlook_mail_navigation_link(page) -> bool:
    selectors = [
        'a[href*="outlook.live.com/mail"]',
        'a[href*="outlook.office.com/mail"]',
        'a[href*="/mail/"]',
    ]
    locator = first_visible_locator(page, selectors)
    if locator:
        locator.click()
        return True
    return click_outlook_text(page, ["outlook", "mail", "inbox", "view inbox"])


def ensure_outlook_inbox_ready(page) -> None:
    for _ in range(8):
        log_host_step("system", "ensure_inbox_ready_loop", page)
        if is_outlook_mail_experience(page):
            log_host_step("system", "inbox_ready", page)
            return
        if click_outlook_mail_navigation_link(page):
            page.wait_for_timeout(2500)
            if is_outlook_mail_experience(page):
                log_host_step("system", "inbox_ready_after_click", page)
                return
        log_host_step("system", "forcing_outlook_url", page)
        page.goto(OUTLOOK_URL, wait_until="commit", timeout=15000)
        page.wait_for_timeout(2000)
        current_body = outlook_body_text(page).lower()
        if "continue to sign in" in current_body or ("sign in" in current_body and "outlook" in current_body):
            click_outlook_text(page, ["continue to sign in", "sign in", "continue"])
            log_host_step("system", "clicked_continue_during_inbox_ready", page)
            page.wait_for_timeout(2000)
            continue
        current_url = current_url_safe(page).lower()
        if "account.microsoft.com" in current_url or "privacynotice.account.microsoft.com" in current_url:
            log_host_step("system", "still_on_account_home", page)
            page.wait_for_timeout(1500)
            continue
    raise HostRunnerError("Nao foi possivel estabilizar a inbox do Outlook.")


def extract_outlook_openai_otp(page) -> str | None:
    if not is_outlook_mail_experience(page):
        return None
    page_body = outlook_body_text(page, timeout_ms=3000)
    match = OTP_REGEX.search(page_body or "")
    if match:
        return match.group(1)
    try:
        html_content = page.content()
    except Exception:
        html_content = ""
    match = OTP_REGEX.search(html_content or "")
    if match:
        return match.group(1)
    return None


def open_first_matching_outlook_message(page) -> bool:
    if not is_outlook_mail_experience(page):
        return False
    for pattern in (
        re.compile(r"openai", re.IGNORECASE),
        re.compile(r"chatgpt", re.IGNORECASE),
        re.compile(r"verification", re.IGNORECASE),
        re.compile(r"code", re.IGNORECASE),
    ):
        try:
            locator = page.get_by_text(pattern).first
            if locator.count() > 0 and locator.is_visible():
                locator.click()
                page.wait_for_timeout(2500)
                return True
        except Exception:
            continue
    return False


def search_and_open_outlook_mail(page) -> bool:
    if not is_outlook_mail_experience(page):
        return False
    search = first_visible_locator(page, OUTLOOK_SEARCH_INPUT_SELECTORS)
    if search:
        for term in ("OpenAI", "ChatGPT", "verification code"):
            try:
                search.fill(term)
                page.keyboard.press("Enter")
                page.wait_for_timeout(2500)
                if open_first_matching_outlook_message(page):
                    return True
            except Exception:
                continue
    return open_first_matching_outlook_message(page)


def maybe_switch_outlook_folder(page, folder_labels: list[str]) -> bool:
    if not is_outlook_mail_experience(page):
        return False
    if click_outlook_text(page, folder_labels):
        page.wait_for_timeout(2000)
        return True
    return False
def run_session_test(request: dict) -> dict:
    tested_at = utcnow().isoformat()
    evidence_dir = Path(request["evidence_dir"])
    evidence_dir.mkdir(parents=True, exist_ok=True)

    with launched_host_chrome(request) as (endpoint, _):
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(endpoint)
            try:
                context = browser.contexts[0]
                page = context.pages[0] if context.pages else context.new_page()
                prewarm_openai_session(page, request["members_url"])
                current_url = page.url
                state = detect_auth_state(page)
                if state == "captcha_required":
                    state = stabilize_challenge_state(page, request["members_url"])

                if state == "captcha_required":
                    capture(page, evidence_dir, "session_test_challenge")
                    html_path = write_html_snapshot(page, evidence_dir, "session_test_challenge")
                    return {
                        "status": "CHALLENGE",
                        "message": "A OpenAI/Cloudflare pediu uma verificação manual nesta sessão.",
                        "tested_at": tested_at,
                        "current_url": current_url,
                        "evidence_path": html_path,
                    }
                if state in {"email_required", "password_required", "otp_required", "unknown_auth_state"}:
                    capture(page, evidence_dir, "session_test_login_required")
                    html_path = write_html_snapshot(page, evidence_dir, "session_test_login_required")
                    return {
                        "status": "NEEDS_LOGIN",
                        "message": "A sessão ainda não está autenticada. Faça o login manual na VM e teste novamente.",
                        "tested_at": tested_at,
                        "current_url": current_url,
                        "evidence_path": html_path,
                    }

                workspace_renamed = rename_workspace_once(page, request, evidence_dir)
                navigate_to_invite_surface(page, request["members_url"])
                current_url = page.url
                if first_visible_locator(page, INVITE_INPUT_SELECTORS):
                    capture(page, evidence_dir, "session_test_valid")
                    message = "Sessão válida e pronta para automação de convites."
                    if workspace_renamed:
                        message = f"{message} Workspace renomeado para {workspace_renamed}."
                    return {
                        "status": "VALID",
                        "message": message,
                        "tested_at": tested_at,
                        "current_url": current_url,
                        "evidence_path": None,
                    }

                capture(page, evidence_dir, "session_test_invite_not_found")
                html_path = write_html_snapshot(page, evidence_dir, "session_test_invite_not_found")
                return {
                    "status": "MANUAL_REVIEW",
                    "message": "Sessão autenticada, mas a interface de convites não foi localizada automaticamente.",
                    "tested_at": tested_at,
                    "current_url": current_url,
                    "evidence_path": html_path,
                }
            finally:
                browser.close()


def run_send_invite(request: dict) -> dict:
    evidence_dir = Path(request["evidence_dir"])
    evidence_dir.mkdir(parents=True, exist_ok=True)

    with launched_host_chrome(request) as (endpoint, _):
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(endpoint)
            try:
                context = browser.contexts[0]
                page = context.pages[0] if context.pages else context.new_page()
                auth_path = ensure_logged_in(page, request, evidence_dir)
                rename_workspace_once(page, request, evidence_dir)
                workspace_name = send_invite(page, request, evidence_dir)
                return {
                    "status": "SENT",
                    "message": "Convite enviado com sucesso.",
                    "auth_path_used": auth_path,
                    "workspace_name": workspace_name,
                    "evidence_path": str(evidence_dir),
                }
            finally:
                browser.close()


def run_remove_member(request: dict) -> dict:
    evidence_dir = Path(request["evidence_dir"])
    evidence_dir.mkdir(parents=True, exist_ok=True)

    with launched_host_chrome(request) as (endpoint, _):
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(endpoint)
            try:
                context = browser.contexts[0]
                page = context.pages[0] if context.pages else context.new_page()
                auth_path = ensure_logged_in(page, request, evidence_dir)
                status = remove_member(page, request, evidence_dir)
                return {
                    "status": status,
                    "message": "Membro removido ou já ausente do workspace.",
                    "auth_path_used": auth_path,
                    "evidence_path": str(evidence_dir),
                }
            finally:
                browser.close()


def navigate_to_signup_surface(page, launch_url: str) -> None:
    page.goto(launch_url, wait_until="domcontentloaded")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(1500)
    wait_for_spinner_to_settle(page, timeout_ms=3000)
    dismiss_openai_cookie_banner(page)
    click_openai_signup_cta(page)
    page.wait_for_timeout(1200)
    wait_for_spinner_to_settle(page, timeout_ms=3000)


def submit_default_continue(page) -> None:
    if not click_primary_continue_button(page):
        page.keyboard.press("Enter")


def run_create_account(request: dict) -> dict:
    evidence_dir = Path(request["evidence_dir"])
    evidence_dir.mkdir(parents=True, exist_ok=True)
    otp_code = request.get("otp_code")

    with launched_host_chrome(request) as (endpoint, _):
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(endpoint)
            try:
                context = browser.contexts[0]
                page = context.pages[0] if context.pages else context.new_page()
                navigate_to_signup_surface(page, request["launch_url"])
                auth_path: list[str] = []

                for _ in range(12):
                    wait_for_spinner_to_settle(page, timeout_ms=4000)
                    dismiss_openai_cookie_banner(page)
                    state = detect_auth_state(page)
                    if state == "captcha_required":
                        state = stabilize_challenge_state(page, request["launch_url"])
                    if state == "captcha_required":
                        capture(page, evidence_dir, "account_creation_captcha")
                        write_html_snapshot(page, evidence_dir, "account_creation_captcha")
                        raise ManualReviewRequired("Captcha detectado no fluxo host-side da OpenAI.")
                    if state == "auth_error_retryable":
                        if "otp" in auth_path:
                            otp_code = None
                            auth_path.append("otp_expired_restart")
                        if recover_retryable_auth_error(page, request["launch_url"]):
                            page.wait_for_timeout(1200)
                            continue
                        capture(page, evidence_dir, "account_creation_auth_error")
                        html_path = write_html_snapshot(page, evidence_dir, "account_creation_auth_error")
                        return {
                            "status": "MANUAL_REVIEW",
                            "message": "A OpenAI retornou erro de autenticacao e o fluxo nao conseguiu reiniciar automaticamente.",
                            "auth_path_used": "_then_".join(auth_path) if auth_path else None,
                            "evidence_path": html_path or str(evidence_dir),
                        }
                    if state == "google_signin":
                        if not recover_signup_surface(page, request["launch_url"]):
                            capture(page, evidence_dir, "account_creation_google_signin")
                            html_path = write_html_snapshot(page, evidence_dir, "account_creation_google_signin")
                            return {
                                "status": "MANUAL_REVIEW",
                                "message": "Fluxo desviou para Google Sign-In durante a criacao da conta.",
                                "auth_path_used": "_then_".join(auth_path) if auth_path else None,
                                "evidence_path": html_path or str(evidence_dir),
                            }
                        page.wait_for_timeout(1200)
                        continue
                    if state == "signup_landing":
                        if recover_signup_surface(page, request["launch_url"]):
                            page.wait_for_timeout(1200)
                            continue
                    if state == "email_required":
                        if not fill_email_input(page, request["signup_email"]):
                            break
                        auth_path.append("email")
                        submit_default_continue(page)
                        page.wait_for_timeout(1500)
                        continue
                    if state == "about_you_required":
                        if not fill_about_you_form(page, request["signup_email"]):
                            raise ManualReviewRequired("A OpenAI abriu a etapa de nome e idade/data de nascimento, mas os campos nao foram localizados.")
                        auth_path.append("about_you")
                        submit_default_continue(page)
                        page.wait_for_timeout(2000)
                        continue
                    if state == "password_required":
                        if not fill_password_input(page, request["signup_password"]):
                            break
                        auth_path.append("password")
                        submit_default_continue(page)
                        page.wait_for_timeout(1500)
                        continue
                    if state == "otp_required":
                        if otp_code and "otp" in auth_path:
                            otp_code = None
                        if not otp_code:
                            capture(page, evidence_dir, "account_creation_waiting_otp")
                            html_path = write_html_snapshot(page, evidence_dir, "account_creation_waiting_otp")
                            return {
                                "status": "WAITING_OTP_INPUT",
                                "message": "Conta aguardando codigo OTP informado manualmente no painel.",
                                "auth_path_used": "_then_".join(auth_path + ["otp_pending"]) if auth_path else "otp_pending",
                                "evidence_path": html_path or str(evidence_dir),
                            }
                        if not fill_otp_input(page, otp_code):
                            raise ManualReviewRequired("A tela pediu OTP, mas nenhum campo compatível foi encontrado.")
                        auth_path.append("otp")
                        submit_default_continue(page)
                        page.wait_for_timeout(2000)
                        continue
                    if state == "logged_in":
                        capture(page, evidence_dir, "account_created")
                        html_path = write_html_snapshot(page, evidence_dir, "account_created")
                        return {
                            "status": "CREATED",
                            "message": "Conta OpenAI criada com sucesso.",
                            "auth_path_used": "_then_".join(auth_path) if auth_path else "session_reused",
                            "workspace_name": extract_workspace_name(page),
                            "evidence_path": html_path or str(evidence_dir),
                        }
                    if state == "unknown_auth_state":
                        current_url = (page.url or "").lower()
                        if any(fragment in current_url for fragment in ("auth.openai.com", "login", "signin", "log-in-or-create-account")):
                            page.wait_for_timeout(1500)
                            wait_for_spinner_to_settle(page, timeout_ms=3000)
                            dismiss_openai_cookie_banner(page)
                            retry_state = detect_auth_state(page)
                            if retry_state != "unknown_auth_state":
                                continue
                            if recover_signup_surface(page, request["launch_url"]):
                                page.wait_for_timeout(1200)
                                continue

                    capture(page, evidence_dir, "account_creation_unknown_state")
                    html_path = write_html_snapshot(page, evidence_dir, "account_creation_unknown_state")
                    return {
                        "status": "MANUAL_REVIEW",
                        "message": f"Estado nao reconhecido durante a criacao da conta: {state}",
                        "auth_path_used": "_then_".join(auth_path) if auth_path else None,
                        "evidence_path": html_path or str(evidence_dir),
                    }

                capture(page, evidence_dir, "account_creation_exhausted")
                html_path = write_html_snapshot(page, evidence_dir, "account_creation_exhausted")
                return {
                    "status": "MANUAL_REVIEW",
                    "message": "Fluxo de criacao de conta OpenAI nao convergiu para um estado final reconhecido.",
                    "auth_path_used": "_then_".join(auth_path) if auth_path else None,
                    "evidence_path": html_path or str(evidence_dir),
                }
            finally:
                browser.close()


def run_fetch_outlook_otp(request: dict) -> dict:
    evidence_dir = Path(request["evidence_dir"])
    evidence_dir.mkdir(parents=True, exist_ok=True)
    profile_dir = Path(request["profile_dir"])
    subject = request.get("outlook_email") or "outlook"

    with sync_playwright() as playwright:
        browser = None
        try:
            with launch_host_chrome_profile(profile_dir, OUTLOOK_URL) as (endpoint, _):
                browser = playwright.chromium.connect_over_cdp(endpoint)
                context = browser.contexts[0]
                page = context.pages[0] if context.pages else context.new_page()
                login_outlook_web(page, request["outlook_email"], request["outlook_password"])
                ensure_outlook_inbox_ready(page)
                log_host_step(subject, "searching_for_openai_mail", page)

                if search_and_open_outlook_mail(page):
                    otp_code = extract_outlook_openai_otp(page)
                    if otp_code:
                        capture(page, evidence_dir, "otp_found")
                        html_path = write_html_snapshot(page, evidence_dir, "otp_found")
                        return {
                            "status": "OTP_FOUND",
                            "message": "Codigo OTP encontrado no Outlook web.",
                            "otp_code": otp_code,
                            "evidence_path": html_path or str(evidence_dir),
                        }

                for folder_labels in (["junk email", "spam", "junk"], ["other"]):
                    if maybe_switch_outlook_folder(page, folder_labels):
                        if search_and_open_outlook_mail(page):
                            otp_code = extract_outlook_openai_otp(page)
                            if otp_code:
                                capture(page, evidence_dir, "otp_found_alt_folder")
                                html_path = write_html_snapshot(page, evidence_dir, "otp_found_alt_folder")
                                return {
                                    "status": "OTP_FOUND",
                                    "message": "Codigo OTP encontrado no Outlook web.",
                                    "otp_code": otp_code,
                                    "evidence_path": html_path or str(evidence_dir),
                                }

                capture(page, evidence_dir, "otp_not_found")
                html_path = write_html_snapshot(page, evidence_dir, "otp_not_found")
                return {
                    "status": "OTP_NOT_FOUND",
                    "message": "Nao encontrei OTP visivel da OpenAI na inbox/junk do Outlook.",
                    "evidence_path": html_path or str(evidence_dir),
                }
        finally:
            if browser is not None:
                browser.close()


def process_request_payload(request: dict) -> dict:
    action = request.get("action")
    if action == "session_test":
        return run_session_test(request)
    if action == "send_invite":
        return run_send_invite(request)
    if action == "remove_member":
        return run_remove_member(request)
    if action == "create_account":
        return run_create_account(request)
    if action == "fetch_outlook_otp":
        return run_fetch_outlook_otp(request)
    raise HostRunnerError(f"Ação desconhecida para o runner host-side: {action}")


def normalize_result(request: dict, result: dict) -> dict:
    return {
        "request_id": request.get("request_id"),
        "action": request.get("action"),
        **result,
    }


def process_request_file(request_path: Path) -> dict:
    request = json.loads(request_path.read_text(encoding="utf-8"))
    try:
        result = normalize_result(request, process_request_payload(request))
    except OTPTimeoutError as exc:
        result = normalize_result(
            request,
            {
                "status": "FAILED",
                "message": str(exc),
                "auth_step_failed": "otp",
                "evidence_path": request.get("evidence_dir"),
            },
        )
    except ManualReviewRequired as exc:
        result = normalize_result(
            request,
            {
                "status": "MANUAL_REVIEW",
                "message": str(exc),
                "evidence_path": request.get("evidence_dir"),
            },
        )
    except (HostRunnerError, PlaywrightTimeoutError) as exc:
        result = normalize_result(
            request,
            {
                "status": "FAILED",
                "message": str(exc),
                "evidence_path": request.get("evidence_dir"),
            },
        )
    except Exception as exc:
        result = normalize_result(
            request,
            {
                "status": "FAILED",
                "message": f"Falha inesperada no runner host-side: {exc}",
                "evidence_path": request.get("evidence_dir"),
            },
        )

    result_path = Path(request["result_path"])
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, ensure_ascii=True), encoding="utf-8")
    result_path.chmod(0o600)
    return result


def daemon_loop(queue_root: Path, poll_interval: float) -> None:
    requests_dir = queue_root / "requests"
    requests_dir.mkdir(parents=True, exist_ok=True)
    while True:
        for request_path in sorted(requests_dir.glob("*.json")):
            processing_path = request_path.with_suffix(".processing")
            try:
                request_path.replace(processing_path)
            except FileNotFoundError:
                continue
            try:
                process_request_file(processing_path)
            finally:
                processing_path.unlink(missing_ok=True)
        time.sleep(poll_interval)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-file")
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--queue-root", default="/opt/bot-vendas/runtime/openai-invite-host-runner")
    parser.add_argument("--poll-interval", type=float, default=1.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.daemon:
        daemon_loop(Path(args.queue_root), args.poll_interval)
        return 0
    if not args.request_file:
        raise SystemExit("--request-file e obrigatorio fora do modo --daemon")
    result = process_request_file(Path(args.request_file))
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
