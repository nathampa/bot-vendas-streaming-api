import datetime
import uuid
from decimal import Decimal
from typing import List, Optional, Tuple

import mercadopago
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel import Session, select

from app.api.v1.deps import get_current_admin_user
from app.core.config import settings
from app.db.database import engine, get_session
from app.models.base import TipoStatusPagamento
from app.models.configuracao_models import TipoGatilhoAfiliado
from app.models.usuario_models import RecargaSaldo, Usuario
from app.schemas.recarga_schemas import (
    RecargaCreateRequest,
    RecargaCreateResponse,
    RecargaStatusResponse,
)
from app.schemas.usuario_schemas import RecargaAdminRead
from app.services.affiliate_service import processar_gatilho_afiliado
from app.services.asaas_service import AsaasGatewayError, AsaasService
from app.services.notification_service import escape_markdown_v2, send_telegram_message
from .usuarios import get_or_create_usuario

sdk = mercadopago.SDK(settings.MERCADOPAGO_ACCESS_TOKEN) if settings.MERCADOPAGO_ACCESS_TOKEN else None

router = APIRouter()
webhook_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(get_current_admin_user)])

ASAAS_GATEWAY = "ASAAS"
MERCADOPAGO_GATEWAY = "MERCADOPAGO"
ASAAS_FINAL_PAYMENT_EVENTS = {"PAYMENT_RECEIVED", "PAYMENT_CONFIRMED"}
ASAAS_FINAL_PAYMENT_STATUSES = {"RECEIVED", "CONFIRMED", "PAID"}
ASAAS_FAILURE_STATUSES = {"FAILED", "CANCELLED", "REFUNDED"}
ASAAS_MIN_PIX_VALUE = Decimal("5.00")


def _calcular_expira_em(criado_em: datetime.datetime) -> datetime.datetime:
    return criado_em + datetime.timedelta(minutes=settings.RECARGA_EXPIRACAO_MINUTOS)


def _resolver_gateway_ativo() -> str:
    gateway = (settings.PAYMENT_PROVIDER or MERCADOPAGO_GATEWAY).strip().upper()
    if gateway not in {ASAAS_GATEWAY, MERCADOPAGO_GATEWAY}:
        raise HTTPException(status_code=500, detail="Gateway de pagamento configurado é inválido.")
    return gateway



def _format_qr_code_base64(encoded_image: str) -> str:
    if not encoded_image:
        return ""
    if encoded_image.startswith("data:image"):
        return encoded_image
    return f"data:image/png;base64,{encoded_image}"


def _extract_asaas_header_token(request: Request) -> Optional[str]:
    return request.headers.get("asaas-access-token") or request.headers.get("Asaas-Access-Token")


def _extract_asaas_payment_identifier(payload: dict) -> str:
    payment = payload.get("payment") or {}
    payment_id = payment.get("id")
    if not payment_id:
        raise HTTPException(status_code=400, detail="Webhook do Asaas sem payment.id.")
    return str(payment_id)


def _notificar_usuario_recarga_aprovada(telegram_id: Optional[int], mensagem: str) -> None:
    if not telegram_id or not mensagem:
        return
    try:
        send_telegram_message(telegram_id=telegram_id, message_text=mensagem)
    except Exception as exc:
        print(f"ERRO (NÃO-CRÍTICO): Falha ao enviar notificação de recarga para {telegram_id}: {exc}")


