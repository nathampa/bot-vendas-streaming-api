import datetime
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks
from sqlmodel import Session, select

from app.core.config import settings
from app.db.database import engine
from app.models.conta_mae_models import (
    ContaMae,
    ContaMaeConvite,
    ContaMaeInviteJobStatus,
    ContaMaeMemberRemovalJob,
    ContaMaeMemberRemovalJobStatus,
)
from app.models.produto_models import Produto
from app.services.conta_mae_invite_service import (
    InviteAutomationError,
    ManualReviewRequired,
    PlaywrightTimeoutError,
    build_imap_credentials_payload,
    build_session_path,
    capture,
    challenge_retryable,
    click_first_button,
    compute_retry_cooldown_seconds,
    decrypt_data,
    execute_host_runner_request,
    first_visible_locator,
    goto_openai_members,
    host_runner_enabled,
    launch_conta_mae_browser_context,
    produto_supports_openai_invite_automation,
    sync_playwright,
    utcnow,
    wait_for_spinner_to_settle,
    write_html_snapshot,
)
from app.services.disponibilidade_service import sincronizar_status_produto_por_disponibilidade
from app.services.notification_service import send_openai_member_removal_failure_admin_alert


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


def removal_result_payload(job: ContaMaeMemberRemovalJob) -> dict:
    return {
        "id": str(job.id),
        "status": job.status.value if hasattr(job.status, "value") else str(job.status),
        "conta_mae_id": str(job.conta_mae_id),
        "email_cliente": job.email_cliente,
        "attempt_count": job.attempt_count,
        "last_error": job.last_error,
        "evidence_path": job.evidence_path,
        "next_retry_at": job.next_retry_at.isoformat() if job.next_retry_at else None,
    }


