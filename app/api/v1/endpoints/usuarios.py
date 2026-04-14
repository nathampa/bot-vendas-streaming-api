import datetime
import re
import uuid
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, func
from sqlmodel import Session, select

from app.api.v1.deps import get_bot_api_key, get_current_admin_user
from app.db.database import get_session
from app.models.base import StatusEntregaPedido, TipoStatusPagamento
from app.models.pedido_models import Pedido
from app.models.produto_models import Produto
from app.models.usuario_models import AjusteSaldoUsuario, RecargaSaldo, Usuario
from app.schemas.usuario_schemas import (
    RecargaAdminRead,
    UsuarioAdminRead,
    UsuarioDocumentoUpdateRequest,
    UsuarioExpiracaoMarcarNotificadaRequest,
    UsuarioExpiracaoPendenteRead,
    UsuarioPedidoRead,
    UsuarioPerfilRead,
    UsuarioRead,
    UsuarioRegisterRequest,
    UsuarioSaldoAjusteRequest,
    UsuarioSaldoAjusteResponse,
    UsuarioSaldoHistoricoRead,
)
from app.services.pedido_expiracao_service import resolver_data_expiracao_pedido

router = APIRouter(dependencies=[Depends(get_bot_api_key)])
admin_router = APIRouter(dependencies=[Depends(get_current_admin_user)])
TWO_DECIMAL_PLACES = Decimal("0.01")


def _normalizar_documento(documento: str) -> str:
    return re.sub(r"\D", "", documento or "")


def _documento_invalido_por_repeticao(documento: str) -> bool:
    return not documento or documento == documento[0] * len(documento)


def _validar_cpf(cpf: str) -> bool:
    if len(cpf) != 11 or _documento_invalido_por_repeticao(cpf):
        return False

    soma = sum(int(cpf[i]) * (10 - i) for i in range(9))
    resto = (soma * 10) % 11
    digito_1 = 0 if resto == 10 else resto
    if digito_1 != int(cpf[9]):
        return False

    soma = sum(int(cpf[i]) * (11 - i) for i in range(10))
    resto = (soma * 10) % 11
    digito_2 = 0 if resto == 10 else resto
    return digito_2 == int(cpf[10])


def _validar_cnpj(cnpj: str) -> bool:
    if len(cnpj) != 14 or _documento_invalido_por_repeticao(cnpj):
        return False

    pesos_1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos_2 = [6] + pesos_1

    soma = sum(int(cnpj[i]) * pesos_1[i] for i in range(12))
    resto = soma % 11
    digito_1 = 0 if resto < 2 else 11 - resto
    if digito_1 != int(cnpj[12]):
        return False

    soma = sum(int(cnpj[i]) * pesos_2[i] for i in range(13))
    resto = soma % 11
    digito_2 = 0 if resto < 2 else 11 - resto
    return digito_2 == int(cnpj[13])


def _validar_cpf_cnpj(documento: str) -> str:
    documento_normalizado = _normalizar_documento(documento)
    if len(documento_normalizado) == 11 and _validar_cpf(documento_normalizado):
        return documento_normalizado
    if len(documento_normalizado) == 14 and _validar_cnpj(documento_normalizado):
        return documento_normalizado
    raise HTTPException(status_code=400, detail="CPF ou CNPJ inválido.")


# --- Função Auxiliar ---
def get_or_create_usuario(session: Session, telegram_id: int, nome_completo: str, referrer_id_telegram: Optional[int] = None) -> Usuario:
    usuario = session.exec(select(Usuario).where(Usuario.telegram_id == telegram_id)).first()

    if usuario:
        if usuario.nome_completo != nome_completo:
            usuario.nome_completo = nome_completo
            session.add(usuario)
            session.commit()
            session.refresh(usuario)
        return usuario

    print(f"Usuário com telegram_id {telegram_id} não encontrado. Criando novo usuário.")

    db_referrer: Optional[Usuario] = None
    if referrer_id_telegram:
        stmt_referrer = select(Usuario).where(Usuario.telegram_id == referrer_id_telegram)
        db_referrer = session.exec(stmt_referrer).first()
        if db_referrer:
            print(f"Usuário {telegram_id} foi indicado por {db_referrer.telegram_id} (UUID: {db_referrer.id})")
        else:
            print(f"Referrer com ID {referrer_id_telegram} não encontrado no banco.")

    novo_usuario = Usuario(
        telegram_id=telegram_id,
        nome_completo=nome_completo,
        referrer_id=db_referrer.id if db_referrer else None,
    )

    session.add(novo_usuario)
    session.commit()
    session.refresh(novo_usuario)
    return novo_usuario