def _creditar_recarga_paga(
    *,
    recarga: RecargaSaldo,
    pago_em: Optional[datetime.datetime] = None,
) -> Tuple[Optional[int], str, str]:
    telegram_id_para_notificar: Optional[int] = None
    mensagem_para_notificar = ""
    status = "pagamento_creditado_sucesso"

    with Session(engine) as session_tx:
        recarga_tx = session_tx.get(RecargaSaldo, recarga.id)
        if not recarga_tx:
            return None, "", "recarga_nao_encontrada"

        if recarga_tx.status_pagamento == TipoStatusPagamento.PAGO:
            return None, "", "ja_pago"

        recarga_tx.status_pagamento = TipoStatusPagamento.PAGO
        recarga_tx.pago_em = pago_em or datetime.datetime.utcnow()
        session_tx.add(recarga_tx)

        usuario = session_tx.get(Usuario, recarga_tx.usuario_id)
        if not usuario:
            session_tx.rollback()
            return None, "", "usuario_nao_encontrado"

        valor_creditado = Decimal(recarga_tx.valor_solicitado)
        valor_bonus = Decimal("0.00")
        if recarga_tx.bonus_cashback_percent:
            bonus_pc = Decimal(recarga_tx.bonus_cashback_percent)
            valor_bonus = (valor_creditado * (bonus_pc / Decimal("100"))).quantize(Decimal("0.01"))
            print(f"CASHBACK: Creditando bônus de R$ {valor_bonus} ({bonus_pc}%)")

        novo_saldo = Decimal(usuario.saldo_carteira) + valor_creditado + valor_bonus
        usuario.saldo_carteira = novo_saldo
        session_tx.add(usuario)

        telegram_id_para_notificar = usuario.telegram_id
        valor_f = escape_markdown_v2(f"{valor_creditado:.2f}")
        saldo_f = escape_markdown_v2(f"{novo_saldo:.2f}")
        mensagem_para_notificar = (
            f"✅ *Pagamento Aprovado*\n\n"
            f"O seu PIX no valor de *R$ {valor_f}* foi confirmado\\!\n\n"
        )
        if valor_bonus > 0:
            bonus_f = escape_markdown_v2(f"{valor_bonus:.2f}")
            mensagem_para_notificar += f"🎉 *Bônus de Indicação:* + R$ {bonus_f}\n"
        mensagem_para_notificar += f"O seu novo saldo é: *R$ {saldo_f}*"

        processar_gatilho_afiliado(
            db=session_tx,
            usuario_indicado=usuario,
            valor_evento=recarga_tx.valor_solicitado,
            gatilho=TipoGatilhoAfiliado.primeira_recarga,
        )

        session_tx.commit()
        print(f"SUCESSO: Saldo de {valor_creditado} creditado ao usuário {usuario.id}")

    return telegram_id_para_notificar, mensagem_para_notificar, status


def _conciliar_recarga_asaas(session: Session, recarga: RecargaSaldo) -> RecargaSaldo:
    if recarga.gateway != ASAAS_GATEWAY or recarga.status_pagamento != TipoStatusPagamento.PENDENTE:
        return recarga

    try:
        service = AsaasService()
        payment = service.get_payment(recarga.gateway_id)
        payment_status = str(payment.get("status") or "").upper()
        if payment_status in ASAAS_FINAL_PAYMENT_STATUSES:
            telegram_id, mensagem, status_credito = _creditar_recarga_paga(recarga=recarga)
            if status_credito == "pagamento_creditado_sucesso":
                _notificar_usuario_recarga_aprovada(telegram_id, mensagem)
            with Session(engine) as verify_session:
                recarga_atualizada = verify_session.get(RecargaSaldo, recarga.id)
                if recarga_atualizada:
                    return recarga_atualizada
        elif payment_status in ASAAS_FAILURE_STATUSES:
            recarga.status_pagamento = TipoStatusPagamento.FALHOU
            session.add(recarga)
            session.commit()
            session.refresh(recarga)
    except AsaasGatewayError as exc:
        print(f"ERRO ao conciliar recarga {recarga.id} no Asaas: {exc.message}")
    except Exception as exc:
        print(f"ERRO inesperado ao conciliar recarga {recarga.id} no Asaas: {exc}")
    return recarga


def _expirar_recarga(session: Session, recarga: RecargaSaldo) -> None:
    if recarga.status_pagamento != TipoStatusPagamento.PENDENTE:
        return
    if recarga.gateway == ASAAS_GATEWAY and recarga.gateway_id:
        try:
            AsaasService().delete_payment(recarga.gateway_id)
        except Exception as exc:
            print(f"Aviso: falha ao cancelar cobrança Asaas {recarga.gateway_id}: {exc}")
    recarga.status_pagamento = TipoStatusPagamento.FALHOU
    session.add(recarga)


