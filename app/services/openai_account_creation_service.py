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
from app.models.openai_account_creation_models import (
    OpenAIAccountCreationJob,
    OpenAIAccountCreationJobStatus,
    OpenAIAccountCreationRequest,
    OpenAIAccountCreationRequestStatus,
)
from app.services.conta_mae_invite_service import challenge_retryable, execute_host_runner_request
from app.services.security import decrypt_data, encrypt_data


class OpenAIAccountCreationError(Exception):
    pass


class OpenAIAccountCreationManualReviewRequired(OpenAIAccountCreationError):
    pass


EMAIL_REGEX = re.compile(r"^[A-Za-z0-9_.+\-]+@[A-Za-z0-9\-]+\.[A-Za-z0-9.\-]+$")


def utcnow() -> datetime.datetime:
    return datetime.datetime.utcnow()


def slugify(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("_") or "default"


def account_creation_session_root() -> Path:
    root = Path(settings.OPENAI_ACCOUNT_CREATION_SESSION_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return root


def account_creation_evidence_root() -> Path:
    root = Path(settings.OPENAI_ACCOUNT_CREATION_EVIDENCE_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return root


def build_request_session_path(request: OpenAIAccountCreationRequest) -> str:
    if request.session_storage_path:
        return request.session_storage_path
    email_part = slugify(request.email.split("@", 1)[0].lower())
    return str(account_creation_session_root() / f"account_{email_part}_{str(request.id)[:8]}")


def build_request_evidence_dir(job: OpenAIAccountCreationJob) -> Path:
    path = account_creation_evidence_root() / str(job.id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def account_creation_retry_cooldowns_seconds() -> list[int]:
    values: list[int] = []
    for piece in settings.OPENAI_ACCOUNT_CREATION_RETRY_COOLDOWNS_SECONDS.split(","):
        piece = piece.strip()
        if not piece:
            continue
        try:
            parsed = int(piece)
        except ValueError:
            continue
        if parsed > 0:
            values.append(parsed)
    return values or [300, 600, 900, 1200, 1800]


def compute_account_creation_retry_cooldown_seconds(attempt_count: int) -> int:
    cooldowns = account_creation_retry_cooldowns_seconds()
    index = max(0, attempt_count - 1)
    if index >= len(cooldowns):
        return cooldowns[-1]
    return cooldowns[index]


def account_creation_retry_deadline(job: OpenAIAccountCreationJob) -> datetime.datetime:
    return job.created_at + datetime.timedelta(seconds=settings.OPENAI_ACCOUNT_CREATION_RETRY_WINDOW_SECONDS)


def validate_batch_item(email: str, senha: str) -> bool:
    email_clean = email.strip().lower()
    senha_clean = senha.strip()
    return bool(email_clean and senha_clean and EMAIL_REGEX.match(email_clean))


def request_to_schema_payload(request: OpenAIAccountCreationRequest) -> dict:
    return {
        "id": request.id,
        "email": request.email,
        "session_storage_path": request.session_storage_path,
        "workspace_name": request.workspace_name,
        "status_atual": request.status_atual.value if hasattr(request.status_atual, "value") else str(request.status_atual),
        "ultimo_erro": request.ultimo_erro,
        "criado_em": request.criado_em,
        "atualizado_em": request.atualizado_em,
    }


def job_to_schema_payload(job: OpenAIAccountCreationJob) -> dict:
    request = getattr(job, "request", None)
    return {
        "id": job.id,
        "request_id": job.request_id,
        "email": request.email if request else None,
        "status": job.status.value if hasattr(job.status, "value") else str(job.status),
        "attempt_count": job.attempt_count,
        "auth_path_used": job.auth_path_used,
        "last_error": job.last_error,
        "evidence_path": job.evidence_path,
        "locked_at": job.locked_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "next_retry_at": job.next_retry_at,
        "cancelled_at": job.cancelled_at,
        "otp_submitted_at": job.otp_submitted_at,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "request_status_atual": request.status_atual.value if request and hasattr(request.status_atual, "value") else (str(request.status_atual) if request else None),
        "session_storage_path": request.session_storage_path if request else None,
        "workspace_name": request.workspace_name if request else None,
    }


def create_account_creation_request_and_job(
    session: Session,
    *,
    email: str,
    senha: str,
) -> tuple[OpenAIAccountCreationRequest, OpenAIAccountCreationJob]:
    request = OpenAIAccountCreationRequest(
        email=email.strip().lower(),
        senha_encrypted=encrypt_data(senha.strip()),
        status_atual=OpenAIAccountCreationRequestStatus.PENDING,
    )
    session.add(request)
    session.flush()
    request.session_storage_path = build_request_session_path(request)
    session.add(request)
    session.flush()

    job = OpenAIAccountCreationJob(
        request_id=request.id,
        status=OpenAIAccountCreationJobStatus.PENDING,
    )
    session.add(job)
    session.flush()
    return request, job


def process_openai_account_creation_job_task(job_id: str) -> None:
    try:
        processed_job = process_openai_account_creation_job(uuid.UUID(job_id))
        print(
            "BACKGROUND TASK: Job de criacao de conta OpenAI processado. "
            f"id={processed_job['id']} status={processed_job['status']}"
        )
    except Exception as exc:
        print(f"ERRO CRITICO na tarefa local de criacao de conta OpenAI ({job_id}): {exc}")


def enqueue_openai_account_creation_job(
    job_id: uuid.UUID,
    *,
    background_tasks: Optional[BackgroundTasks] = None,
    countdown_seconds: int | None = None,
) -> None:
    if not settings.OPENAI_ACCOUNT_CREATION_ENABLED:
        return
    if settings.CELERY_BROKER_URL:
        from app.worker.celery_app import celery_app

        kwargs = {}
        if countdown_seconds and countdown_seconds > 0:
            kwargs["countdown"] = countdown_seconds
        celery_app.send_task("process_openai_account_creation_job", args=[str(job_id)], **kwargs)
        return
    if background_tasks is not None:
        if countdown_seconds and countdown_seconds > 0:
            def delayed_task():
                time.sleep(countdown_seconds)
                process_openai_account_creation_job_task(str(job_id))
            background_tasks.add_task(delayed_task)
        else:
            background_tasks.add_task(process_openai_account_creation_job_task, str(job_id))
        return

    def thread_target():
        if countdown_seconds and countdown_seconds > 0:
            time.sleep(countdown_seconds)
        process_openai_account_creation_job_task(str(job_id))

    threading.Thread(
        target=thread_target,
        daemon=True,
        name=f"openai-account-create-{job_id}",
    ).start()


def build_host_runner_account_creation_request(
    job: OpenAIAccountCreationJob,
    request: OpenAIAccountCreationRequest,
) -> dict:
    password = decrypt_data(request.senha_encrypted)
    if not password:
        raise OpenAIAccountCreationManualReviewRequired("Nao foi possivel descriptografar a senha da conta alvo.")

    otp_code = decrypt_data(job.otp_code_encrypted) if job.otp_code_encrypted else None
    return {
        "action": "create_account",
        "job_id": str(job.id),
        "session_path": build_request_session_path(request),
        "evidence_dir": str(build_request_evidence_dir(job)),
        "launch_url": settings.OPENAI_ACCOUNT_CREATION_SIGNUP_URL,
        "signup_email": request.email,
        "signup_password": password,
        "otp_code": otp_code,
    }


def run_openai_account_creation_automation(
    job: OpenAIAccountCreationJob,
    request: OpenAIAccountCreationRequest,
) -> dict:
    result = execute_host_runner_request(build_host_runner_account_creation_request(job, request))
    status = result.get("status")
    if status in {"CREATED", "WAITING_OTP_INPUT", "MANUAL_REVIEW", "FAILED"}:
        return result
    raise OpenAIAccountCreationError(result.get("message") or "Runner host-side retornou um estado invalido na criacao de conta.")


def retry_openai_account_creation_job(
    session: Session,
    job: OpenAIAccountCreationJob,
) -> OpenAIAccountCreationJob:
    if job.status == OpenAIAccountCreationJobStatus.CREATED:
        raise OpenAIAccountCreationManualReviewRequired("O job ja foi concluido com sucesso.")
    if job.status == OpenAIAccountCreationJobStatus.CANCELLED:
        raise OpenAIAccountCreationManualReviewRequired("O job foi cancelado e nao pode ser reenfileirado.")
    job.status = OpenAIAccountCreationJobStatus.PENDING
    job.last_error = None
    job.locked_at = None
    job.started_at = None
    job.finished_at = None
    job.next_retry_at = None
    session.add(job)

    request = session.get(OpenAIAccountCreationRequest, job.request_id)
    if request:
        request.status_atual = OpenAIAccountCreationRequestStatus.PENDING
        request.ultimo_erro = None
        session.add(request)
    session.flush()
    return job


def cancel_openai_account_creation_job(
    session: Session,
    job: OpenAIAccountCreationJob,
) -> OpenAIAccountCreationJob:
    if job.status == OpenAIAccountCreationJobStatus.CREATED:
        raise OpenAIAccountCreationManualReviewRequired("Nao e possivel cancelar um job ja criado com sucesso.")
    now = utcnow()
    job.status = OpenAIAccountCreationJobStatus.CANCELLED
    job.cancelled_at = now
    job.finished_at = now
    job.locked_at = None
    job.next_retry_at = None
    session.add(job)

    request = session.get(OpenAIAccountCreationRequest, job.request_id)
    if request:
        request.status_atual = OpenAIAccountCreationRequestStatus.CANCELLED
        request.ultimo_erro = "Cancelado manualmente pelo admin."
        session.add(request)
    session.flush()
    return job


def submit_openai_account_creation_otp(
    session: Session,
    job: OpenAIAccountCreationJob,
    otp_code: str,
) -> OpenAIAccountCreationJob:
    otp_digits = re.sub(r"\D+", "", otp_code or "")
    if len(otp_digits) != 6:
        raise OpenAIAccountCreationManualReviewRequired("O codigo OTP deve conter exatamente 6 digitos.")
    if job.status != OpenAIAccountCreationJobStatus.WAITING_OTP_INPUT:
        raise OpenAIAccountCreationManualReviewRequired("Este job nao esta aguardando OTP manual.")
    job.otp_code_encrypted = encrypt_data(otp_digits)
    job.otp_submitted_at = utcnow()
    job.status = OpenAIAccountCreationJobStatus.PENDING
    job.last_error = None
    job.locked_at = None
    job.finished_at = None
    job.next_retry_at = None
    session.add(job)

    request = session.get(OpenAIAccountCreationRequest, job.request_id)
    if request:
        request.status_atual = OpenAIAccountCreationRequestStatus.PENDING
        request.ultimo_erro = None
        session.add(request)
    session.flush()
    return job


def schedule_openai_account_creation_retry_or_manual_review(
    session: Session,
    job: OpenAIAccountCreationJob,
    request: OpenAIAccountCreationRequest,
    *,
    error_message: str,
) -> dict:
    now = utcnow()
    deadline = account_creation_retry_deadline(job)
    remaining_seconds = int((deadline - now).total_seconds())

    if remaining_seconds <= 0:
        job.status = OpenAIAccountCreationJobStatus.MANUAL_REVIEW
        job.last_error = error_message
        job.finished_at = now
        job.locked_at = None
        job.next_retry_at = None
        session.add(job)
        request.status_atual = OpenAIAccountCreationRequestStatus.MANUAL_REVIEW
        request.ultimo_erro = error_message
        session.add(request)
        session.commit()
        session.refresh(job)
        session.refresh(request)
        return job_to_schema_payload(job)

    cooldown_seconds = min(compute_account_creation_retry_cooldown_seconds(job.attempt_count), remaining_seconds)
    next_retry = now + datetime.timedelta(seconds=cooldown_seconds)
    job.status = OpenAIAccountCreationJobStatus.RETRY_WAIT
    job.last_error = error_message
    job.locked_at = None
    job.finished_at = None
    job.next_retry_at = next_retry
    session.add(job)
    request.status_atual = OpenAIAccountCreationRequestStatus.RETRY_WAIT
    request.ultimo_erro = error_message
    session.add(request)
    session.commit()
    session.refresh(job)
    session.refresh(request)
    enqueue_openai_account_creation_job(job.id, countdown_seconds=cooldown_seconds)
    return job_to_schema_payload(job)


def process_openai_account_creation_job(job_id: uuid.UUID) -> dict:
    with Session(engine) as session:
        job = session.get(OpenAIAccountCreationJob, job_id)
        if not job:
            raise OpenAIAccountCreationError(f"Job {job_id} nao encontrado.")
        if job.status in {OpenAIAccountCreationJobStatus.CREATED, OpenAIAccountCreationJobStatus.CANCELLED}:
            return job_to_schema_payload(job)
        if job.status == OpenAIAccountCreationJobStatus.RETRY_WAIT and job.next_retry_at and job.next_retry_at > utcnow():
            return job_to_schema_payload(job)

        request = session.get(OpenAIAccountCreationRequest, job.request_id)
        if not request:
            job.status = OpenAIAccountCreationJobStatus.FAILED
            job.last_error = "Requisicao de criacao de conta nao encontrada."
            session.add(job)
            session.commit()
            session.refresh(job)
            return job_to_schema_payload(job)

        now = utcnow()
        job.status = OpenAIAccountCreationJobStatus.RUNNING
        job.locked_at = now
        job.started_at = now
        job.finished_at = None
        job.next_retry_at = None
        job.attempt_count += 1
        job.last_error = None
        session.add(job)
        request.status_atual = OpenAIAccountCreationRequestStatus.RUNNING
        request.ultimo_erro = None
        request.session_storage_path = build_request_session_path(request)
        session.add(request)
        session.commit()
        session.refresh(job)
        session.refresh(request)

        try:
            result = run_openai_account_creation_automation(job, request)
            refreshed_job = session.get(OpenAIAccountCreationJob, job_id)
            refreshed_request = session.get(OpenAIAccountCreationRequest, request.id)
            if not refreshed_job or not refreshed_request:
                raise OpenAIAccountCreationError("Job ou requisicao indisponivel apos automacao.")

            result_status = (result.get("status") or "").upper()
            result_message = result.get("message")

            if result_status == "WAITING_OTP_INPUT":
                refreshed_job.status = OpenAIAccountCreationJobStatus.WAITING_OTP_INPUT
                refreshed_job.last_error = result_message
                refreshed_job.evidence_path = result.get("evidence_path") or str(build_request_evidence_dir(refreshed_job))
                refreshed_job.auth_path_used = result.get("auth_path_used")
                refreshed_job.locked_at = None
                refreshed_job.finished_at = utcnow()
                session.add(refreshed_job)
                refreshed_request.status_atual = OpenAIAccountCreationRequestStatus.WAITING_OTP_INPUT
                refreshed_request.ultimo_erro = result_message
                session.add(refreshed_request)
                session.commit()
                session.refresh(refreshed_job)
                return job_to_schema_payload(refreshed_job)

            if result_status == "CREATED":
                refreshed_job.status = OpenAIAccountCreationJobStatus.CREATED
                refreshed_job.auth_path_used = result.get("auth_path_used")
                refreshed_job.last_error = None
                refreshed_job.evidence_path = result.get("evidence_path") or str(build_request_evidence_dir(refreshed_job))
                refreshed_job.locked_at = None
                refreshed_job.finished_at = utcnow()
                refreshed_job.otp_code_encrypted = None
                refreshed_job.next_retry_at = None
                session.add(refreshed_job)
                refreshed_request.status_atual = OpenAIAccountCreationRequestStatus.CREATED
                refreshed_request.ultimo_erro = None
                refreshed_request.workspace_name = result.get("workspace_name")
                refreshed_request.session_storage_path = build_request_session_path(refreshed_request)
                session.add(refreshed_request)
                session.commit()
                session.refresh(refreshed_job)
                return job_to_schema_payload(refreshed_job)

            if challenge_retryable(result_message):
                return schedule_openai_account_creation_retry_or_manual_review(
                    session,
                    refreshed_job,
                    refreshed_request,
                    error_message=result_message or "Captcha detectado na criacao de conta OpenAI.",
                )

            target_status = OpenAIAccountCreationJobStatus.MANUAL_REVIEW if result_status == "MANUAL_REVIEW" else OpenAIAccountCreationJobStatus.FAILED
            refreshed_job.status = target_status
            refreshed_job.last_error = result_message
            refreshed_job.evidence_path = result.get("evidence_path") or str(build_request_evidence_dir(refreshed_job))
            refreshed_job.locked_at = None
            refreshed_job.finished_at = utcnow()
            refreshed_job.next_retry_at = None
            session.add(refreshed_job)
            refreshed_request.status_atual = OpenAIAccountCreationRequestStatus(target_status.value)
            refreshed_request.ultimo_erro = result_message
            session.add(refreshed_request)
            session.commit()
            session.refresh(refreshed_job)
            return job_to_schema_payload(refreshed_job)
        except Exception as exc:
            refreshed_job = session.get(OpenAIAccountCreationJob, job_id)
            refreshed_request = session.get(OpenAIAccountCreationRequest, request.id)
            if not refreshed_job or not refreshed_request:
                raise
            if challenge_retryable(str(exc)):
                return schedule_openai_account_creation_retry_or_manual_review(
                    session,
                    refreshed_job,
                    refreshed_request,
                    error_message=str(exc),
                )
            refreshed_job.status = OpenAIAccountCreationJobStatus.FAILED
            refreshed_job.last_error = str(exc)
            refreshed_job.evidence_path = str(build_request_evidence_dir(refreshed_job))
            refreshed_job.locked_at = None
            refreshed_job.finished_at = utcnow()
            refreshed_job.next_retry_at = None
            session.add(refreshed_job)
            refreshed_request.status_atual = OpenAIAccountCreationRequestStatus.FAILED
            refreshed_request.ultimo_erro = str(exc)
            session.add(refreshed_request)
            session.commit()
            session.refresh(refreshed_job)
            return job_to_schema_payload(refreshed_job)
