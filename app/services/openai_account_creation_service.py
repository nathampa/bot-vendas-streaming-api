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
MAX_ERROR_LENGTH = 500
MAX_AUTH_PATH_LENGTH = 80
ACCOUNT_CREATION_SEQUENCE_BLOCKING_STATUSES = {
    OpenAIAccountCreationJobStatus.PENDING,
    OpenAIAccountCreationJobStatus.RUNNING,
    OpenAIAccountCreationJobStatus.WAITING_OTP_INPUT,
    OpenAIAccountCreationJobStatus.RETRY_WAIT,
}


def utcnow() -> datetime.datetime:
    return datetime.datetime.utcnow()


def normalize_error_message(message: str | None) -> str | None:
    if message is None:
        return None
    value = re.sub(r"\s+", " ", str(message)).strip()
    if len(value) <= MAX_ERROR_LENGTH:
        return value
    return value[: MAX_ERROR_LENGTH - 3] + "..."


def normalize_auth_path(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"\s+", " ", str(value)).strip()
    if len(normalized) <= MAX_AUTH_PATH_LENGTH:
        return normalized
    return normalized[: MAX_AUTH_PATH_LENGTH - 3] + "..."


def slugify(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("_") or "default"


def normalize_optional_email(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    return normalized


def account_creation_session_root() -> Path:
    root = Path(settings.OPENAI_ACCOUNT_CREATION_SESSION_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return root


def account_creation_evidence_root() -> Path:
    root = Path(settings.OPENAI_ACCOUNT_CREATION_EVIDENCE_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return root


def account_creation_outlook_profile_root() -> Path:
    root = Path(settings.OPENAI_ACCOUNT_CREATION_OUTLOOK_PROFILE_ROOT)
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


def build_request_outlook_profile_path(request: OpenAIAccountCreationRequest) -> str:
    email_part = slugify((request.outlook_email or request.email).split("@", 1)[0].lower())
    return str(account_creation_outlook_profile_root() / f"outlook_{email_part}_{str(request.id)[:8]}")


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


def account_creation_sequence_retry_seconds() -> int:
    return max(10, int(settings.OPENAI_ACCOUNT_CREATION_SEQUENCE_RETRY_SECONDS))


def account_creation_retry_deadline(job: OpenAIAccountCreationJob) -> datetime.datetime:
    return job.created_at + datetime.timedelta(seconds=settings.OPENAI_ACCOUNT_CREATION_RETRY_WINDOW_SECONDS)


def find_blocking_account_creation_predecessor(
    session: Session,
    job: OpenAIAccountCreationJob,
) -> OpenAIAccountCreationJob | None:
    return session.exec(
        select(OpenAIAccountCreationJob)
        .where(OpenAIAccountCreationJob.id != job.id)
        .where(OpenAIAccountCreationJob.created_at < job.created_at)
        .where(OpenAIAccountCreationJob.status.in_(ACCOUNT_CREATION_SEQUENCE_BLOCKING_STATUSES))
        .order_by(OpenAIAccountCreationJob.created_at.asc())
        .limit(1)
    ).first()


def defer_account_creation_job_until_predecessor_finishes(
    session: Session,
    job: OpenAIAccountCreationJob,
    request: OpenAIAccountCreationRequest,
    predecessor: OpenAIAccountCreationJob,
) -> dict:
    now = utcnow()
    retry_seconds = account_creation_sequence_retry_seconds()
    next_retry = now + datetime.timedelta(seconds=retry_seconds)
    predecessor_request = session.get(OpenAIAccountCreationRequest, predecessor.request_id)
    predecessor_email = predecessor_request.email if predecessor_request else str(predecessor.id)
    message = normalize_error_message(
        f"Aguardando job anterior finalizar antes de criar esta conta: {predecessor_email} ({predecessor.status.value})."
    )

    job.status = OpenAIAccountCreationJobStatus.RETRY_WAIT
    job.last_error = message
    job.locked_at = None
    job.started_at = None
    job.finished_at = None
    job.next_retry_at = next_retry
    session.add(job)

    request.status_atual = OpenAIAccountCreationRequestStatus.RETRY_WAIT
    request.ultimo_erro = message
    request.atualizado_em = now
    session.add(request)
    session.commit()
    session.refresh(job)
    enqueue_openai_account_creation_job(job.id, countdown_seconds=retry_seconds)
    return job_to_schema_payload(job)


def validate_batch_item(email: str, senha: str) -> bool:
    email_clean = email.strip().lower()
    senha_clean = senha.strip()
    return bool(email_clean and senha_clean and EMAIL_REGEX.match(email_clean))


def request_to_schema_payload(request: OpenAIAccountCreationRequest) -> dict:
    return {
        "id": request.id,
        "email": request.email,
        "outlook_email": request.outlook_email,
        "has_outlook_password": bool(request.outlook_password_encrypted),
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
        "outlook_email": request.outlook_email if request else None,
        "has_outlook_password": bool(request.outlook_password_encrypted) if request else False,
        "session_storage_path": request.session_storage_path if request else None,
        "workspace_name": request.workspace_name if request else None,
    }


def create_account_creation_request_and_job(
    session: Session,
    *,
    email: str,
    senha: str,
    outlook_email: str | None = None,
    outlook_senha: str | None = None,
) -> tuple[OpenAIAccountCreationRequest, OpenAIAccountCreationJob]:
    request = OpenAIAccountCreationRequest(
        email=email.strip().lower(),
        senha_encrypted=encrypt_data(senha.strip()),
        outlook_email=normalize_optional_email(outlook_email),
        outlook_password_encrypted=encrypt_data(outlook_senha.strip()) if outlook_senha and outlook_senha.strip() else None,
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


def attach_outlook_credentials_to_requests(
    session: Session,
    *,
    items: list[dict[str, str | None]],
) -> tuple[list[OpenAIAccountCreationRequest], list[str]]:
    updated_requests: list[OpenAIAccountCreationRequest] = []
    ignored_items: list[str] = []

    for item in items:
        email = (item.get("email") or "").strip().lower()
        outlook_senha = (item.get("outlook_senha") or "").strip()
        outlook_email = normalize_optional_email(item.get("outlook_email"))
        if not email or not outlook_senha:
            ignored_items.append(email or "<email-vazio>")
            continue

        request = session.exec(
            select(OpenAIAccountCreationRequest).where(OpenAIAccountCreationRequest.email == email)
        ).first()
        if not request:
            ignored_items.append(email)
            continue

        request.outlook_email = outlook_email
        request.outlook_password_encrypted = encrypt_data(outlook_senha)
        request.atualizado_em = utcnow()
        session.add(request)
        updated_requests.append(request)

    session.flush()
    return updated_requests, ignored_items


def process_openai_account_creation_job_task(job_id: str) -> None:
    try:
        processed_job = process_openai_account_creation_job(uuid.UUID(job_id))
        print(
            "BACKGROUND TASK: Job de criacao de conta OpenAI processado. "
            f"id={processed_job['id']} status={processed_job['status']}"
        )
    except Exception as exc:
        print(f"ERRO CRITICO na tarefa local de criacao de conta OpenAI ({job_id}): {exc}")


def fetch_openai_account_creation_outlook_otp_task(job_id: str) -> None:
    try:
        result = process_openai_account_creation_outlook_fetch(uuid.UUID(job_id))
        print(
            "BACKGROUND TASK: Fetch Outlook OTP processado. "
            f"id={result['id']} status={result['status']}"
        )
    except Exception as exc:
        print(f"ERRO CRITICO na tarefa local de fetch Outlook OTP ({job_id}): {exc}")


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


def enqueue_openai_account_creation_outlook_fetch_job(
    job_id: uuid.UUID,
    *,
    background_tasks: Optional[BackgroundTasks] = None,
) -> None:
    if not settings.OPENAI_ACCOUNT_CREATION_ENABLED:
        return
    if settings.CELERY_BROKER_URL:
        from app.worker.celery_app import celery_app

        celery_app.send_task("process_openai_account_creation_outlook_fetch_job", args=[str(job_id)])
        return
    if background_tasks is not None:
        background_tasks.add_task(fetch_openai_account_creation_outlook_otp_task, str(job_id))
        return

    threading.Thread(
        target=fetch_openai_account_creation_outlook_otp_task,
        args=(str(job_id),),
        daemon=True,
        name=f"openai-account-fetch-otp-{job_id}",
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


def resolve_outlook_credentials(request: OpenAIAccountCreationRequest) -> tuple[str, str]:
    outlook_email = normalize_optional_email(request.outlook_email) or request.email
    encrypted_password = request.outlook_password_encrypted or request.senha_encrypted
    password = decrypt_data(encrypted_password) if encrypted_password else None
    if not password:
        raise OpenAIAccountCreationManualReviewRequired(
            "Nao foi possivel descriptografar a senha da conta Outlook vinculada."
        )
    return outlook_email, password


def build_host_runner_outlook_fetch_request(
    job: OpenAIAccountCreationJob,
    request: OpenAIAccountCreationRequest,
) -> dict:
    outlook_email, outlook_password = resolve_outlook_credentials(request)
    evidence_dir = build_request_evidence_dir(job) / "outlook_otp"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    return {
        "action": "fetch_outlook_otp",
        "job_id": str(job.id),
        "outlook_email": outlook_email,
        "outlook_password": outlook_password,
        "profile_dir": build_request_outlook_profile_path(request),
        "evidence_dir": str(evidence_dir),
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


def fetch_outlook_otp_for_job(
    session: Session,
    job: OpenAIAccountCreationJob,
    *,
    background_tasks: Optional[BackgroundTasks] = None,
) -> tuple[str, str, OpenAIAccountCreationJob]:
    if job.status not in {
        OpenAIAccountCreationJobStatus.WAITING_OTP_INPUT,
        OpenAIAccountCreationJobStatus.CREATED,
    }:
        raise OpenAIAccountCreationManualReviewRequired(
            "Este job nao permite busca de OTP Outlook neste estado."
        )

    request = session.get(OpenAIAccountCreationRequest, job.request_id)
    if not request:
        raise OpenAIAccountCreationManualReviewRequired("Requisicao de criacao de conta OpenAI nao encontrada.")

    result = execute_host_runner_request(build_host_runner_outlook_fetch_request(job, request))
    result_status = (result.get("status") or "FAILED").upper()
    result_message = normalize_error_message(result.get("message"))
    refreshed_job = session.get(OpenAIAccountCreationJob, job.id)
    refreshed_request = session.get(OpenAIAccountCreationRequest, request.id)
    if not refreshed_job or not refreshed_request:
        raise OpenAIAccountCreationManualReviewRequired("Job indisponivel apos o fetch de OTP do Outlook.")

    refreshed_job.evidence_path = result.get("evidence_path") or refreshed_job.evidence_path

    if result_status == "OTP_FOUND":
        otp_code = re.sub(r"\D+", "", result.get("otp_code") or "")
        if len(otp_code) != 6:
            raise OpenAIAccountCreationManualReviewRequired(
                "O fetch do Outlook retornou um OTP invalido."
            )
        if refreshed_job.status == OpenAIAccountCreationJobStatus.WAITING_OTP_INPUT:
            submit_openai_account_creation_otp(session, refreshed_job, otp_code)
            refreshed_job.evidence_path = result.get("evidence_path") or refreshed_job.evidence_path
            session.add(refreshed_job)
            session.commit()
            session.refresh(refreshed_job)
            enqueue_openai_account_creation_job(refreshed_job.id, background_tasks=background_tasks)
            return "OTP encontrado no Outlook e job reenfileirado.", result_status, refreshed_job

        refreshed_job.last_error = f"OTP Outlook encontrado: {otp_code}"
        refreshed_job.locked_at = None
        refreshed_job.updated_at = utcnow()
        session.add(refreshed_job)
        refreshed_request.ultimo_erro = refreshed_job.last_error
        refreshed_request.atualizado_em = utcnow()
        session.add(refreshed_request)
        session.commit()
        session.refresh(refreshed_job)
        return "OTP encontrado no Outlook para login manual.", result_status, refreshed_job

    refreshed_job.last_error = result_message or (
        "Nao foi possivel localizar um OTP visivel da OpenAI no Outlook."
        if result_status == "OTP_NOT_FOUND"
        else "Falha ao buscar OTP no Outlook."
    )
    refreshed_job.locked_at = None
    refreshed_job.updated_at = utcnow()
    session.add(refreshed_job)
    refreshed_request.ultimo_erro = refreshed_job.last_error
    session.add(refreshed_request)
    session.commit()
    session.refresh(refreshed_job)
    return refreshed_job.last_error, result_status, refreshed_job


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
    error_message = normalize_error_message(error_message)
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


def start_openai_account_creation_outlook_fetch(
    session: Session,
    job: OpenAIAccountCreationJob,
    *,
    start_message: str = "Busca de OTP Outlook iniciada pelo painel.",
) -> OpenAIAccountCreationJob:
    if job.status not in {
        OpenAIAccountCreationJobStatus.WAITING_OTP_INPUT,
        OpenAIAccountCreationJobStatus.CREATED,
    }:
        raise OpenAIAccountCreationManualReviewRequired(
            "Este job nao permite busca de OTP Outlook neste estado."
        )
    if job.locked_at is not None:
        raise OpenAIAccountCreationManualReviewRequired("Ja existe uma busca de OTP Outlook em andamento para este job.")

    request = session.get(OpenAIAccountCreationRequest, job.request_id)
    if not request:
        raise OpenAIAccountCreationManualReviewRequired("Requisicao de criacao de conta OpenAI nao encontrada.")

    resolve_outlook_credentials(request)

    now = utcnow()
    job.locked_at = now
    job.last_error = normalize_error_message(start_message)
    job.updated_at = now
    session.add(job)
    request.ultimo_erro = job.last_error
    request.atualizado_em = now
    session.add(request)
    session.flush()
    return job


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
            job.last_error = normalize_error_message("Requisicao de criacao de conta nao encontrada.")
            session.add(job)
            session.commit()
            session.refresh(job)
            return job_to_schema_payload(job)

        blocking_predecessor = find_blocking_account_creation_predecessor(session, job)
        if blocking_predecessor:
            return defer_account_creation_job_until_predecessor_finishes(
                session,
                job,
                request,
                blocking_predecessor,
            )

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
            result_message = normalize_error_message(result.get("message"))

            if result_status == "WAITING_OTP_INPUT":
                refreshed_job.status = OpenAIAccountCreationJobStatus.WAITING_OTP_INPUT
                refreshed_job.last_error = result_message
                refreshed_job.evidence_path = result.get("evidence_path") or str(build_request_evidence_dir(refreshed_job))
                refreshed_job.auth_path_used = normalize_auth_path(result.get("auth_path_used"))
                refreshed_job.locked_at = None
                refreshed_job.finished_at = utcnow()
                session.add(refreshed_job)
                refreshed_request.status_atual = OpenAIAccountCreationRequestStatus.WAITING_OTP_INPUT
                refreshed_request.ultimo_erro = result_message
                session.add(refreshed_request)
                session.commit()
                session.refresh(refreshed_job)
                try:
                    start_openai_account_creation_outlook_fetch(
                        session,
                        refreshed_job,
                        start_message="Busca de OTP Outlook iniciada automaticamente pelo fluxo de criacao.",
                    )
                    session.commit()
                    session.refresh(refreshed_job)
                    enqueue_openai_account_creation_outlook_fetch_job(refreshed_job.id)
                except Exception as exc:
                    session.rollback()
                    refreshed_job = session.get(OpenAIAccountCreationJob, job_id)
                    refreshed_request = session.get(OpenAIAccountCreationRequest, request.id)
                    if refreshed_job and refreshed_request:
                        fallback_message = normalize_error_message(
                            f"Aguardando OTP manual. Busca automatica Outlook nao iniciada: {exc}"
                        )
                        refreshed_job.last_error = fallback_message or refreshed_job.last_error
                        refreshed_job.locked_at = None
                        refreshed_job.updated_at = utcnow()
                        session.add(refreshed_job)
                        refreshed_request.ultimo_erro = refreshed_job.last_error
                        refreshed_request.atualizado_em = utcnow()
                        session.add(refreshed_request)
                        session.commit()
                        session.refresh(refreshed_job)
                return job_to_schema_payload(refreshed_job)

            if result_status == "CREATED":
                refreshed_job.status = OpenAIAccountCreationJobStatus.CREATED
                refreshed_job.auth_path_used = normalize_auth_path(result.get("auth_path_used"))
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
            session.rollback()
            refreshed_job = session.get(OpenAIAccountCreationJob, job_id)
            refreshed_request = session.get(OpenAIAccountCreationRequest, request.id)
            if not refreshed_job or not refreshed_request:
                raise
            if challenge_retryable(str(exc)):
                return schedule_openai_account_creation_retry_or_manual_review(
                    session,
                    refreshed_job,
                    refreshed_request,
                    error_message=normalize_error_message(str(exc)),
                )
            normalized_error = normalize_error_message(str(exc))
            refreshed_job.status = OpenAIAccountCreationJobStatus.FAILED
            refreshed_job.last_error = normalized_error
            refreshed_job.evidence_path = str(build_request_evidence_dir(refreshed_job))
            refreshed_job.locked_at = None
            refreshed_job.finished_at = utcnow()
            refreshed_job.next_retry_at = None
            session.add(refreshed_job)
            refreshed_request.status_atual = OpenAIAccountCreationRequestStatus.FAILED
            refreshed_request.ultimo_erro = normalized_error
            session.add(refreshed_request)
            session.commit()
            session.refresh(refreshed_job)
            return job_to_schema_payload(refreshed_job)


def process_openai_account_creation_outlook_fetch(job_id: uuid.UUID) -> dict:
    with Session(engine) as session:
        job = session.get(OpenAIAccountCreationJob, job_id)
        if not job:
            raise OpenAIAccountCreationError(f"Job {job_id} nao encontrado.")
        if job.status not in {
            OpenAIAccountCreationJobStatus.WAITING_OTP_INPUT,
            OpenAIAccountCreationJobStatus.CREATED,
        }:
            return job_to_schema_payload(job)

        try:
            _, _, refreshed_job = fetch_outlook_otp_for_job(session, job)
            return job_to_schema_payload(refreshed_job)
        except Exception as exc:
            session.rollback()
            refreshed_job = session.get(OpenAIAccountCreationJob, job_id)
            if not refreshed_job:
                raise
            request = session.get(OpenAIAccountCreationRequest, refreshed_job.request_id)
            normalized_error = normalize_error_message(str(exc))
            refreshed_job.last_error = normalized_error
            refreshed_job.locked_at = None
            refreshed_job.updated_at = utcnow()
            session.add(refreshed_job)
            if request:
                request.ultimo_erro = normalized_error
                request.atualizado_em = utcnow()
                session.add(request)
            session.commit()
            session.refresh(refreshed_job)
            return job_to_schema_payload(refreshed_job)