def _criar_pagamento_mercadopago(usuario: Usuario, valor: Decimal) -> Tuple[str, str, str]:
    if not sdk:
        raise HTTPException(status_code=503, detail="Mercado Pago não configurado.")

    payment_data = {
        "transaction_amount": float(valor),
        "description": f"Recarga de saldo Ferreira Streamings (ID: {usuario.id})",
        "payment_method_id": "pix",
        "payer": {
            "email": f"user_{usuario.telegram_id}@ferreirastreamings.com",
            "first_name": usuario.nome_completo,
        },
        "notification_url": "http://api.ferreirastreamings.com.br/api/v1/webhook/recarga",
    }

    try:
        print("API: A contactar Mercado Pago para criar PIX...")
        payment_response = sdk.payment().create(payment_data)
        if payment_response["status"] != 201:
            print(f"Erro do Mercado Pago: {payment_response}")
            raise HTTPException(status_code=500, detail="Erro ao gerar PIX no gateway.")

        payment_info = payment_response["response"]
        gateway_id_real = str(payment_info["id"])
        pix_copia_e_cola_real = payment_info["point_of_interaction"]["transaction_data"]["qr_code"]
        pix_qr_code_base64_real = payment_info["point_of_interaction"]["transaction_data"]["qr_code_base64"]
        print(f"API: PIX criado no MP com ID: {gateway_id_real}")
        return gateway_id_real, pix_copia_e_cola_real, f"data:image/png;base64,{pix_qr_code_base64_real}"
    except HTTPException:
        raise
    except Exception as exc:
        print(f"ERRO CRÍTICO na API do Mercado Pago: {exc}")
        raise HTTPException(status_code=503, detail=f"Serviço de pagamento indisponível: {exc}")


def _criar_pagamento_asaas(*, session: Session, usuario: Usuario, valor: Decimal, recarga_id: uuid.UUID) -> Tuple[str, str, str]:
    try:
        service = AsaasService()
        if not usuario.cpf_cnpj:
            raise HTTPException(status_code=400, detail="CPF_CNPJ_REQUIRED")

        email_pagador = usuario.email or f"user_{usuario.telegram_id}@ferreirastreamings.com"
        customer_id = service.ensure_customer(
            nome=usuario.nome_completo,
            email=email_pagador,
            external_reference=str(usuario.id),
            cpf_cnpj=usuario.cpf_cnpj,
            existing_customer_id=usuario.asaas_customer_id,
        )
        if usuario.asaas_customer_id != customer_id:
            usuario.asaas_customer_id = customer_id
            session.add(usuario)

        due_date = datetime.datetime.utcnow().date()
        payment = service.create_pix_payment(
            customer_id=customer_id,
            value=valor,
            due_date=due_date,
            description=f"Recarga de saldo Ferreira Streamings (ID: {usuario.id})",
            external_reference=str(recarga_id),
        )
        payment_id = payment.get("id")
        if not payment_id:
            raise AsaasGatewayError("Asaas não retornou o ID da cobrança.", payload=payment)

        qr_code = service.get_pix_qr_code(str(payment_id))
        payload = qr_code.get("payload")
        encoded_image = qr_code.get("encodedImage")
        if not payload or not encoded_image:
            raise AsaasGatewayError("Asaas não retornou o QR Code PIX completo.", payload=qr_code)

        print(f"API: PIX criado no Asaas com ID: {payment_id}")
        return str(payment_id), str(payload), _format_qr_code_base64(str(encoded_image))
    except AsaasGatewayError as exc:
        print(f"ERRO CRÍTICO na API do Asaas: {exc.message}")
        raise HTTPException(status_code=503, detail=f"Serviço de pagamento indisponível: {exc.message}")


@admin_router.get("/", response_model=List[RecargaAdminRead])
def get_admin_recargas(*, session: Session = Depends(get_session)):
    """
    [ADMIN] Lista as 50 últimas recargas (pagas ou pendentes).
    """
    stmt = (
        select(RecargaSaldo, Usuario.telegram_id, Usuario.nome_completo)
        .join(Usuario, RecargaSaldo.usuario_id == Usuario.id)
        .order_by(RecargaSaldo.criado_em.desc())
        .limit(50)
    )
    resultados = session.exec(stmt).all()
    return [
        RecargaAdminRead(
            id=recarga.id,
            valor_solicitado=recarga.valor_solicitado,
            status_pagamento=recarga.status_pagamento,
            gateway_id=recarga.gateway_id,
            criado_em=recarga.criado_em,
            pago_em=recarga.pago_em,
            usuario_telegram_id=tid,
            usuario_nome_completo=nome,
        )
        for recarga, tid, nome in resultados
    ]


