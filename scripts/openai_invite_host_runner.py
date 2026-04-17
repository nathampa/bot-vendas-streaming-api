#!/usr/bin/env python3

import argparse
import email
import html
import imaplib
import json
import os
import re
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
]
PASSWORD_INPUT_SELECTORS = [
    'input[type="password"]',
    'input[autocomplete="current-password"]',
    'input[name="password"]',
]
OTP_INPUT_SELECTORS = [
    'input[autocomplete="one-time-code"]',
    'input[inputmode="numeric"]',
    'input[name*="code"]',
    'input[id*="code"]',
]
INVITE_INPUT_SELECTORS = [
    'input[placeholder*="email" i]',
    'input[name*="email" i]',
    'input[type="email"]',
    "textarea",
]
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


def fill_visible(page, selectors: list[str], value: str) -> bool:
    locator = first_visible_locator(page, selectors)
    if not locator:
        return False
    locator.fill(value)
    return True


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

    if first_visible_locator(page, OTP_INPUT_SELECTORS):
        return "otp_required"
    if first_visible_locator(page, PASSWORD_INPUT_SELECTORS):
        return "password_required"
    if first_visible_locator(page, EMAIL_INPUT_SELECTORS):
        return "email_required"

    body_text = page.locator("body").inner_text(timeout=1000).lower()
    if any(hint in body_text for hint in CHALLENGE_TEXT_HINTS):
        return "captcha_required"
    if any(hint in page_html for hint in CHALLENGE_TEXT_HINTS):
        return "captcha_required"
    if any(hint in page_title for hint in CHALLENGE_TEXT_HINTS):
        return "captcha_required"
    if "captcha" in body_text or "verify you are human" in body_text:
        return "captcha_required"
    if "members" in body_text or "invite" in body_text or "workspace" in body_text:
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
        raise ManualReviewRequired("Nenhuma configuracao IMAP disponivel para buscar o OTP da OpenAI.")

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

    raise OTPTimeoutError(last_error or "Codigo OTP da OpenAI nao encontrado a tempo.")


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
                raise ManualReviewRequired("A tela pediu OTP, mas nenhum campo compativel foi encontrado.")
            if not click_first_button(page, ["continue", "verify", "confirm", "next"]):
                page.keyboard.press("Enter")
            page.wait_for_timeout(1500)
            continue

        capture(page, evidence_dir, "unknown_auth_state")
        write_html_snapshot(page, evidence_dir, "unknown_auth_state")
        raise ManualReviewRequired(f"Estado de autenticacao nao reconhecido: {state}")

    capture(page, evidence_dir, "auth_loop_exhausted")
    write_html_snapshot(page, evidence_dir, "auth_loop_exhausted")
    raise ManualReviewRequired("Fluxo de autenticacao nao convergiu para uma sessao logada.")


def send_invite(page, request: dict, evidence_dir: Path) -> str | None:
    navigate_to_invite_surface(page, request["members_url"])
    if not first_visible_locator(page, INVITE_INPUT_SELECTORS):
        capture(page, evidence_dir, "invite_surface_not_found")
        write_html_snapshot(page, evidence_dir, "invite_surface_not_found")
        raise ManualReviewRequired("Nao foi possivel localizar a interface de convite da OpenAI.")

    if not fill_visible(page, INVITE_INPUT_SELECTORS, request["invite_email"]):
        raise ManualReviewRequired("Campo de email de convite nao encontrado.")

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
            f"O perfil da OpenAI ainda esta em uso pelo processo {pid}. Feche o Chrome dessa conta na VM e tente novamente."
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
        raise HostRunnerError("Xvfb nao encontrado no host.")

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
        raise HostRunnerError("Google Chrome nao encontrado no host.")

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
            request["members_url"],
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
                        "message": "A OpenAI/Cloudflare pediu uma verificacao manual nesta sessao.",
                        "tested_at": tested_at,
                        "current_url": current_url,
                        "evidence_path": html_path,
                    }
                if state in {"email_required", "password_required", "otp_required", "unknown_auth_state"}:
                    capture(page, evidence_dir, "session_test_login_required")
                    html_path = write_html_snapshot(page, evidence_dir, "session_test_login_required")
                    return {
                        "status": "NEEDS_LOGIN",
                        "message": "A sessao ainda nao esta autenticada. Faca o login manual na VM e teste novamente.",
                        "tested_at": tested_at,
                        "current_url": current_url,
                        "evidence_path": html_path,
                    }

                navigate_to_invite_surface(page, request["members_url"])
                current_url = page.url
                if first_visible_locator(page, INVITE_INPUT_SELECTORS):
                    capture(page, evidence_dir, "session_test_valid")
                    return {
                        "status": "VALID",
                        "message": "Sessao valida e pronta para automacao de convites.",
                        "tested_at": tested_at,
                        "current_url": current_url,
                        "evidence_path": None,
                    }

                capture(page, evidence_dir, "session_test_invite_not_found")
                html_path = write_html_snapshot(page, evidence_dir, "session_test_invite_not_found")
                return {
                    "status": "MANUAL_REVIEW",
                    "message": "Sessao autenticada, mas a interface de convites nao foi localizada automaticamente.",
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


def process_request_payload(request: dict) -> dict:
    action = request.get("action")
    if action == "session_test":
        return run_session_test(request)
    if action == "send_invite":
        return run_send_invite(request)
    raise HostRunnerError(f"Acao desconhecida para o runner host-side: {action}")


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
