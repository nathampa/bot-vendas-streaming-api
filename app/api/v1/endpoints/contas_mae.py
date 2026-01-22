import datetime
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from sqlalchemy import func

from app.api.v1.deps import get_current_admin_user
from app.db.database import get_session
from app.models.produto_models import Produto
from app.models.conta_mae_models import ContaMae, ContaMaeConvite
from app.schemas.conta_mae_schemas import (
    ContaMaeCreate,
    ContaMaeUpdate,
    ContaMaeAdminRead,
    ContaMaeAdminDetails,
    ContaMaeConviteRead,
    ContaMaeConviteCreate,
)
from app.services import security


router = APIRouter(dependencies=[Depends(get_current_admin_user)])


@router.post("/", response_model=ContaMaeAdminRead, status_code=status.HTTP_201_CREATED)
def create_conta_mae(
    *,
    session: Session = Depends(get_session),
    conta_in: ContaMaeCreate
):
    produto = session.get(Produto, conta_in.produto_id)
    if not produto:
        raise HTTPException(status_code=404, detail="Produto nÃ£o encontrado")
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
    )
    session.add(conta)
    session.commit()
    session.refresh(conta)

    today = datetime.date.today()
    dias_restantes = None
    if conta.data_expiracao:
        dias_restantes = (conta.data_expiracao - today).days

    return ContaMaeAdminRead(
        id=conta.id,
        produto_id=conta.produto_id,
        login=conta.login,
        max_slots=conta.max_slots,
        slots_ocupados=conta.slots_ocupados,
        is_ativo=conta.is_ativo,
        data_expiracao=conta.data_expiracao,
        dias_restantes=dias_restantes,
        total_convites=0,
    )


@router.get("/", response_model=List[ContaMaeAdminRead])
def get_contas_mae(session: Session = Depends(get_session)):
    contas = session.exec(select(ContaMae)).all()

    counts = session.exec(
        select(ContaMaeConvite.conta_mae_id, func.count(ContaMaeConvite.id))
        .group_by(ContaMaeConvite.conta_mae_id)
    ).all()
    counts_map = {conta_id: total for conta_id, total in counts}

    today = datetime.date.today()
    response: List[ContaMaeAdminRead] = []
    for conta in contas:
        dias_restantes = None
        if conta.data_expiracao:
            dias_restantes = (conta.data_expiracao - today).days

        response.append(
            ContaMaeAdminRead(
                id=conta.id,
                produto_id=conta.produto_id,
                login=conta.login,
                max_slots=conta.max_slots,
                slots_ocupados=conta.slots_ocupados,
                is_ativo=conta.is_ativo,
                data_expiracao=conta.data_expiracao,
                dias_restantes=dias_restantes,
                total_convites=counts_map.get(conta.id, 0),
            )
        )

    return response


@router.get("/{conta_mae_id}", response_model=ContaMaeAdminDetails)
def get_conta_mae(
    *,
    session: Session = Depends(get_session),
    conta_mae_id: uuid.UUID
):
    conta = session.get(ContaMae, conta_mae_id)
    if not conta:
        raise HTTPException(status_code=404, detail="Conta mÃ£e nÃ£o encontrada")

    senha_descriptografada = security.decrypt_data(conta.senha)

    convites_db = session.exec(
        select(ContaMaeConvite)
        .where(ContaMaeConvite.conta_mae_id == conta_mae_id)
        .order_by(ContaMaeConvite.criado_em.desc())
    ).all()

    convites = [
        ContaMaeConviteRead(
            id=convite.id,
            email_cliente=convite.email_cliente,
            criado_em=convite.criado_em,
            pedido_id=convite.pedido_id,
        )
        for convite in convites_db
    ]

    today = datetime.date.today()
    dias_restantes = None
    if conta.data_expiracao:
        dias_restantes = (conta.data_expiracao - today).days

    return ContaMaeAdminDetails(
        id=conta.id,
        produto_id=conta.produto_id,
        login=conta.login,
        max_slots=conta.max_slots,
        slots_ocupados=conta.slots_ocupados,
        is_ativo=conta.is_ativo,
        data_expiracao=conta.data_expiracao,
        dias_restantes=dias_restantes,
        total_convites=len(convites),
        senha=senha_descriptografada,
        convites=convites,
    )