@router.get("/{recarga_id}", response_model=RecargaStatusResponse)
def get_status_recarga(*, session: Session = Depends(get_session), recarga_id: uuid.UUID):
    """
    [BOT] Consulta o status de uma recarga e expira se passou do prazo.
    """
    recarga = session.get(RecargaSaldo, recarga_id)
    if not recarga:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recarga nao encontrada.")

    agora = datetime.datetime.utcnow()
    expira_em = _calcular_expira_em(recarga.criado_em)
    expirou = agora >= expira_em

    if recarga.status_pagamento == TipoStatusPagamento.PENDENTE and not expirou:
        recarga = _conciliar_recarga_asaas(session, recarga)

    if recarga.status_pagamento == TipoStatusPagamento.PENDENTE and expirou:
        _expirar_recarga(session, recarga)
        session.commit()
        session.refresh(recarga)

    expirado = recarga.status_pagamento == TipoStatusPagamento.FALHOU and expirou

    return RecargaStatusResponse(
        recarga_id=recarga.id,
        status_pagamento=recarga.status_pagamento,
        expirado=expirado,
        expiracao_minutos=settings.RECARGA_EXPIRACAO_MINUTOS,
        expira_em=expira_em,
    )


@router.post("/", response_model=RecargaCreateResponse)
def create_pedido_de_recarga(*, session: Session = Depends(get_session), recarga_in: RecargaCreateRequest):
    """
    [BOT] Cria um novo pedido de recarga (PIX) para um usuário.
    """
    if recarga_in.valor <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="O valor da recarga deve ser positivo.")

    if _resolver_gateway_ativo() == ASAAS_GATEWAY and Decimal(recarga_in.valor) < ASAAS_MIN_PIX_VALUE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"O valor mínimo para recarga via PIX é R$ {ASAAS_MIN_PIX_VALUE:.2f}.",
        )

    usuario = get_or_create_usuario(
        session=session,
        telegram_id=recarga_in.telegram_id,
        nome_completo=recarga_in.nome_completo,
    )

    expiracao_limite = datetime.datetime.utcnow() - datetime.timedelta(minutes=settings.RECARGA_EXPIRACAO_MINUTOS)
    recargas_expiradas = session.exec(
        select(RecargaSaldo).where(
            RecargaSaldo.usuario_id == usuario.id,
            RecargaSaldo.status_pagamento == TipoStatusPagamento.PENDENTE,
            RecargaSaldo.criado_em <= expiracao_limite,
        )
    ).all()
    for recarga in recargas_expiradas:
        _expirar_recarga(session, recarga)

    bonus_percent_aplicado = None
    if usuario.pending_cashback_percent:
        bonus_percent_aplicado = usuario.pending_cashback_percent
        usuario.pending_cashback_percent = None
        session.add(usuario)
        print(f"CASHBACK: Aplicando bônus de {bonus_percent_aplicado}% para recarga do usuário {usuario.telegram_id}")

    gateway_ativo = _resolver_gateway_ativo()
    recarga_id = uuid.uuid4()

    if gateway_ativo == ASAAS_GATEWAY:
        gateway_id_real, pix_copia_e_cola_real, pix_qr_code_base64_real = _criar_pagamento_asaas(
            session=session,
            usuario=usuario,
            valor=recarga_in.valor,
            recarga_id=recarga_id,
        )
    else:
        gateway_id_real, pix_copia_e_cola_real, pix_qr_code_base64_real = _criar_pagamento_mercadopago(
            usuario=usuario,
            valor=recarga_in.valor,
        )

    nova_recarga = RecargaSaldo(
        id=recarga_id,
        usuario_id=usuario.id,
        valor_solicitado=recarga_in.valor,
        status_pagamento=TipoStatusPagamento.PENDENTE,
        gateway=gateway_ativo,
        gateway_id=gateway_id_real,
        pix_copia_e_cola=pix_copia_e_cola_real,
        bonus_cashback_percent=bonus_percent_aplicado,
    )

    session.add(nova_recarga)
    session.commit()
    session.refresh(nova_recarga)

    expira_em = _calcular_expira_em(nova_recarga.criado_em)
    return RecargaCreateResponse(
        recarga_id=nova_recarga.id,
        status_pagamento=nova_recarga.status_pagamento,
        valor_solicitado=nova_recarga.valor_solicitado,
        pix_copia_e_cola=pix_copia_e_cola_real,
        pix_qr_code_base64=pix_qr_code_base64_real,
        expiracao_minutos=settings.RECARGA_EXPIRACAO_MINUTOS,
        expira_em=expira_em,
    )


