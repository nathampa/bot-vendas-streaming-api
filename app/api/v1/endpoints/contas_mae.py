import datetime
import uuid
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import func
from sqlmodel import Session, select

from app.api.v1.deps import get_current_admin_user
from app.db.database import get_session
from app.models.conta_mae_models import ContaMae, ContaMaeConvite, ContaMaeInviteJob
from app.models.produto_models import Produto
from app.schemas.conta_mae_schemas import (
    ContaMaeAdminDetails,
    ContaMaeAdminRead,
    ContaMaeConviteCreate,
    ContaMaeConviteRead,
    ContaMaeCreate,
    ContaMaeInviteJobRead,
    ContaMaeSessionPrepareResponse,
    ContaMaeSessionTestResponse,
    ContaMaeUpdate,
)
from app.services import security
from app.services.conta_mae_invite_service import (
    cancel_invite_job,
    create_invite_job_for_convite,
    enqueue_invite_job,
    job_to_schema_payload,
    mark_invite_job_sent_manually,
    notify_invite_job_sent,
    prepare_conta_mae_session,
    retry_invite_job,
    test_conta_mae_session,
)
from app.services.disponibilidade_service import (
    inativar_conta_mae_se_lotada,
    sincronizar_status_produto_por_disponibilidade,
)


router = APIRouter(dependencies=[Depends(get_current_admin_user)])
ACTIVE_INVITE_JOB_STATUSES = (
    "PENDING",
    "RUNNING",
    "WAITING_OTP",
    "RETRY_WAIT",
    "MANUAL_REVIEW",
)


def _get_conta_mae_produto_or_404(session: Session, conta: ContaMae) -> Produto:
    produto = session.get(Produto, conta.produto_id)
    if not produto:
        raise HTTPException(status_code=404, detail="Produto da conta mãe não encontrado")
    return produto


def _ensure_openai_invite_provider(produto: Produto) -> None:
    if not produto.uses_openai_invite_automation():
        raise HTTPException(
            status_code=400,
            detail="Sessão OpenAI só está disponível para produtos com automação OPENAI.",
        )


def _convites_count_and_emails(session: Session) -> tuple[dict[uuid.UUID, int], dict[uuid.UUID, set[str]]]:
    convite_rows = session.exec(
        select(ContaMaeConvite.conta_mae_id, ContaMaeConvite.email_cliente)
    ).all()
    counts_map: dict[uuid.UUID, int] = {}
    emails_map: dict[uuid.UUID, set[str]] = {}
    for conta_mae_id, email_cliente in convite_rows:
        counts_map[conta_mae_id] = counts_map.get(conta_mae_id, 0) + 1
        if email_cliente:
            emails_map.setdefault(conta_mae_id, set()).add(email_cliente)
    return counts_map, emails_map


def _to_conta_read(
    conta: ContaMae,
    *,
    produto: Produto,
    total_convites: int,
    emails_vinculados: List[str],
) -> ContaMaeAdminRead:
    today = datetime.date.today()
    dias_restantes = None
    if conta.data_expiracao:
        dias_restantes = (conta.data_expiracao - today).days

    return ContaMaeAdminRead(
        id=conta.id,
        produto_id=conta.produto_id,
        invite_provider=produto.invite_provider,
        uses_openai_invite_automation=produto.uses_openai_invite_automation(),
        login=conta.login,
        max_slots=conta.max_slots,
        slots_ocupados=conta.slots_ocupados,
        is_ativo=conta.is_ativo,
        data_expiracao=conta.data_expiracao,
        dias_restantes=dias_restantes,
        total_convites=total_convites,
        emails_vinculados=emails_vinculados,
        email_monitor_account_id=conta.email_monitor_account_id,
        session_storage_path=conta.session_storage_path,
        ultimo_login_automatizado_em=conta.ultimo_login_automatizado_em,
        ultimo_convite_sucesso_em=conta.ultimo_convite_sucesso_em,
        ultimo_erro_automacao=conta.ultimo_erro_automacao,
    )


def _to_job_read(job: ContaMaeInviteJob) -> ContaMaeInviteJobRead:
    return ContaMaeInviteJobRead(**job_to_schema_payload(job))