@router.put("/{conta_mae_id}", response_model=ContaMaeAdminRead)
def update_conta_mae(
    *,
    session: Session = Depends(get_session),
    conta_mae_id: uuid.UUID,
    conta_in: ContaMaeUpdate
):
    conta = session.get(ContaMae, conta_mae_id)
    if not conta:
        raise HTTPException(status_code=404, detail="Conta mÃ£e nÃ£o encontrada")

    update_data = conta_in.model_dump(exclude_unset=True)
    if "max_slots" in update_data and update_data["max_slots"] is not None:
        if update_data["max_slots"] < 1:
            raise HTTPException(status_code=400, detail="Max slots deve ser maior que zero.")
        if update_data["max_slots"] < conta.slots_ocupados:
            raise HTTPException(
                status_code=400,
                detail="Max slots nÃ£o pode ser menor que os slots ocupados."
            )
    if "senha" in update_data:
        update_data["senha"] = security.encrypt_data(update_data["senha"])

    conta.sqlmodel_update(update_data)
    session.add(conta)
    session.commit()
    session.refresh(conta)

    today = datetime.date.today()
    dias_restantes = None
    if conta.data_expiracao:
        dias_restantes = (conta.data_expiracao - today).days

    total_convites = session.exec(
        select(func.count(ContaMaeConvite.id)).where(ContaMaeConvite.conta_mae_id == conta.id)
    ).one()

    return ContaMaeAdminRead(
        id=conta.id,
        produto_id=conta.produto_id,
        login=conta.login,
        max_slots=conta.max_slots,
        slots_ocupados=conta.slots_ocupados,
        is_ativo=conta.is_ativo,
        data_expiracao=conta.data_expiracao,
        dias_restantes=dias_restantes,
        total_convites=total_convites,
    )


@router.delete("/{conta_mae_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conta_mae(
    *,
    session: Session = Depends(get_session),
    conta_mae_id: uuid.UUID
):
    conta = session.get(ContaMae, conta_mae_id)
    if not conta:
        raise HTTPException(status_code=404, detail="Conta mÃ£e nÃ£o encontrada")

    try:
        session.delete(conta)
        session.commit()
    except Exception as e:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro de banco de dados ao deletar conta mÃ£e: {e}"
        )

    return


@router.post("/{conta_mae_id}/convites", response_model=ContaMaeConviteRead)
def add_convite_conta_mae(
    *,
    session: Session = Depends(get_session),
    conta_mae_id: uuid.UUID,
    convite_in: ContaMaeConviteCreate
):
    conta = session.get(ContaMae, conta_mae_id)
    if not conta:
        raise HTTPException(status_code=404, detail="Conta mÃ£e nÃ£o encontrada")

    email_cliente = convite_in.email_cliente.strip()
    if not email_cliente:
        raise HTTPException(status_code=400, detail="Email do cliente Ã© obrigatÃ³rio")

    existente = session.exec(
        select(ContaMaeConvite)
        .where(ContaMaeConvite.conta_mae_id == conta_mae_id)
        .where(ContaMaeConvite.email_cliente == email_cliente)
    ).first()
    if existente:
        raise HTTPException(status_code=409, detail="Email jÃ¡ cadastrado nesta conta mÃ£e")

    if conta.slots_ocupados >= conta.max_slots:
        raise HTTPException(status_code=409, detail="Conta mÃ£e sem slots disponÃ­veis.")

    convite = ContaMaeConvite(
        conta_mae_id=conta_mae_id,
        email_cliente=email_cliente,
    )
    conta.slots_ocupados += 1
    session.add(conta)
    session.add(convite)
    session.commit()
    session.refresh(convite)

    return ContaMaeConviteRead(
        id=convite.id,
        email_cliente=convite.email_cliente,
        criado_em=convite.criado_em,
        pedido_id=convite.pedido_id,
    )