@admin_router.get("/", response_model=list[UsuarioAdminRead])
def get_admin_usuarios(*, session: Session = Depends(get_session)):
    stmt = (
        select(
            Usuario.id,
            Usuario.telegram_id,
            Usuario.nome_completo,
            Usuario.saldo_carteira,
            Usuario.criado_em,
            func.count(Pedido.id).label("total_pedidos"),
        )
        .join(Pedido, Pedido.usuario_id == Usuario.id, isouter=True)
        .where(Usuario.is_admin == False)
        .group_by(Usuario.id)
        .order_by(Usuario.criado_em.desc())
    )

    resultados = session.exec(stmt).all()
    return [
        UsuarioAdminRead(
            id=u.id,
            telegram_id=u.telegram_id,
            nome_completo=u.nome_completo,
            saldo_carteira=u.saldo_carteira,
            criado_em=u.criado_em,
            total_pedidos=u.total_pedidos,
        )
        for u in resultados
    ]


@admin_router.post("/{usuario_id}/ajuste-saldo", response_model=UsuarioSaldoAjusteResponse)
def ajustar_saldo_usuario(
    *,
    usuario_id: uuid.UUID,
    ajuste: UsuarioSaldoAjusteRequest,
    session: Session = Depends(get_session),
    current_admin: Usuario = Depends(get_current_admin_user),
):
    usuario = session.exec(select(Usuario).where(Usuario.id == usuario_id, Usuario.is_admin == False)).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    valor_ajuste = ajuste.valor.quantize(TWO_DECIMAL_PLACES, rounding=ROUND_HALF_UP)
    saldo_anterior = Decimal(usuario.saldo_carteira).quantize(TWO_DECIMAL_PLACES, rounding=ROUND_HALF_UP)

    if ajuste.operacao in ("ADICIONAR", "REMOVER") and valor_ajuste <= 0:
        raise HTTPException(status_code=400, detail="O valor do ajuste precisa ser maior que zero para adicionar ou remover saldo.")
    if ajuste.operacao == "DEFINIR" and valor_ajuste < 0:
        raise HTTPException(status_code=400, detail="Não é permitido definir saldo negativo.")

    if ajuste.operacao == "ADICIONAR":
        saldo_atual = saldo_anterior + valor_ajuste
    elif ajuste.operacao == "REMOVER":
        if valor_ajuste > saldo_anterior:
            raise HTTPException(status_code=400, detail=f"Saldo insuficiente para remoção. Saldo atual: R$ {saldo_anterior:.2f}")
        saldo_atual = saldo_anterior - valor_ajuste
    else:
        saldo_atual = valor_ajuste

    saldo_atual = saldo_atual.quantize(TWO_DECIMAL_PLACES, rounding=ROUND_HALF_UP)
    usuario.saldo_carteira = saldo_atual
    motivo = ajuste.motivo.strip() if ajuste.motivo and ajuste.motivo.strip() else None

    historico = AjusteSaldoUsuario(
        operacao=ajuste.operacao,
        valor=valor_ajuste,
        saldo_anterior=saldo_anterior,
        saldo_atual=saldo_atual,
        motivo=motivo,
        usuario_id=usuario.id,
        admin_id=current_admin.id,
    )
    session.add(usuario)
    session.add(historico)
    session.commit()

    return UsuarioSaldoAjusteResponse(
        usuario_id=usuario.id,
        operacao=ajuste.operacao,
        valor=valor_ajuste,
        saldo_anterior=saldo_anterior,
        saldo_atual=saldo_atual,
        motivo=motivo,
        ajustado_em=datetime.datetime.utcnow(),
    )


