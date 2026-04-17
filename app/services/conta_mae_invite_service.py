import datetime
import email
import json
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks
from sqlmodel import Session, select

from app.core.config import settings
from app.db.database import engine
from app.models.conta_mae_models import (
    ContaMae,
    ContaMaeConvite,
    ContaMaeInviteJob,
    ContaMaeInviteJobStatus,
)
from app.models.email_monitor_models import EmailMonitorAccount
from app.models.pedido_models import Pedido
from app.models.produto_models import Produto
from app.models.usuario_models import Usuario
from app.services.email_monitor_service import (
    build_connection,
    decode_mime_header,
    extract_message_bodies,
    normalize_folder_list,
    parse_sent_datetime,
    stringify_imap_exception,
)
from app.services.notification_service import (
    send_openai_invite_failure_admin_alert,
    send_openai_invite_sent_message,
)
from app.services.security import decrypt_data

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover
    PlaywrightTimeoutError = Exception
    sync_playwright = None


class InviteAutomationError(Exception):
    pass


class ManualReviewRequired(InviteAutomationError):
    pass


class OTPTimeoutError(InviteAutomationError):
    pass


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
GENERIC_WORKSPACE_TEXTS = {
    "chatgpt",
    "admin",
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


def utcnow() -> datetime.datetime:
    return datetime.datetime.utcnow()


def slugify(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("_") or "default"


def session_root() -> Path:
    root = Path(settings.OPENAI_INVITE_SESSION_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return root


def evidence_root() -> Path:
    root = Path(settings.OPENAI_INVITE_EVIDENCE_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return root


def host_runner_root() -> Path:
    root = Path(settings.OPENAI_INVITE_HOST_RUNNER_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return root


def host_runner_requests_dir() -> Path:
    path = host_runner_root() / "requests"
    path.mkdir(parents=True, exist_ok=True)
    return path


def host_runner_results_dir() -> Path:
    path = host_runner_root() / "results"
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_session_path(conta_mae: ContaMae) -> str:
    if conta_mae.session_storage_path:
        return conta_mae.session_storage_path
    return str(session_root() / f"conta_mae_{conta_mae.id}")


def build_evidence_dir(job: ContaMaeInviteJob) -> Path:
    path = evidence_root() / str(job.id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_session_test_evidence_dir(conta_mae: ContaMae) -> Path:
    path = evidence_root() / f"session-test-{conta_mae.id}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_host_runner_request_path(request_id: uuid.UUID) -> Path:
    return host_runner_requests_dir() / f"{request_id}.json"


def build_host_runner_result_path(request_id: uuid.UUID) -> Path:
    return host_runner_results_dir() / f"{request_id}.json"


def job_result_payload(job: ContaMaeInviteJob) -> dict:
    return {
        "id": str(job.id),
        "status": job.status.value if hasattr(job.status, "value") else str(job.status),
        "conta_mae_id": str(job.conta_mae_id),
        "email_cliente": job.email_cliente,
        "attempt_count": job.attempt_count,
        "last_error": job.last_error,
        "auth_path_used": job.auth_path_used,
        "auth_step_failed": job.auth_step_failed,
        "evidence_path": job.evidence_path,
    }


def job_to_schema_payload(job: ContaMaeInviteJob) -> dict:
    return {
        "id": job.id,
        "convite_id": job.convite_id,
        "conta_mae_id": job.conta_mae_id,
        "pedido_id": job.pedido_id,
        "email_cliente": job.email_cliente,
        "status": job.status.value if hasattr(job.status, "value") else str(job.status),
        "attempt_count": job.attempt_count,
        "auth_path_used": job.auth_path_used,
        "auth_step_failed": job.auth_step_failed,
        "last_error": job.last_error,
        "evidence_path": job.evidence_path,
        "locked_at": job.locked_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def create_invite_job_for_convite(session: Session, convite: ContaMaeConvite) -> ContaMaeInviteJob:
    existing = session.exec(
        select(ContaMaeInviteJob).where(ContaMaeInviteJob.convite_id == convite.id)
    ).first()
    if existing:
        return existing

    job = ContaMaeInviteJob(
        convite_id=convite.id,
        conta_mae_id=convite.conta_mae_id,
        pedido_id=convite.pedido_id,
        email_cliente=convite.email_cliente.strip(),
        status=ContaMaeInviteJobStatus.PENDING,
    )
    session.add(job)
    session.flush()
    return job


def process_invite_job_task(job_id: str) -> None:
    try:
        processed_job = process_invite_job(uuid.UUID(job_id))
        print(
            "BACKGROUND TASK: Job de convite processado. "
            f"id={processed_job['id']} status={processed_job['status']}"
        )
    except Exception as exc:
        print(f"ERRO CRÍTICO na tarefa local de convite ({job_id}): {exc}")


def enqueue_invite_job(
    job_id: uuid.UUID,
    *,
    background_tasks: Optional[BackgroundTasks] = None,
) -> None:
    if not settings.OPENAI_INVITE_AUTOMATION_ENABLED:
        return
    if settings.CELERY_BROKER_URL:
        from app.worker.celery_app import celery_app

        celery_app.send_task("process_conta_mae_invite_job", args=[str(job_id)])
        return
    if background_tasks is not None:
        background_tasks.add_task(process_invite_job_task, str(job_id))
        return
    threading.Thread(
        target=process_invite_job_task,
        args=(str(job_id),),
        daemon=True,
        name=f"openai-invite-{job_id}",
    ).start()


def retry_invite_job(session: Session, job: ContaMaeInviteJob) -> ContaMaeInviteJob:
    if job.status == ContaMaeInviteJobStatus.SENT:
        raise ManualReviewRequired("O job já foi concluído com sucesso.")
    job.status = ContaMaeInviteJobStatus.PENDING
    job.last_error = None
    job.auth_step_failed = None
    job.locked_at = None
    job.started_at = None
    job.finished_at = None
    session.add(job)
    session.flush()
    return job


def host_runner_enabled() -> bool:
    return settings.OPENAI_INVITE_HOST_RUNNER_ENABLED


def find_email_monitor_account_for_conta_mae(session: Session, conta_mae: ContaMae) -> Optional[EmailMonitorAccount]:
    if conta_mae.email_monitor_account_id:
        account = session.get(EmailMonitorAccount, conta_mae.email_monitor_account_id)
        if account and account.is_active:
            return account

    login = (conta_mae.login or "").strip().lower()
    if not login:
        return None

    for field_name in (EmailMonitorAccount.email, EmailMonitorAccount.imap_username):
        account = session.exec(
            select(EmailMonitorAccount)
            .where(field_name == login)
            .where(EmailMonitorAccount.is_active == True)
        ).first()
        if account:
            return account
    return None


def iter_recent_message_uids(connection, limit: int) -> list[int]:
    status, data = connection.uid("search", None, "ALL")
    if status != "OK" or not data or not data[0]:
        return []
    raw_uids = data[0].decode("utf-8", errors="replace").strip().split()
    uids: list[int] = []
    for item in raw_uids[-limit:]:
        if item.isdigit():
            uids.append(int(item))
    return uids


def extract_otp_from_message(message: email.message.Message) -> Optional[str]:
    subject = decode_mime_header(message.get("Subject")) or ""
    plain_text, html_text = extract_message_bodies(message)
    combined = "\n".join(part for part in (subject, plain_text or "", html_text or "") if part)
    match = OTP_REGEX.search(combined)
    return match.group(1) if match else None


def is_openai_message(message: email.message.Message) -> bool:
    subject = (decode_mime_header(message.get("Subject")) or "").lower()
    sender = (decode_mime_header(message.get("From")) or "").lower()
    sender_match = any(hint in sender for hint in OPENAI_SENDER_HINTS)
    subject_match = any(hint in subject for hint in OPENAI_SUBJECT_HINTS)
    return sender_match or subject_match


def fetch_openai_otp_via_imap(session: Session, conta_mae: ContaMae) -> str:
    account = find_email_monitor_account_for_conta_mae(session, conta_mae)
    if not account:
        raise ManualReviewRequired("Nenhuma conta de email monitor vinculada à conta-mãe.")

    password = decrypt_data(account.imap_password_encrypted)
    if not password:
        raise ManualReviewRequired("Não foi possível descriptografar a senha IMAP da conta vinculada.")

    deadline = time.time() + settings.OPENAI_INVITE_OTP_TIMEOUT_SECONDS
    last_error: Optional[str] = None

    while time.time() < deadline:
        connection = None
        try:
            connection = build_connection(account.imap_host, account.imap_port, account.use_ssl)
            connection.login(account.imap_username, password)
            folders = normalize_folder_list(account.selected_folders_json)
            for folder_name in folders:
                status, _ = connection.select(folder_name, readonly=True)
                if status != "OK":
                    continue
                for uid in reversed(iter_recent_message_uids(connection, settings.OPENAI_INVITE_IMAP_FETCH_LIMIT)):
                    fetch_status, fetch_data = connection.uid("fetch", str(uid), "(RFC822)")
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
                    if sent_at and sent_at < utcnow() - datetime.timedelta(minutes=15):
                        continue
                    otp = extract_otp_from_message(message)
                    if otp:
                        return otp
        except Exception as exc:
            last_error = stringify_imap_exception(exc)
        finally:
            if connection is not None:
                try:
                    connection.logout()
                except Exception:
                    pass
        time.sleep(settings.OPENAI_INVITE_OTP_POLL_INTERVAL_SECONDS)

    raise OTPTimeoutError(last_error or "Código OTP da OpenAI não encontrado a tempo.")


def build_imap_credentials_payload(
    session: Session,
    conta_mae: ContaMae,
) -> Optional[dict]:
    account = find_email_monitor_account_for_conta_mae(session, conta_mae)
    if not account:
        return None

    password = decrypt_data(account.imap_password_encrypted)
    if not password:
        return None

    return {
        "email": account.email,
        "imap_host": account.imap_host,
        "imap_port": account.imap_port,
        "imap_username": account.imap_username,
        "imap_password": password,
        "use_ssl": account.use_ssl,
        "selected_folders": normalize_folder_list(account.selected_folders_json),
        "fetch_limit": settings.OPENAI_INVITE_IMAP_FETCH_LIMIT,
        "poll_interval_seconds": settings.OPENAI_INVITE_OTP_POLL_INTERVAL_SECONDS,
        "otp_timeout_seconds": settings.OPENAI_INVITE_OTP_TIMEOUT_SECONDS,
    }


def write_host_runner_request(payload: dict) -> tuple[uuid.UUID, Path]:
    request_id = uuid.uuid4()
    request_path = build_host_runner_request_path(request_id)
    result_path = build_host_runner_result_path(request_id)
    full_payload = {
        **payload,
        "request_id": str(request_id),
        "result_path": str(result_path),
        "created_at": utcnow().isoformat(),
    }
    temp_path = request_path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(full_payload, ensure_ascii=True), encoding="utf-8")
    temp_path.chmod(0o600)
    temp_path.replace(request_path)
    return request_id, result_path


def wait_for_host_runner_result(result_path: Path) -> dict:
    deadline = time.time() + settings.OPENAI_INVITE_HOST_RUNNER_TIMEOUT_SECONDS
    while time.time() < deadline:
        if result_path.exists():
            try:
                payload = json.loads(result_path.read_text(encoding="utf-8"))
            finally:
                result_path.unlink(missing_ok=True)
            return payload
        time.sleep(0.5)
    raise InviteAutomationError("O runner host-side da OpenAI nao respondeu a tempo.")


def execute_host_runner_request(payload: dict) -> dict:
    _, result_path = write_host_runner_request(payload)
    return wait_for_host_runner_result(result_path)


def build_host_runner_session_test_request(conta_mae: ContaMae) -> dict:
    session_path = Path(build_session_path(conta_mae))
    evidence_dir = build_session_test_evidence_dir(conta_mae)
    return {
        "action": "session_test",
        "session_path": str(session_path),
        "evidence_dir": str(evidence_dir),
        "members_url": settings.OPENAI_INVITE_MEMBERS_URL,
    }


def build_host_runner_invite_request(
    session: Session,
    job: ContaMaeInviteJob,
    conta_mae: ContaMae,
) -> dict:
    password = decrypt_data(conta_mae.senha)
    if not password:
        raise ManualReviewRequired("Nao foi possivel descriptografar a senha da conta-mae.")

    return {
        "action": "send_invite",
        "job_id": str(job.id),
        "session_path": build_session_path(conta_mae),
        "evidence_dir": str(build_evidence_dir(job)),
        "members_url": settings.OPENAI_INVITE_MEMBERS_URL,
        "login_email": conta_mae.login,
        "login_password": password,
        "invite_email": job.email_cliente,
        "imap": build_imap_credentials_payload(session, conta_mae),
    }


def first_visible_locator(page, selectors: list[str]):
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.count() > 0 and locator.is_visible():
                return locator
        except Exception:
            continue
    return None


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
    if not value or len(value) > 80:
        return None
    lowered = value.lower()
    if lowered in GENERIC_WORKSPACE_TEXTS:
        return None
    if lowered.startswith("chatgpt - admin"):
        return None
    if "@" in value:
        return None
    if any(token in lowered for token in ("invite member", "pending invites", "workspace settings")):
        return None
    return value


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
    return None


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


def fill_visible(page, selectors: list[str], value: str) -> bool:
    locator = first_visible_locator(page, selectors)
    if not locator:
        return False
    locator.fill(value)
    return True


def capture(page, evidence_dir: Path, name: str) -> Optional[str]:
    try:
        path = evidence_dir / f"{slugify(name)}.png"
        page.screenshot(path=str(path), full_page=True)
        return str(path)
    except Exception:
        return None


def write_html_snapshot(page, evidence_dir: Path, name: str) -> Optional[str]:
    try:
        path = evidence_dir / f"{slugify(name)}.html"
        path.write_text(page.content(), encoding="utf-8")
        return str(path)
    except Exception:
        return None


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


def goto_openai_members(page) -> None:
    page.goto(settings.OPENAI_INVITE_MEMBERS_URL, wait_until="domcontentloaded")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(1500)


def browser_viewport() -> dict[str, int]:
    return {
        "width": settings.OPENAI_INVITE_VIRTUAL_DISPLAY_WIDTH,
        "height": settings.OPENAI_INVITE_VIRTUAL_DISPLAY_HEIGHT,
    }


def browser_launch_args() -> list[str]:
    return [
        "--disable-gpu",
        "--use-gl=swiftshader",
        "--ozone-platform=x11",
        "--no-first-run",
        "--no-default-browser-check",
    ]


def should_fallback_to_headless(exc: Exception) -> bool:
    lowered = str(exc).lower()
    return (
        "target page, context or browser has been closed" in lowered
        or "sigtrap" in lowered
        or "browser has been closed" in lowered
    )


def next_virtual_display() -> str:
    for display_number in range(90, 110):
        socket_path = Path(f"/tmp/.X11-unix/X{display_number}")
        if not socket_path.exists():
            return f":{display_number}"
    raise InviteAutomationError("Nao foi possivel reservar um display virtual livre para a automacao.")


def wait_for_virtual_display(display: str, process: subprocess.Popen) -> None:
    socket_path = Path(f"/tmp/.X11-unix/X{display.removeprefix(':')}")
    deadline = time.time() + settings.OPENAI_INVITE_XVFB_START_TIMEOUT_SECONDS
    while time.time() < deadline:
        if process.poll() is not None:
            raise InviteAutomationError("O Xvfb encerrou antes de disponibilizar o display virtual.")
        if socket_path.exists():
            return
        time.sleep(0.1)
    raise InviteAutomationError("Tempo esgotado ao iniciar o display virtual da automacao.")


@contextmanager
def maybe_virtual_display():
    if not settings.OPENAI_INVITE_VIRTUAL_DISPLAY_ENABLED:
        yield None
        return

    xvfb_binary = shutil.which("Xvfb")
    if not xvfb_binary:
        raise InviteAutomationError("Xvfb nao esta disponivel no ambiente da API para automacao headful.")

    display = next_virtual_display()
    process = subprocess.Popen(
        [
            xvfb_binary,
            display,
            "-screen",
            "0",
            (
                f"{settings.OPENAI_INVITE_VIRTUAL_DISPLAY_WIDTH}"
                f"x{settings.OPENAI_INVITE_VIRTUAL_DISPLAY_HEIGHT}"
                f"x{settings.OPENAI_INVITE_VIRTUAL_DISPLAY_COLOR_DEPTH}"
            ),
            "-nolisten",
            "tcp",
            "-ac",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_virtual_display(display, process)
        yield display
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)


def playwright_launch_env(display: Optional[str]) -> Optional[dict[str, str]]:
    if not display:
        return None
    env = dict(os.environ)
    env["DISPLAY"] = display
    env.setdefault("HOME", "/tmp")
    return env


def launch_browser_context(playwright, session_path: Path, *, headless: bool, display: Optional[str]):
    launch_kwargs = {
        "user_data_dir": str(session_path),
        "headless": headless,
        "viewport": browser_viewport(),
        "args": browser_launch_args(),
    }
    env = playwright_launch_env(display)
    if env:
        launch_kwargs["env"] = env
    return playwright.chromium.launch_persistent_context(**launch_kwargs)


@contextmanager
def launch_conta_mae_browser_context(playwright, session_path: Path):
    if settings.OPENAI_INVITE_VIRTUAL_DISPLAY_ENABLED:
        try:
            with maybe_virtual_display() as display:
                context = launch_browser_context(
                    playwright,
                    session_path,
                    headless=False,
                    display=display,
                )
                try:
                    yield context
                    return
                finally:
                    context.close()
        except Exception as exc:
            if not should_fallback_to_headless(exc):
                raise

    context = launch_browser_context(
        playwright,
        session_path,
        headless=True if settings.OPENAI_INVITE_VIRTUAL_DISPLAY_ENABLED else settings.OPENAI_INVITE_HEADLESS,
        display=None,
    )
    try:
        yield context
    finally:
        context.close()


def build_manual_session_launch_command(conta_mae: ContaMae) -> str:
    session_path = build_session_path(conta_mae)
    flags = [
        "google-chrome",
        "--disable-gpu",
        "--use-gl=swiftshader",
        "--ozone-platform=x11",
        "--no-first-run",
        "--no-default-browser-check",
        f"--user-data-dir={shlex.quote(session_path)}",
        "--new-window",
        shlex.quote(settings.OPENAI_INVITE_MEMBERS_URL),
    ]
    return " ".join(flags)


def prepare_conta_mae_session(conta_mae: ContaMae) -> dict:
    session_path = Path(build_session_path(conta_mae))
    session_path.mkdir(parents=True, exist_ok=True)
    conta_mae.session_storage_path = str(session_path)
    return {
        "conta_mae_id": conta_mae.id,
        "session_storage_path": str(session_path),
        "launch_url": settings.OPENAI_INVITE_MEMBERS_URL,
        "launch_command": build_manual_session_launch_command(conta_mae),
        "browser_hint": "Abra esse comando na VM via RDP, conclua o login e depois feche o Chrome antes de testar.",
    }


def test_conta_mae_session(conta_mae: ContaMae) -> dict:
    tested_at = utcnow()
    session_path = Path(build_session_path(conta_mae))
    session_path.mkdir(parents=True, exist_ok=True)
    evidence_dir = build_session_test_evidence_dir(conta_mae)

    if host_runner_enabled():
        try:
            result = execute_host_runner_request(build_host_runner_session_test_request(conta_mae))
            return {
                "conta_mae_id": conta_mae.id,
                "session_storage_path": str(session_path),
                "status": result.get("status", "ERROR"),
                "message": result.get("message", "Runner host-side nao retornou mensagem."),
                "tested_at": result.get("tested_at", tested_at),
                "current_url": result.get("current_url"),
                "evidence_path": result.get("evidence_path"),
            }
        except InviteAutomationError as exc:
            return {
                "conta_mae_id": conta_mae.id,
                "session_storage_path": str(session_path),
                "status": "ERROR",
                "message": str(exc),
                "tested_at": tested_at,
                "current_url": None,
                "evidence_path": None,
            }

    if sync_playwright is None:
        return {
            "conta_mae_id": conta_mae.id,
            "session_storage_path": str(session_path),
            "status": "ERROR",
            "message": "Playwright não está disponível para validar a sessão.",
            "tested_at": tested_at,
            "current_url": None,
            "evidence_path": None,
        }

    try:
        with sync_playwright() as playwright:
            try:
                context_manager = launch_conta_mae_browser_context(playwright, session_path)
                context = context_manager.__enter__()
            except Exception as exc:
                lowered = str(exc).lower()
                profile_in_use = "singleton" in lowered or "in use" in lowered
                return {
                    "conta_mae_id": conta_mae.id,
                    "session_storage_path": str(session_path),
                    "status": "PROFILE_IN_USE" if profile_in_use else "ERROR",
                    "message": "Feche o Chrome dessa conta na VM antes de testar a sessão."
                    if profile_in_use
                    else f"Não foi possível abrir o perfil persistente: {exc}",
                    "tested_at": tested_at,
                    "current_url": None,
                    "evidence_path": None,
                }

            try:
                context.set_default_timeout(settings.OPENAI_INVITE_PAGE_TIMEOUT_MS)
                page = context.pages[0] if context.pages else context.new_page()
                goto_openai_members(page)
                current_url = page.url
                state = detect_auth_state(page)

                if state == "captcha_required":
                    capture(page, evidence_dir, "session_test_challenge")
                    html_path = write_html_snapshot(page, evidence_dir, "session_test_challenge")
                    return {
                        "conta_mae_id": conta_mae.id,
                        "session_storage_path": str(session_path),
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
                        "conta_mae_id": conta_mae.id,
                        "session_storage_path": str(session_path),
                        "status": "NEEDS_LOGIN",
                        "message": "A sessão ainda não está autenticada. Faça o login manual na VM e teste novamente.",
                        "tested_at": tested_at,
                        "current_url": current_url,
                        "evidence_path": html_path,
                    }

                navigate_to_invite_surface(page)
                current_url = page.url
                if first_visible_locator(page, INVITE_INPUT_SELECTORS):
                    capture(page, evidence_dir, "session_test_valid")
                    return {
                        "conta_mae_id": conta_mae.id,
                        "session_storage_path": str(session_path),
                        "status": "VALID",
                        "message": "Sessão válida e pronta para automação de convites.",
                        "tested_at": tested_at,
                        "current_url": current_url,
                        "evidence_path": None,
                    }

                capture(page, evidence_dir, "session_test_invite_not_found")
                html_path = write_html_snapshot(page, evidence_dir, "session_test_invite_not_found")
                return {
                    "conta_mae_id": conta_mae.id,
                    "session_storage_path": str(session_path),
                    "status": "MANUAL_REVIEW",
                    "message": "Sessão autenticada, mas a interface de convites não foi localizada automaticamente.",
                    "tested_at": tested_at,
                    "current_url": current_url,
                    "evidence_path": html_path,
                }
            except PlaywrightTimeoutError as exc:
                return {
                    "conta_mae_id": conta_mae.id,
                    "session_storage_path": str(session_path),
                    "status": "ERROR",
                    "message": f"Tempo esgotado ao validar a sessão: {exc}",
                    "tested_at": tested_at,
                    "current_url": None,
                    "evidence_path": None,
                }
            finally:
                context_manager.__exit__(None, None, None)
    except Exception as exc:
        return {
            "conta_mae_id": conta_mae.id,
            "session_storage_path": str(session_path),
            "status": "ERROR",
            "message": f"Falha inesperada ao validar a sessão: {exc}",
            "tested_at": tested_at,
            "current_url": None,
            "evidence_path": None,
        }


def ensure_logged_in(page, conta_mae: ContaMae, session: Session, evidence_dir: Path) -> str:
    auth_path: list[str] = []
    goto_openai_members(page)

    for _ in range(10):
        state = detect_auth_state(page)
        if state == "logged_in":
            return "session_reused" if not auth_path else "_then_".join(auth_path)
        if state == "captcha_required":
            capture(page, evidence_dir, "captcha_required")
            raise ManualReviewRequired("Captcha detectado no fluxo de login da OpenAI.")
        if state == "email_required":
            if not fill_visible(page, EMAIL_INPUT_SELECTORS, conta_mae.login):
                break
            auth_path.append("email")
            if not click_first_button(page, ["continue", "next", "proceed", "entrar", "login", "sign in"]):
                page.keyboard.press("Enter")
            page.wait_for_timeout(1200)
            continue
        if state == "password_required":
            password = decrypt_data(conta_mae.senha)
            if not password:
                raise ManualReviewRequired("Não foi possível descriptografar a senha da conta-mãe.")
            if not fill_visible(page, PASSWORD_INPUT_SELECTORS, password):
                break
            auth_path.append("password")
            if not click_first_button(page, ["continue", "next", "entrar", "login", "sign in"]):
                page.keyboard.press("Enter")
            page.wait_for_timeout(1500)
            continue
        if state == "otp_required":
            auth_path.append("otp")
            otp = fetch_openai_otp_via_imap(session, conta_mae)
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


def navigate_to_invite_surface(page) -> None:
    goto_openai_members(page)
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


def send_invite(page, job: ContaMaeInviteJob, evidence_dir: Path) -> str | None:
    navigate_to_invite_surface(page)
    if not first_visible_locator(page, INVITE_INPUT_SELECTORS):
        capture(page, evidence_dir, "invite_surface_not_found")
        write_html_snapshot(page, evidence_dir, "invite_surface_not_found")
        raise ManualReviewRequired("Não foi possível localizar a interface de convite da OpenAI.")

    if not fill_visible(page, INVITE_INPUT_SELECTORS, job.email_cliente):
        raise ManualReviewRequired("Campo de email de convite não encontrado.")
    page.wait_for_timeout(500)
    if not click_first_button(page, ["invite", "send invite", "add member", "add members", "send"]):
        page.keyboard.press("Enter")
    page.wait_for_timeout(2000)

    body_text = page.locator("body").inner_text(timeout=1500)
    lowered = body_text.lower()
    if any(pattern.search(lowered) for pattern in SUCCESS_TEXT_PATTERNS):
        capture(page, evidence_dir, "invite_sent")
        return extract_workspace_name(page)
    if "error" in lowered or "invalid" in lowered:
        capture(page, evidence_dir, "invite_error")
        write_html_snapshot(page, evidence_dir, "invite_error")
        raise InviteAutomationError("A OpenAI retornou erro ao enviar o convite.")
    capture(page, evidence_dir, "invite_post_submit")
    return extract_workspace_name(page)


def run_invite_automation(session: Session, job: ContaMaeInviteJob, conta_mae: ContaMae) -> dict:
    if host_runner_enabled():
        result = execute_host_runner_request(build_host_runner_invite_request(session, job, conta_mae))
        status = result.get("status")
        if status == "SENT":
            return {
                "auth_path_used": result.get("auth_path_used") or "session_reused",
                "workspace_name": result.get("workspace_name"),
                "evidence_path": result.get("evidence_path"),
            }
        if result.get("evidence_path"):
            job.evidence_path = result["evidence_path"]
        if status == "MANUAL_REVIEW":
            raise ManualReviewRequired(result.get("message") or "Runner host-side exigiu revisao manual.")
        if result.get("auth_step_failed") == "otp":
            raise OTPTimeoutError(result.get("message") or "Runner host-side nao conseguiu concluir o OTP.")
        raise InviteAutomationError(result.get("message") or "Runner host-side falhou ao enviar o convite.")

    if sync_playwright is None:
        raise ManualReviewRequired("Playwright não está instalado no ambiente da API.")

    evidence_dir = build_evidence_dir(job)
    session_path = Path(build_session_path(conta_mae))
    session_path.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        context_manager = launch_conta_mae_browser_context(playwright, session_path)
        context = context_manager.__enter__()
        try:
            context.set_default_timeout(settings.OPENAI_INVITE_PAGE_TIMEOUT_MS)
            page = context.pages[0] if context.pages else context.new_page()
            auth_path = ensure_logged_in(page, conta_mae, session, evidence_dir)
            workspace_name = send_invite(page, job, evidence_dir)
            return {
                "auth_path_used": auth_path,
                "workspace_name": workspace_name,
                "evidence_path": str(evidence_dir),
            }
        finally:
            context_manager.__exit__(None, None, None)


def notify_invite_job_sent(
    session: Session,
    job: ContaMaeInviteJob,
    *,
    workspace_name: str | None = None,
) -> None:
    pedido = session.get(Pedido, job.pedido_id) if job.pedido_id else None
    if not pedido:
        return
    usuario = session.get(Usuario, pedido.usuario_id) if pedido.usuario_id else None
    if not usuario or not usuario.telegram_id:
        return
    produto = session.get(Produto, pedido.produto_id) if pedido.produto_id else None
    produto_nome = produto.nome if produto else "seu produto"
    send_openai_invite_sent_message(
        telegram_id=usuario.telegram_id,
        email_cliente=job.email_cliente,
        produto_nome=produto_nome,
        workspace_name=workspace_name,
    )


def notify_invite_job_admin_failure(
    session: Session,
    job: ContaMaeInviteJob,
    conta_mae: ContaMae,
) -> None:
    pedido = session.get(Pedido, job.pedido_id) if job.pedido_id else None
    produto = session.get(Produto, pedido.produto_id) if pedido and pedido.produto_id else None
    send_openai_invite_failure_admin_alert(
        status=job.status.value if hasattr(job.status, "value") else str(job.status),
        conta_mae_login=conta_mae.login,
        email_cliente=job.email_cliente,
        job_id=str(job.id),
        pedido_id=str(job.pedido_id) if job.pedido_id else None,
        produto_nome=produto.nome if produto else None,
        motivo=job.last_error,
    )


def process_invite_job(job_id: uuid.UUID) -> dict:
    with Session(engine) as session:
        job = session.get(ContaMaeInviteJob, job_id)
        if not job:
            raise InviteAutomationError(f"Job {job_id} não encontrado.")
        if job.status == ContaMaeInviteJobStatus.SENT:
            return job_result_payload(job)

        conta_mae = session.get(ContaMae, job.conta_mae_id)
        if not conta_mae:
            job.status = ContaMaeInviteJobStatus.FAILED
            job.last_error = "Conta-mãe não encontrada para o job."
            session.add(job)
            session.commit()
            session.refresh(job)
            return job_result_payload(job)

        now = utcnow()
        job.status = ContaMaeInviteJobStatus.RUNNING
        job.locked_at = now
        job.started_at = now
        job.finished_at = None
        job.attempt_count += 1
        job.last_error = None
        session.add(job)
        session.commit()
        session.refresh(job)
        session.refresh(conta_mae)

        try:
            automation_result = run_invite_automation(session, job, conta_mae)
            refreshed_job = session.get(ContaMaeInviteJob, job_id)
            refreshed_conta = session.get(ContaMae, conta_mae.id)
            if not refreshed_job or not refreshed_conta:
                raise InviteAutomationError("Job ou conta-mãe indisponível após automação.")
            refreshed_job.status = ContaMaeInviteJobStatus.SENT
            refreshed_job.auth_path_used = automation_result["auth_path_used"]
            refreshed_job.auth_step_failed = None
            refreshed_job.last_error = None
            refreshed_job.evidence_path = (
                automation_result.get("evidence_path") or str(build_evidence_dir(refreshed_job))
            )
            refreshed_job.finished_at = utcnow()
            refreshed_job.locked_at = None
            refreshed_conta.ultimo_convite_sucesso_em = refreshed_job.finished_at
            refreshed_conta.ultimo_login_automatizado_em = refreshed_job.finished_at
            refreshed_conta.session_storage_path = build_session_path(refreshed_conta)
            refreshed_conta.ultimo_erro_automacao = None
            session.add(refreshed_job)
            session.add(refreshed_conta)
            session.commit()
            session.refresh(refreshed_job)
            try:
                notify_invite_job_sent(
                    session,
                    refreshed_job,
                    workspace_name=automation_result.get("workspace_name"),
                )
            except Exception as exc:
                print(f"AVISO: falha ao notificar cliente do convite {refreshed_job.id}: {exc}")
            return job_result_payload(refreshed_job)
        except OTPTimeoutError as exc:
            refreshed_job = session.get(ContaMaeInviteJob, job_id)
            refreshed_conta = session.get(ContaMae, conta_mae.id)
            refreshed_job.status = ContaMaeInviteJobStatus.FAILED
            refreshed_job.auth_step_failed = "otp"
            refreshed_job.last_error = str(exc)
            refreshed_job.evidence_path = str(build_evidence_dir(refreshed_job))
            refreshed_job.finished_at = utcnow()
            refreshed_job.locked_at = None
            refreshed_conta.ultimo_erro_automacao = refreshed_job.last_error
            session.add(refreshed_job)
            session.add(refreshed_conta)
            session.commit()
            session.refresh(refreshed_job)
            try:
                notify_invite_job_admin_failure(session, refreshed_job, refreshed_conta)
            except Exception as exc_notify:
                print(f"AVISO: falha ao alertar admin do convite {refreshed_job.id}: {exc_notify}")
            return job_result_payload(refreshed_job)
        except ManualReviewRequired as exc:
            refreshed_job = session.get(ContaMaeInviteJob, job_id)
            refreshed_conta = session.get(ContaMae, conta_mae.id)
            refreshed_job.status = ContaMaeInviteJobStatus.MANUAL_REVIEW
            refreshed_job.last_error = str(exc)
            refreshed_job.evidence_path = str(build_evidence_dir(refreshed_job))
            refreshed_job.finished_at = utcnow()
            refreshed_job.locked_at = None
            refreshed_conta.ultimo_erro_automacao = refreshed_job.last_error
            session.add(refreshed_job)
            session.add(refreshed_conta)
            session.commit()
            session.refresh(refreshed_job)
            try:
                notify_invite_job_admin_failure(session, refreshed_job, refreshed_conta)
            except Exception as exc_notify:
                print(f"AVISO: falha ao alertar admin do convite {refreshed_job.id}: {exc_notify}")
            return job_result_payload(refreshed_job)
        except (InviteAutomationError, PlaywrightTimeoutError) as exc:
            refreshed_job = session.get(ContaMaeInviteJob, job_id)
            refreshed_conta = session.get(ContaMae, conta_mae.id)
            refreshed_job.status = ContaMaeInviteJobStatus.FAILED
            refreshed_job.last_error = str(exc)
            refreshed_job.evidence_path = str(build_evidence_dir(refreshed_job))
            refreshed_job.finished_at = utcnow()
            refreshed_job.locked_at = None
            refreshed_conta.ultimo_erro_automacao = refreshed_job.last_error
            session.add(refreshed_job)
            session.add(refreshed_conta)
            session.commit()
            session.refresh(refreshed_job)
            try:
                notify_invite_job_admin_failure(session, refreshed_job, refreshed_conta)
            except Exception as exc_notify:
                print(f"AVISO: falha ao alertar admin do convite {refreshed_job.id}: {exc_notify}")
            return job_result_payload(refreshed_job)
