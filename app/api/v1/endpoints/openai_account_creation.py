import uuid
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.api.v1.deps import get_current_admin_user
from app.db.database import get_session
from app.models.openai_account_creation_models import (
    OpenAIAccountCreationJob,
    OpenAIAccountCreationJobStatus,
    OpenAIAccountCreationRequest,
)
from app.schemas.openai_account_creation_schemas import (
    OpenAIAccountCreationBatchCreateRequest,
    OpenAIAccountCreationBatchCreateResponse,
    OpenAIAccountCreationJobRead,
    OpenAIAccountCreationOTPSubmitRequest,
    OpenAIAccountCreationRetryResponse,
)
from app.services.openai_account_creation_service import (
    cancel_openai_account_creation_job,
    create_account_creation_request_and_job,
    enqueue_openai_account_creation_job,
    job_to_schema_payload,
    retry_openai_account_creation_job,
    submit_openai_account_creation_otp,
    validate_batch_item,
)

router = APIRouter(dependencies=[Depends(get_current_admin_user)])


def _to_job_read(job: OpenAIAccountCreationJob, request: Optional[OpenAIAccountCreationRequest] = None) -> OpenAIAccountCreationJobRead:
    if request is not None:
        job.request = request
    return OpenAIAccountCreationJobRead(**job_to_schema_payload(job))


@router.post("/batch", response_model=OpenAIAccountCreationBatchCreateResponse)
def create_batch_openai_account_jobs(
    *,
    payload: OpenAIAccountCreationBatchCreateRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    created_requests = 0
    created_jobs = 0
    ignored_items: list[str] = []
    created_job_reads: list[OpenAIAccountCreationJobRead] = []

    for item in payload.items:
        email = item.email.strip().lower()
        senha = item.senha.strip()
        if not validate_batch_item(email, senha):
            ignored_items.append(email or "<email-vazio>")
            continue

        existing_request = session.exec(
            select(OpenAIAccountCreationRequest).where(OpenAIAccountCreationRequest.email == email)
        ).first()
        if existing_request:
            ignored_items.append(email)
            continue

        request, job = create_account_creation_request_and_job(session, email=email, senha=senha)
        created_requests += 1
        created_jobs += 1
        created_job_reads.append(_to_job_read(job, request))

    session.commit()

    for job_read in created_job_reads:
        try:
            enqueue_openai_account_creation_job(uuid.UUID(str(job_read.id)), background_tasks=background_tasks)
        except Exception as exc:
            print(f"AVISO: falha ao enfileirar job de criacao de conta {job_read.id}: {exc}")

    return OpenAIAccountCreationBatchCreateResponse(
        created_requests=created_requests,
        created_jobs=created_jobs,
        ignored_items=ignored_items,
        jobs=created_job_reads,
    )


@router.get("/jobs", response_model=List[OpenAIAccountCreationJobRead])
def list_openai_account_creation_jobs(
    *,
    session: Session = Depends(get_session),
    status: Optional[str] = None,
    email: Optional[str] = None,
    only_active: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
):
    stmt = (
        select(OpenAIAccountCreationJob, OpenAIAccountCreationRequest)
        .join(OpenAIAccountCreationRequest, OpenAIAccountCreationRequest.id == OpenAIAccountCreationJob.request_id)
        .order_by(OpenAIAccountCreationJob.created_at.desc())
        .limit(limit)
    )
    if status:
        stmt = stmt.where(OpenAIAccountCreationJob.status == status.strip().upper())
    elif only_active:
        stmt = stmt.where(
            OpenAIAccountCreationJob.status.in_(
                (
                    OpenAIAccountCreationJobStatus.PENDING,
                    OpenAIAccountCreationJobStatus.RUNNING,
                    OpenAIAccountCreationJobStatus.WAITING_OTP_INPUT,
                    OpenAIAccountCreationJobStatus.RETRY_WAIT,
                    OpenAIAccountCreationJobStatus.MANUAL_REVIEW,
                )
            )
        )
    if email:
        stmt = stmt.where(OpenAIAccountCreationRequest.email.contains(email.strip().lower()))

    rows = session.exec(stmt).all()
    return [_to_job_read(job, request) for job, request in rows]


@router.get("/jobs/{job_id}", response_model=OpenAIAccountCreationJobRead)
def get_openai_account_creation_job(
    *,
    session: Session = Depends(get_session),
    job_id: uuid.UUID,
):
    job = session.get(OpenAIAccountCreationJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job de criacao de conta OpenAI nao encontrado.")
    request = session.get(OpenAIAccountCreationRequest, job.request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Requisicao de criacao de conta OpenAI nao encontrada.")
    return _to_job_read(job, request)


@router.post("/jobs/{job_id}/submit-otp", response_model=OpenAIAccountCreationRetryResponse)
def submit_openai_account_creation_job_otp(
    *,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    job_id: uuid.UUID,
    payload: OpenAIAccountCreationOTPSubmitRequest,
):
    job = session.get(OpenAIAccountCreationJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job de criacao de conta OpenAI nao encontrado.")

    try:
        submit_openai_account_creation_otp(session, job, payload.otp_code)
        session.commit()
        session.refresh(job)
        enqueue_openai_account_creation_job(job.id, background_tasks=background_tasks)
        request = session.get(OpenAIAccountCreationRequest, job.request_id)
        return OpenAIAccountCreationRetryResponse(
            message="Codigo OTP recebido. O job foi reenfileirado.",
            job=_to_job_read(job, request),
        )
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/jobs/{job_id}/retry", response_model=OpenAIAccountCreationRetryResponse)
def retry_openai_account_creation_job_endpoint(
    *,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    job_id: uuid.UUID,
):
    job = session.get(OpenAIAccountCreationJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job de criacao de conta OpenAI nao encontrado.")

    try:
        retry_openai_account_creation_job(session, job)
        session.commit()
        session.refresh(job)
        enqueue_openai_account_creation_job(job.id, background_tasks=background_tasks)
        request = session.get(OpenAIAccountCreationRequest, job.request_id)
        return OpenAIAccountCreationRetryResponse(
            message="Job reenfileirado com sucesso.",
            job=_to_job_read(job, request),
        )
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/jobs/{job_id}/cancel", response_model=OpenAIAccountCreationRetryResponse)
def cancel_openai_account_creation_job_endpoint(
    *,
    session: Session = Depends(get_session),
    job_id: uuid.UUID,
):
    job = session.get(OpenAIAccountCreationJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job de criacao de conta OpenAI nao encontrado.")

    try:
        cancel_openai_account_creation_job(session, job)
        session.commit()
        session.refresh(job)
        request = session.get(OpenAIAccountCreationRequest, job.request_id)
        return OpenAIAccountCreationRetryResponse(
            message="Job cancelado com sucesso.",
            job=_to_job_read(job, request),
        )
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