@webhook_router.post("/recarga")
async def webhook_confirmacao_recarga(*, request: Request, session: Session = Depends(get_session)):
    """
    [WEBHOOK] Endpoint para confirmação de pagamento.
    Compatível com Asaas e Mercado Pago durante a migração.
    """
    data = await request.json()
    print(f"Webhook de recarga recebido: {data}")

    if data.get("event"):
        token_configurado = settings.ASAAS_WEBHOOK_AUTH_TOKEN
        if token_configurado:
            token_recebido = _extract_asaas_header_token(request)
            if token_recebido != token_configurado:
                raise HTTPException(status_code=401, detail="Token do webhook Asaas inválido.")

        event = str(data.get("event") or "").upper()
        if event not in ASAAS_FINAL_PAYMENT_EVENTS:
            return {"status": "ignorado"}

        gateway_id_real = _extract_asaas_payment_identifier(data)
        recarga = session.exec(
            select(RecargaSaldo).where(
                RecargaSaldo.gateway == ASAAS_GATEWAY,
                RecargaSaldo.gateway_id == gateway_id_real,
            )
        ).first()
        if not recarga:
            print(f"Erro: Pagamento Asaas {gateway_id_real} aprovado, mas não encontrado no nosso banco.")
            return {"status": "recarga_nao_encontrada"}

        telegram_id, mensagem, status_credito = _creditar_recarga_paga(
            recarga=recarga,
            pago_em=datetime.datetime.utcnow(),
        )
        if status_credito == "pagamento_creditado_sucesso":
            _notificar_usuario_recarga_aprovada(telegram_id, mensagem)
        return {"status": status_credito}

    if data.get("type") == "payment" and data.get("action") == "payment.updated":
        if not sdk:
            return {"status": "mercadopago_nao_configurado"}

        try:
            gateway_id_real = str(data["data"]["id"])
            print(f"A processar atualização para o payment_id: {gateway_id_real}")
            payment_info = sdk.payment().get(gateway_id_real)
            if payment_info["status"] != 200:
                print(f"Erro: Não foi possível buscar dados do payment_id {gateway_id_real} no MP")
                raise HTTPException(status_code=404, detail="Pagamento não encontrado no gateway.")

            payment_status = payment_info["response"]["status"]
            if payment_status != "approved":
                print(f"Pagamento {gateway_id_real} não está 'approved'. Status: {payment_status}")
                return {"status": f"pagamento_{payment_status}"}

            recarga = session.exec(
                select(RecargaSaldo).where(
                    RecargaSaldo.gateway == MERCADOPAGO_GATEWAY,
                    RecargaSaldo.gateway_id == gateway_id_real,
                )
            ).first()
            if not recarga:
                print(f"Erro: Pagamento {gateway_id_real} aprovado, mas não encontrado no nosso banco.")
                return {"status": "recarga_nao_encontrada"}

            telegram_id, mensagem, status_credito = _creditar_recarga_paga(
                recarga=recarga,
                pago_em=datetime.datetime.utcnow(),
            )
            if status_credito == "pagamento_creditado_sucesso":
                _notificar_usuario_recarga_aprovada(telegram_id, mensagem)
            return {"status": status_credito}
        except Exception as exc:
            print(f"ERRO CRÍTICO no processamento do webhook Mercado Pago: {exc}")
            return {"status": "erro_interno"}

    return {"status": "ignorado"}