@router.get("/invite-jobs", response_model=List[ContaMaeInviteJobRead])
def list_invite_jobs(
    *,
    session: Session = Depends(get_session),
    conta_mae_id: Optional[uuid.UUID] = None,
    status: Optional[str] = None,
    email: Optional[str] = None,
    only_active: bool = False,
    limit: int = 100,
):
    stmt = (
        select(ContaMaeInviteJob, ContaMae.login)
        .join(ContaMae, ContaMae.id == ContaMaeInviteJob.conta_mae_id)
        .order_by(ContaMaeInviteJob.created_at.desc())
        .limit(min(max(limit, 1), 500))
    )
    if conta_mae_id:
        stmt = stmt.where(ContaMaeInviteJob.conta_mae_id == conta_mae_id)
    if status:
        stmt = stmt.where(ContaMaeInviteJob.status == status.strip().upper())
    elif only_active:
        stmt = stmt.where(ContaMaeInviteJob.status.in_(ACTIVE_INVITE_JOB_STATUSES))
    if email:
        stmt = stmt.where(func.lower(ContaMaeInviteJob.email_cliente).contains(email.strip().lower()))
    rows = session.exec(stmt).all()
    payloads = []
    for job, conta_login in rows:
        payload = job_to_schema_payload(job)
        payload["conta_mae_login"] = conta_login
        payloads.append(ContaMaeInviteJobRead(**payload))
    return payloads