def build_removal_evidence_dir(job: ContaMaeMemberRemovalJob) -> Path:
    path = Path(settings.OPENAI_INVITE_EVIDENCE_ROOT) / "member-removal" / str(job.id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_member_removal_job_for_convite(
    session: Session,
    convite: ContaMaeConvite,
) -> ContaMaeMemberRemovalJob:
    existing = session.exec(
        select(ContaMaeMemberRemovalJob).where(ContaMaeMemberRemovalJob.convite_id == convite.id)
    ).first()
    if existing:
        return existing

    job = ContaMaeMemberRemovalJob(
        convite_id=convite.id,
        conta_mae_id=convite.conta_mae_id,
        pedido_id=convite.pedido_id,
        email_cliente=convite.email_cliente.strip(),
        status=ContaMaeMemberRemovalJobStatus.PENDING,
    )
    session.add(job)
    session.flush()
    return job


def process_member_removal_job_task(job_id: str) -> None:
    try:
        processed_job = process_member_removal_job(uuid.UUID(job_id))
        print(
            "BACKGROUND TASK: Job de remoção de membro processado. "
            f"id={processed_job['id']} status={processed_job['status']}"
        )
    except Exception as exc:
        print(f"ERRO CRÍTICO na tarefa local de remoção de membro ({job_id}): {exc}")


def enqueue_member_removal_job(
    job_id: uuid.UUID,
    *,
    background_tasks: Optional[BackgroundTasks] = None,
    countdown_seconds: int | None = None,
) -> None:
    if not settings.OPENAI_INVITE_AUTOMATION_ENABLED:
        return
    if settings.CELERY_BROKER_URL:
        from app.worker.celery_app import celery_app

        kwargs = {}
        if countdown_seconds and countdown_seconds > 0:
            kwargs["countdown"] = countdown_seconds
        celery_app.send_task("process_conta_mae_member_removal_job", args=[str(job_id)], **kwargs)
        return
    if background_tasks is not None:
        if countdown_seconds and countdown_seconds > 0:
            def delayed_task():
                time.sleep(countdown_seconds)
                process_member_removal_job_task(str(job_id))
            background_tasks.add_task(delayed_task)
        else:
            background_tasks.add_task(process_member_removal_job_task, str(job_id))
        return

    def thread_target():
        if countdown_seconds and countdown_seconds > 0:
            time.sleep(countdown_seconds)
        process_member_removal_job_task(str(job_id))

    threading.Thread(
        target=thread_target,
        daemon=True,
        name=f"openai-member-removal-{job_id}",
    ).start()


def build_host_runner_removal_request(
    session: Session,
    job: ContaMaeMemberRemovalJob,
    conta_mae: ContaMae,
) -> dict:
    password = decrypt_data(conta_mae.senha)
    if not password:
        raise ManualReviewRequired("Não foi possível descriptografar a senha da conta-mãe.")

    return {
        "action": "remove_member",
        "job_id": str(job.id),
        "session_path": build_session_path(conta_mae),
        "evidence_dir": str(build_removal_evidence_dir(job)),
        "members_url": settings.OPENAI_INVITE_MEMBERS_URL,
        "login_email": conta_mae.login,
        "login_password": password,
        "member_email": job.email_cliente,
        "imap": build_imap_credentials_payload(session, conta_mae),
    }


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


def navigate_to_members_surface(page) -> None:
    goto_openai_members(page)
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


def remove_member_from_workspace(page, email_cliente: str, evidence_dir: Path) -> str:
    navigate_to_members_surface(page)
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


def run_member_removal_automation(
    session: Session,
    job: ContaMaeMemberRemovalJob,
    conta_mae: ContaMae,
) -> dict:
    if host_runner_enabled():
        result = execute_host_runner_request(build_host_runner_removal_request(session, job, conta_mae))
        status = result.get("status")
        if status in {"REMOVED", "NOT_FOUND"}:
            return {
                "status": status,
                "auth_path_used": result.get("auth_path_used") or "session_reused",
                "evidence_path": result.get("evidence_path"),
            }
        if result.get("evidence_path"):
            job.evidence_path = result["evidence_path"]
        if status == "MANUAL_REVIEW":
            raise ManualReviewRequired(result.get("message") or "Runner host-side exigiu revisão manual.")
        raise InviteAutomationError(result.get("message") or "Runner host-side falhou ao remover o membro.")

    if sync_playwright is None:
        raise ManualReviewRequired("Playwright não está instalado no ambiente da API.")

    evidence_dir = build_removal_evidence_dir(job)
    session_path = Path(build_session_path(conta_mae))
    session_path.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        context_manager = launch_conta_mae_browser_context(playwright, session_path)
        context = context_manager.__enter__()
        try:
            context.set_default_timeout(settings.OPENAI_INVITE_PAGE_TIMEOUT_MS)
            page = context.pages[0] if context.pages else context.new_page()
            from app.services.conta_mae_invite_service import ensure_logged_in

            auth_path = ensure_logged_in(page, conta_mae, session, evidence_dir)
            status = remove_member_from_workspace(page, job.email_cliente, evidence_dir)
            return {
                "status": status,
                "auth_path_used": auth_path,
                "evidence_path": str(evidence_dir),
            }
        finally:
            context_manager.__exit__(None, None, None)


def notify_member_removal_admin_failure(
    session: Session,
    job: ContaMaeMemberRemovalJob,
    conta_mae: ContaMae,
) -> None:
    produto = session.get(Produto, conta_mae.produto_id) if conta_mae.produto_id else None
    send_openai_member_removal_failure_admin_alert(
        status=job.status.value if hasattr(job.status, "value") else str(job.status),
        conta_mae_login=conta_mae.login,
        email_cliente=job.email_cliente,
        job_id=str(job.id),
        pedido_id=str(job.pedido_id) if job.pedido_id else None,
        produto_nome=produto.nome if produto else None,
        motivo=job.last_error,
        attempt_count=job.attempt_count,
        next_retry_at=job.next_retry_at.isoformat() if job.next_retry_at else None,
    )


def schedule_retry_or_manual_review(
    session: Session,
    job: ContaMaeMemberRemovalJob,
    conta_mae: ContaMae,
    *,
    error_message: str,
) -> dict:
    now = utcnow()
    deadline = job.created_at + datetime.timedelta(seconds=settings.OPENAI_INVITE_RETRY_WINDOW_SECONDS)
    remaining_seconds = int((deadline - now).total_seconds())

    if remaining_seconds <= 0:
        job.status = ContaMaeMemberRemovalJobStatus.MANUAL_REVIEW
        job.last_error = error_message
        job.evidence_path = job.evidence_path or str(build_removal_evidence_dir(job))
        job.finished_at = now
        job.locked_at = None
        job.next_retry_at = None
        conta_mae.ultimo_erro_automacao = job.last_error
        session.add(job)
        session.add(conta_mae)
        session.commit()
        session.refresh(job)
        try:
            notify_member_removal_admin_failure(session, job, conta_mae)
        except Exception as exc_notify:
            print(f"AVISO: falha ao alertar admin da remoção {job.id}: {exc_notify}")
        return removal_result_payload(job)

    cooldown_seconds = min(compute_retry_cooldown_seconds(job.attempt_count), remaining_seconds)
    next_retry = now + datetime.timedelta(seconds=cooldown_seconds)
    job.status = ContaMaeMemberRemovalJobStatus.RETRY_WAIT
    job.last_error = error_message
    job.evidence_path = job.evidence_path or str(build_removal_evidence_dir(job))
    job.finished_at = None
    job.locked_at = None
    job.next_retry_at = next_retry
    conta_mae.ultimo_erro_automacao = job.last_error
    session.add(job)
    session.add(conta_mae)
    session.commit()
    session.refresh(job)
    try:
        notify_member_removal_admin_failure(session, job, conta_mae)
    except Exception as exc_notify:
        print(f"AVISO: falha ao alertar admin da remoção {job.id}: {exc_notify}")
    try:
        enqueue_member_removal_job(job.id, countdown_seconds=cooldown_seconds)
    except Exception as exc_enqueue:
        print(f"AVISO: falha ao agendar retry da remoção {job.id}: {exc_enqueue}")
    return removal_result_payload(job)


def mark_member_removed(
    session: Session,
    job: ContaMaeMemberRemovalJob,
    convite: ContaMaeConvite,
    conta_mae: ContaMae,
    status: ContaMaeMemberRemovalJobStatus,
    automation_result: dict,
) -> None:
    now = utcnow()
    job.status = status
    job.auth_path_used = automation_result.get("auth_path_used")
    job.last_error = None
    job.evidence_path = automation_result.get("evidence_path") or str(build_removal_evidence_dir(job))
    job.finished_at = now
    job.locked_at = None
    job.next_retry_at = None
    job.cancelled_at = None
    convite.removido_workspace_em = convite.removido_workspace_em or now
    conta_mae.slots_ocupados = max((conta_mae.slots_ocupados or 0) - 1, 0)
    if conta_mae.data_expiracao is None or conta_mae.data_expiracao >= datetime.date.today():
        conta_mae.is_ativo = conta_mae.slots_ocupados < conta_mae.max_slots
    conta_mae.ultimo_erro_automacao = None
    session.add(job)
    session.add(convite)
    session.add(conta_mae)
    produto = session.get(Produto, conta_mae.produto_id)
    if produto:
        sincronizar_status_produto_por_disponibilidade(session, produto)


def process_member_removal_job(job_id: uuid.UUID) -> dict:
    with Session(engine) as session:
        job = session.get(ContaMaeMemberRemovalJob, job_id)
        if not job:
            raise InviteAutomationError(f"Job {job_id} não encontrado.")
        if job.status in (
            ContaMaeMemberRemovalJobStatus.REMOVED,
            ContaMaeMemberRemovalJobStatus.NOT_FOUND,
            ContaMaeMemberRemovalJobStatus.CANCELLED,
        ):
            return removal_result_payload(job)
        if (
            job.status == ContaMaeMemberRemovalJobStatus.RETRY_WAIT
            and job.next_retry_at
            and job.next_retry_at > utcnow()
        ):
            return removal_result_payload(job)

        conta_mae = session.get(ContaMae, job.conta_mae_id)
        convite = session.get(ContaMaeConvite, job.convite_id)
        if not conta_mae or not convite:
            job.status = ContaMaeMemberRemovalJobStatus.FAILED
            job.last_error = "Conta-mãe ou convite não encontrado para o job."
            session.add(job)
            session.commit()
            session.refresh(job)
            return removal_result_payload(job)

        produto = session.get(Produto, conta_mae.produto_id)
        if not produto_supports_openai_invite_automation(produto):
            job.status = ContaMaeMemberRemovalJobStatus.MANUAL_REVIEW
            job.last_error = "Automação OpenAI desabilitada para o produto desta conta-mãe."
            job.finished_at = utcnow()
            job.locked_at = None
            job.next_retry_at = None
            job.evidence_path = job.evidence_path or str(build_removal_evidence_dir(job))
            conta_mae.ultimo_erro_automacao = job.last_error
            session.add(job)
            session.add(conta_mae)
            session.commit()
            session.refresh(job)
            return removal_result_payload(job)

        now = utcnow()
        job.status = ContaMaeMemberRemovalJobStatus.RUNNING
        job.locked_at = now
        job.started_at = now
        job.finished_at = None
        job.next_retry_at = None
        job.attempt_count += 1
        job.last_error = None
        session.add(job)
        session.commit()
        session.refresh(job)
        session.refresh(conta_mae)
        session.refresh(convite)

        try:
            automation_result = run_member_removal_automation(session, job, conta_mae)
            refreshed_job = session.get(ContaMaeMemberRemovalJob, job_id)
            refreshed_conta = session.get(ContaMae, conta_mae.id)
            refreshed_convite = session.get(ContaMaeConvite, convite.id)
            if not refreshed_job or not refreshed_conta or not refreshed_convite:
                raise InviteAutomationError("Job, conta-mãe ou convite indisponível após automação.")
            status = (
                ContaMaeMemberRemovalJobStatus.NOT_FOUND
                if automation_result.get("status") == "NOT_FOUND"
                else ContaMaeMemberRemovalJobStatus.REMOVED
            )
            mark_member_removed(
                session,
                refreshed_job,
                refreshed_convite,
                refreshed_conta,
                status,
                automation_result,
            )
            session.commit()
            session.refresh(refreshed_job)
            return removal_result_payload(refreshed_job)
        except (ManualReviewRequired, InviteAutomationError, PlaywrightTimeoutError) as exc:
            refreshed_job = session.get(ContaMaeMemberRemovalJob, job_id)
            refreshed_conta = session.get(ContaMae, conta_mae.id)
            if not refreshed_job or not refreshed_conta:
                raise InviteAutomationError("Job ou conta-mãe indisponível ao tratar falha.")
            if challenge_retryable(str(exc)):
                return schedule_retry_or_manual_review(
                    session,
                    refreshed_job,
                    refreshed_conta,
                    error_message=str(exc),
                )
            refreshed_job.status = (
                ContaMaeMemberRemovalJobStatus.MANUAL_REVIEW
                if isinstance(exc, ManualReviewRequired)
                else ContaMaeMemberRemovalJobStatus.FAILED
            )
            refreshed_job.last_error = str(exc)
            refreshed_job.evidence_path = refreshed_job.evidence_path or str(build_removal_evidence_dir(refreshed_job))
            refreshed_job.finished_at = utcnow()
            refreshed_job.locked_at = None
            refreshed_job.next_retry_at = None
            refreshed_conta.ultimo_erro_automacao = refreshed_job.last_error
            session.add(refreshed_job)
            session.add(refreshed_conta)
            session.commit()
            session.refresh(refreshed_job)
            try:
                notify_member_removal_admin_failure(session, refreshed_job, refreshed_conta)
            except Exception as exc_notify:
                print(f"AVISO: falha ao alertar admin da remoção {refreshed_job.id}: {exc_notify}")
            return removal_result_payload(refreshed_job)


def convite_tem_convite_openai_enviado(convite: ContaMaeConvite) -> bool:
    return bool(
        convite.invite_job
        and convite.invite_job.status == ContaMaeInviteJobStatus.SENT
    )
