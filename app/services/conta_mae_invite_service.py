import datetime
import email
import re
import threading
import time
import uuid
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
from app.services.email_monitor_service import (
    build_connection,
    decode_mime_header,
    extract_message_bodies,
    normalize_folder_list,
    parse_sent_datetime,
    stringify_imap_exception,
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


def build_session_path(conta_mae: ContaMae) -> str:
    if conta_mae.session_storage_path:
        return conta_mae.session_storage_path
    return str(session_root() / f"conta_mae_{conta_mae.id}")


def build_evidence_dir(job: ContaMaeInviteJob) -> Path:
    path = evidence_root() / str(job.id)
    path.mkdir(parents=True, exist_ok=True)
    return path


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
            f"id={processed_job.id} status={processed_job.status}"
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
    if first_visible_locator(page, OTP_INPUT_SELECTORS):
        return "otp_required"
    if first_visible_locator(page, PASSWORD_INPUT_SELECTORS):
        return "password_required"
    if first_visible_locator(page, EMAIL_INPUT_SELECTORS):
        return "email_required"

    body_text = page.locator("body").inner_text(timeout=1000).lower()
    if "captcha" in body_text or "verify you are human" in body_text:
        return "captcha_required"
    if "members" in body_text or "invite" in body_text or "workspace" in body_text:
        return "logged_in"
    if any(fragment in page.url.lower() for fragment in ("login", "auth", "signin")):
        return "unknown_auth_state"
    return "logged_in"


def ensure_logged_in(page, conta_mae: ContaMae, session: Session, evidence_dir: Path) -> str:
    auth_path: list[str] = []
    page.goto(settings.OPENAI_INVITE_MEMBERS_URL, wait_until="networkidle")

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
    page.goto(settings.OPENAI_INVITE_MEMBERS_URL, wait_until="networkidle")
    if first_visible_locator(page, INVITE_INPUT_SELECTORS):
        return
    click_first_button(page, ["members", "manage members", "team", "workspace"])
    page.wait_for_timeout(1000)
    if first_visible_locator(page, INVITE_INPUT_SELECTORS):
        return
    click_first_button(page, ["invite", "invite members", "add member", "add members"])
    page.wait_for_timeout(1000)


def send_invite(page, job: ContaMaeInviteJob, evidence_dir: Path) -> None:
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
        return
    if "error" in lowered or "invalid" in lowered:
        capture(page, evidence_dir, "invite_error")
        write_html_snapshot(page, evidence_dir, "invite_error")
        raise InviteAutomationError("A OpenAI retornou erro ao enviar o convite.")
    capture(page, evidence_dir, "invite_post_submit")


def run_invite_automation(session: Session, job: ContaMaeInviteJob, conta_mae: ContaMae) -> str:
    if sync_playwright is None:
        raise ManualReviewRequired("Playwright não está instalado no ambiente da API.")

    evidence_dir = build_evidence_dir(job)
    session_path = Path(build_session_path(conta_mae))
    session_path.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(session_path),
            headless=settings.OPENAI_INVITE_HEADLESS,
            viewport={"width": 1440, "height": 960},
        )
        try:
            context.set_default_timeout(settings.OPENAI_INVITE_PAGE_TIMEOUT_MS)
            page = context.pages[0] if context.pages else context.new_page()
            auth_path = ensure_logged_in(page, conta_mae, session, evidence_dir)
            send_invite(page, job, evidence_dir)
            return auth_path
        finally:
            context.close()


def process_invite_job(job_id: uuid.UUID) -> ContaMaeInviteJob:
    with Session(engine) as session:
        job = session.get(ContaMaeInviteJob, job_id)
        if not job:
            raise InviteAutomationError(f"Job {job_id} não encontrado.")
        if job.status == ContaMaeInviteJobStatus.SENT:
            return job

        conta_mae = session.get(ContaMae, job.conta_mae_id)
        if not conta_mae:
            job.status = ContaMaeInviteJobStatus.FAILED
            job.last_error = "Conta-mãe não encontrada para o job."
            session.add(job)
            session.commit()
            return job

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
            auth_path = run_invite_automation(session, job, conta_mae)
            refreshed_job = session.get(ContaMaeInviteJob, job_id)
            refreshed_conta = session.get(ContaMae, conta_mae.id)
            if not refreshed_job or not refreshed_conta:
                raise InviteAutomationError("Job ou conta-mãe indisponível após automação.")
            refreshed_job.status = ContaMaeInviteJobStatus.SENT
            refreshed_job.auth_path_used = auth_path
            refreshed_job.auth_step_failed = None
            refreshed_job.last_error = None
            refreshed_job.evidence_path = str(build_evidence_dir(refreshed_job))
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
            return refreshed_job
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
            return refreshed_job
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
            return refreshed_job
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
            return refreshed_job