@router.post("/invite-jobs/{job_id}/retry", response_model=ContaMaeInviteJobRead)
def retry_conta_mae_invite_job(
    *,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    job_id: uuid.UUID,
):
    job = session.get(ContaMaeInviteJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job de convite não encontrado")

    try:
        retry_invite_job(session, job)
        session.commit()
        session.refresh(job)
        try:
            enqueue_invite_job(job.id, background_tasks=background_tasks)
        except Exception as exc:
            print(f"AVISO: falha ao reenfileirar job de convite {job.id}: {exc}")
        return _to_job_read(job)
    except HTTPException:
        raise
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/invite-jobs/{job_id}/cancel", response_model=ContaMaeInviteJobRead)
def cancel_conta_mae_invite_job(
    *,
    session: Session = Depends(get_session),
    job_id: uuid.UUID,
):
    job = session.get(ContaMaeInviteJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job de convite não encontrado")

    try:
        cancel_invite_job(session, job)
        session.commit()
        session.refresh(job)
        return _to_job_read(job)
    except HTTPException:
        raise
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/invite-jobs/{job_id}/mark-manual-sent", response_model=ContaMaeInviteJobRead)
def mark_conta_mae_invite_job_manual_sent(
    *,
    session: Session = Depends(get_session),
    job_id: uuid.UUID,
):
    job = session.get(ContaMaeInviteJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job de convite não encontrado")

    conta = session.get(ContaMae, job.conta_mae_id)
    if not conta:
        raise HTTPException(status_code=404, detail="Conta mãe não encontrada para este job")

    try:
        mark_invite_job_sent_manually(session, job, conta)
        session.commit()
        session.refresh(job)
        session.refresh(conta)
        try:
            notify_invite_job_sent(session, job)
        except Exception as exc_notify:
            print(f"AVISO: falha ao notificar cliente do convite manual {job.id}: {exc_notify}")
        return _to_job_read(job)
    except HTTPException:
        raise
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/", response_model=ContaMaeAdminRead, status_code=status.HTTP_201_CREATED)
def create_conta_mae(
    *,
    session: Session = Depends(get_session),
    conta_in: ContaMaeCreate,
):
    produto = session.get(Produto, conta_in.produto_id)
    if not produto:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    if conta_in.max_slots < 1:
        raise HTTPException(status_code=400, detail="Max slots deve ser maior que zero.")

    senha_criptografada = security.encrypt_data(conta_in.senha)
    conta = ContaMae(
        produto_id=conta_in.produto_id,
        login=conta_in.login,
        senha=senha_criptografada,
        max_slots=conta_in.max_slots,
        data_expiracao=conta_in.data_expiracao,
        is_ativo=conta_in.is_ativo,
        email_monitor_account_id=conta_in.email_monitor_account_id,
        session_storage_path=conta_in.session_storage_path,
    )
    session.add(conta)
    sincronizar_status_produto_por_disponibilidade(session, produto)
    session.commit()
    session.refresh(conta)

    return _to_conta_read(conta, produto=produto, total_convites=0, emails_vinculados=[])


@router.get("/", response_model=List[ContaMaeAdminRead])
def get_contas_mae(session: Session = Depends(get_session)):
    contas = session.exec(select(ContaMae)).all()
    counts_map, emails_map = _convites_count_and_emails(session)
    produtos_map = {
        produto.id: produto
        for produto in session.exec(select(Produto)).all()
    }
    return [
        _to_conta_read(
            conta,
            produto=produtos_map[conta.produto_id],
            total_convites=counts_map.get(conta.id, 0),
            emails_vinculados=sorted(list(emails_map.get(conta.id, set()))),
        )
        for conta in contas
    ]


@router.get("/{conta_mae_id}", response_model=ContaMaeAdminDetails)
def get_conta_mae(
    *,
    session: Session = Depends(get_session),
    conta_mae_id: uuid.UUID,
):
    conta = session.get(ContaMae, conta_mae_id)
    if not conta:
        raise HTTPException(status_code=404, detail="Conta mãe não encontrada")

    convites_db = session.exec(
        select(ContaMaeConvite)
        .where(ContaMaeConvite.conta_mae_id == conta_mae_id)
        .order_by(ContaMaeConvite.criado_em.desc())
    ).all()
    jobs_db = session.exec(
        select(ContaMaeInviteJob)
        .where(ContaMaeInviteJob.conta_mae_id == conta_mae_id)
        .order_by(ContaMaeInviteJob.created_at.desc())
        .limit(100)
    ).all()

    senha_descriptografada = security.decrypt_data(conta.senha)
    produto = _get_conta_mae_produto_or_404(session, conta)
    conta_read = _to_conta_read(
        conta,
        produto=produto,
        total_convites=len(convites_db),
        emails_vinculados=sorted(list({convite.email_cliente for convite in convites_db if convite.email_cliente})),
    )

    return ContaMaeAdminDetails(
        **conta_read.model_dump(),
        senha=senha_descriptografada,
        convites=[
            ContaMaeConviteRead(
                id=convite.id,
                email_cliente=convite.email_cliente,
                criado_em=convite.criado_em,
                pedido_id=convite.pedido_id,
            )
            for convite in convites_db
        ],
        invite_jobs=[_to_job_read(job) for job in jobs_db],
    )


@router.post("/{conta_mae_id}/session/prepare", response_model=ContaMaeSessionPrepareResponse)
def prepare_conta_mae_openai_session(
    *,
    session: Session = Depends(get_session),
    conta_mae_id: uuid.UUID,
):
    conta = session.get(ContaMae, conta_mae_id)
    if not conta:
        raise HTTPException(status_code=404, detail="Conta mãe não encontrada")
    produto = _get_conta_mae_produto_or_404(session, conta)
    _ensure_openai_invite_provider(produto)

    payload = prepare_conta_mae_session(conta)
    session.add(conta)
    session.commit()
    session.refresh(conta)
    return ContaMaeSessionPrepareResponse(**payload)


@router.post("/{conta_mae_id}/session/test", response_model=ContaMaeSessionTestResponse)
def test_conta_mae_openai_session(
    *,
    session: Session = Depends(get_session),
    conta_mae_id: uuid.UUID,
):
    conta = session.get(ContaMae, conta_mae_id)
    if not conta:
        raise HTTPException(status_code=404, detail="Conta mãe não encontrada")
    produto = _get_conta_mae_produto_or_404(session, conta)
    _ensure_openai_invite_provider(produto)

    payload = test_conta_mae_session(conta)
    return ContaMaeSessionTestResponse(**payload)


@router.put("/{conta_mae_id}", response_model=ContaMaeAdminRead)
def update_conta_mae(
    *,
    session: Session = Depends(get_session),
    conta_mae_id: uuid.UUID,
    conta_in: ContaMaeUpdate,
):
    conta = session.get(ContaMae, conta_mae_id)
    if not conta:
        raise HTTPException(status_code=404, detail="Conta mãe não encontrada")

    update_data = conta_in.model_dump(exclude_unset=True)
    if "max_slots" in update_data and update_data["max_slots"] is not None:
        if update_data["max_slots"] < 1:
            raise HTTPException(status_code=400, detail="Max slots deve ser maior que zero.")
        if update_data["max_slots"] < conta.slots_ocupados:
            raise HTTPException(
                status_code=400,
                detail="Max slots não pode ser menor que os slots ocupados.",
            )
    if "senha" in update_data:
        update_data["senha"] = security.encrypt_data(update_data["senha"])

    conta.sqlmodel_update(update_data)
    inativar_conta_mae_se_lotada(conta)
    session.add(conta)
    produto = session.get(Produto, conta.produto_id)
    if produto:
        sincronizar_status_produto_por_disponibilidade(session, produto)
    session.commit()
    session.refresh(conta)

    total_convites = session.exec(
        select(func.count(ContaMaeConvite.id)).where(ContaMaeConvite.conta_mae_id == conta.id)
    ).one()
    emails = sorted(
        list(
            {
                email
                for email in session.exec(
                    select(ContaMaeConvite.email_cliente).where(ContaMaeConvite.conta_mae_id == conta.id)
                ).all()
                if email
            }
        )
    )
    if not produto:
        raise HTTPException(status_code=404, detail="Produto da conta mãe não encontrado")
    return _to_conta_read(conta, produto=produto, total_convites=total_convites, emails_vinculados=emails)


@router.delete("/{conta_mae_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conta_mae(
    *,
    session: Session = Depends(get_session),
    conta_mae_id: uuid.UUID,
):
    conta = session.get(ContaMae, conta_mae_id)
    if not conta:
        raise HTTPException(status_code=404, detail="Conta mãe não encontrada")

    try:
        session.delete(conta)
        session.commit()
    except Exception as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro de banco de dados ao deletar conta mãe: {exc}",
        )


@router.post("/{conta_mae_id}/convites", response_model=ContaMaeConviteRead)
def add_convite_conta_mae(
    *,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    conta_mae_id: uuid.UUID,
    convite_in: ContaMaeConviteCreate,
):
    conta = session.get(ContaMae, conta_mae_id)
    if not conta:
        raise HTTPException(status_code=404, detail="Conta mãe não encontrada")

    email_cliente = convite_in.email_cliente.strip()
    if not email_cliente:
        raise HTTPException(status_code=400, detail="Email do cliente é obrigatório")

    existente = session.exec(
        select(ContaMaeConvite)
        .where(ContaMaeConvite.conta_mae_id == conta_mae_id)
        .where(ContaMaeConvite.email_cliente == email_cliente)
    ).first()
    if existente:
        raise HTTPException(status_code=409, detail="Email já cadastrado nesta conta mãe")

    if conta.slots_ocupados >= conta.max_slots:
        raise HTTPException(status_code=409, detail="Conta mãe sem slots disponíveis.")

    produto = _get_conta_mae_produto_or_404(session, conta)
    convite = ContaMaeConvite(conta_mae_id=conta_mae_id, email_cliente=email_cliente)
    conta.slots_ocupados += 1
    inativar_conta_mae_se_lotada(conta)
    session.add(conta)
    sincronizar_status_produto_por_disponibilidade(session, produto)
    session.add(convite)
    session.flush()
    job = create_invite_job_for_convite(session, convite) if produto.uses_openai_invite_automation() else None
    session.commit()
    session.refresh(convite)
    if job:
        try:
            enqueue_invite_job(job.id, background_tasks=background_tasks)
        except Exception as exc:
            print(f"AVISO: falha ao enfileirar job de convite {job.id}: {exc}")

    return ContaMaeConviteRead(
        id=convite.id,
        email_cliente=convite.email_cliente,
        criado_em=convite.criado_em,
        pedido_id=convite.pedido_id,
    )


@router.delete("/{conta_mae_id}/convites/{convite_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_convite_conta_mae(
    *,
    session: Session = Depends(get_session),
    conta_mae_id: uuid.UUID,
    convite_id: uuid.UUID,
):
    conta = session.get(ContaMae, conta_mae_id)
    if not conta:
        raise HTTPException(status_code=404, detail="Conta mãe não encontrada")

    convite = session.get(ContaMaeConvite, convite_id)
    if not convite or convite.conta_mae_id != conta_mae_id:
        raise HTTPException(status_code=404, detail="Convite não encontrado para esta conta mãe")

    conta_estava_lotada = conta.slots_ocupados >= conta.max_slots
    conta.slots_ocupados = max(conta.slots_ocupados - 1, 0)

    if conta_estava_lotada and (conta.data_expiracao is None or conta.data_expiracao >= datetime.date.today()):
        conta.is_ativo = True

    if convite.invite_job:
        session.delete(convite.invite_job)
    session.delete(convite)
    session.add(conta)
    produto = session.get(Produto, conta.produto_id)
    if produto:
        sincronizar_status_produto_por_disponibilidade(session, produto)
    session.commit()