@admin_router.get("/{usuario_id}/historico-saldo", response_model=list[UsuarioSaldoHistoricoRead])
def get_historico_ajustes_saldo_usuario(*, usuario_id: uuid.UUID, limite: int = 20, session: Session = Depends(get_session)):
    if limite < 1:
        raise HTTPException(status_code=400, detail="O limite precisa ser maior ou igual a 1.")
    if limite > 200:
        raise HTTPException(status_code=400, detail="O limite máximo permitido é 200.")

    usuario = session.exec(select(Usuario).where(Usuario.id == usuario_id, Usuario.is_admin == False)).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    stmt = (
        select(
            AjusteSaldoUsuario.id,
            AjusteSaldoUsuario.operacao,
            AjusteSaldoUsuario.valor,
            AjusteSaldoUsuario.saldo_anterior,
            AjusteSaldoUsuario.saldo_atual,
            AjusteSaldoUsuario.motivo,
            AjusteSaldoUsuario.criado_em,
            AjusteSaldoUsuario.admin_id,
            Usuario.nome_completo.label("admin_nome_completo"),
            Usuario.telegram_id.label("admin_telegram_id"),
        )
        .join(Usuario, Usuario.id == AjusteSaldoUsuario.admin_id)
        .where(AjusteSaldoUsuario.usuario_id == usuario_id)
        .order_by(desc(AjusteSaldoUsuario.criado_em))
        .limit(limite)
    )
    resultados = session.exec(stmt).all()
    return [
        UsuarioSaldoHistoricoRead(
            id=item.id,
            operacao=item.operacao,
            valor=item.valor,
            saldo_anterior=item.saldo_anterior,
            saldo_atual=item.saldo_atual,
            motivo=item.motivo,
            criado_em=item.criado_em,
            admin_id=item.admin_id,
            admin_nome_completo=item.admin_nome_completo,
            admin_telegram_id=item.admin_telegram_id,
        )
        for item in resultados
    ]


@router.post("/register", response_model=UsuarioRead)
def register_user(*, session: Session = Depends(get_session), user_in: UsuarioRegisterRequest):
    usuario = get_or_create_usuario(
        session=session,
        telegram_id=user_in.telegram_id,
        nome_completo=user_in.nome_completo,
        referrer_id_telegram=user_in.referrer_id,
    )
    return usuario


@router.put("/documento", response_model=UsuarioRead)
def update_user_documento(*, session: Session = Depends(get_session), documento_in: UsuarioDocumentoUpdateRequest):
    usuario = session.exec(select(Usuario).where(Usuario.telegram_id == documento_in.telegram_id)).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    documento_normalizado = _validar_cpf_cnpj(documento_in.cpf_cnpj)
    usuario_existente = session.exec(
        select(Usuario).where(Usuario.cpf_cnpj == documento_normalizado, Usuario.id != usuario.id)
    ).first()
    if usuario_existente:
        raise HTTPException(status_code=409, detail="CPF ou CNPJ já está em uso por outro usuário.")

    usuario.cpf_cnpj = documento_normalizado
    session.add(usuario)
    session.commit()
    session.refresh(usuario)
    return usuario


@router.get("/perfil", response_model=UsuarioPerfilRead)
def get_usuario_perfil(*, session: Session = Depends(get_session), telegram_id: int):
    usuario = session.exec(select(Usuario).where(Usuario.telegram_id == telegram_id)).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    total_recargas_pagas, total_valor_recarregado = session.exec(
        select(
            func.count(RecargaSaldo.id),
            func.coalesce(func.sum(RecargaSaldo.valor_solicitado), 0),
        ).where(
            RecargaSaldo.usuario_id == usuario.id,
            RecargaSaldo.status_pagamento == TipoStatusPagamento.PAGO,
        )
    ).one()

    total_compras, total_valor_gasto = session.exec(
        select(
            func.count(Pedido.id),
            func.coalesce(func.sum(Pedido.valor_pago), 0),
        ).where(Pedido.usuario_id == usuario.id)
    ).one()

    return UsuarioPerfilRead(
        id=usuario.id,
        telegram_id=usuario.telegram_id,
        nome_completo=usuario.nome_completo,
        saldo_carteira=usuario.saldo_carteira,
        criado_em=usuario.criado_em,
        total_recargas_pagas=int(total_recargas_pagas or 0),
        total_valor_recarregado=Decimal(total_valor_recarregado or 0).quantize(TWO_DECIMAL_PLACES, rounding=ROUND_HALF_UP),
        total_compras=int(total_compras or 0),
        total_valor_gasto=Decimal(total_valor_gasto or 0).quantize(TWO_DECIMAL_PLACES, rounding=ROUND_HALF_UP),
    )


@router.get("/meus-pedidos", response_model=list[UsuarioPedidoRead])
def get_meus_pedidos(*, session: Session = Depends(get_session), telegram_id: int):
    usuario = session.exec(select(Usuario).where(Usuario.telegram_id == telegram_id)).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    stmt = (
        select(
            Pedido.id,
            Produto.nome,
            Pedido.valor_pago,
            Pedido.criado_em,
            Pedido.email_cliente,
            Pedido.estoque_conta_id,
            Pedido.conta_mae_id,
        )
        .join(Produto, Produto.id == Pedido.produto_id)
        .where(Pedido.usuario_id == usuario.id)
        .order_by(Pedido.criado_em.desc())
        .limit(5)
    )

    resultados = session.exec(stmt).all()
    today = datetime.date.today()
    lista_pedidos: list[UsuarioPedidoRead] = []

    for (pid, pnome, vpago, data, email_cliente, estoque_conta_id, conta_mae_id) in resultados:
        data_expiracao, origem_expiracao = resolver_data_expiracao_pedido(
            session=session,
            pedido_id=pid,
            email_cliente=email_cliente,
            estoque_conta_id=estoque_conta_id,
            conta_mae_id=conta_mae_id,
        )

        dias_restantes = None
        conta_expirada = False
        if data_expiracao:
            dias_restantes = (data_expiracao - today).days
            conta_expirada = dias_restantes < 0

        lista_pedidos.append(
            UsuarioPedidoRead(
                pedido_id=pid,
                produto_nome=pnome,
                valor_pago=vpago,
                data_compra=data,
                data_expiracao=data_expiracao,
                dias_restantes=dias_restantes,
                conta_expirada=conta_expirada,
                origem_expiracao=origem_expiracao,
            )
        )

    return lista_pedidos


@router.get("/expiracoes-pendentes", response_model=list[UsuarioExpiracaoPendenteRead])
def get_expiracoes_pendentes(*, session: Session = Depends(get_session), limite: int = 200):
    if limite < 1:
        raise HTTPException(status_code=400, detail="O limite precisa ser maior ou igual a 1.")
    if limite > 500:
        raise HTTPException(status_code=400, detail="O limite máximo permitido é 500.")

    today = datetime.date.today()
    stmt = (
        select(
            Pedido.id,
            Usuario.telegram_id,
            Produto.nome,
            Pedido.email_cliente,
            Pedido.estoque_conta_id,
            Pedido.conta_mae_id,
        )
        .join(Usuario, Usuario.id == Pedido.usuario_id)
        .join(Produto, Produto.id == Pedido.produto_id)
        .where(Pedido.status_entrega == StatusEntregaPedido.ENTREGUE)
        .order_by(Pedido.criado_em.desc())
        .limit(limite)
    )

    resultados = session.exec(stmt).all()
    pendentes: list[UsuarioExpiracaoPendenteRead] = []
    for (pedido_id, telegram_id, produto_nome, email_cliente, estoque_conta_id, conta_mae_id) in resultados:
        data_expiracao, origem_expiracao = resolver_data_expiracao_pedido(
            session=session,
            pedido_id=pedido_id,
            email_cliente=email_cliente,
            estoque_conta_id=estoque_conta_id,
            conta_mae_id=conta_mae_id,
        )
        if not data_expiracao or data_expiracao != today:
            continue

        pedido = session.get(Pedido, pedido_id)
        if not pedido or pedido.ultima_data_expiracao_notificada == today:
            continue

        pendentes.append(
            UsuarioExpiracaoPendenteRead(
                pedido_id=pedido_id,
                telegram_id=telegram_id,
                produto_nome=produto_nome,
                data_expiracao=data_expiracao,
                origem_expiracao=origem_expiracao,
            )
        )

    return pendentes


@router.post("/expiracoes-pendentes/marcar-notificada", status_code=status.HTTP_204_NO_CONTENT)
def marcar_expiracao_notificada(
    *,
    session: Session = Depends(get_session),
    payload: UsuarioExpiracaoMarcarNotificadaRequest,
):
    pedido = session.get(Pedido, payload.pedido_id)
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido não encontrado.")

    pedido.ultima_data_expiracao_notificada = payload.data_expiracao
    session.add(pedido)
    session.commit()
    return None


@router.get("/ids")
def get_all_user_ids(*, session: Session = Depends(get_session)):
    resultados = session.exec(select(Usuario.telegram_id).where(Usuario.is_admin == False)).all()
    return {"telegram_ids": resultados}
