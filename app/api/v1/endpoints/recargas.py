import uuid
import datetime

import mercadopago
from app.core.config import settings
# SDK do Mercado Pago
sdk = mercadopago.SDK(settings.MERCADOPAGO_ACCESS_TOKEN)

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlmodel import Session, select
from typing import List
from app.models.base import TipoStatusPagamento
from .usuarios import get_or_create_usuario
from app.api.v1.deps import get_current_admin_user
from app.schemas.usuario_schemas import RecargaAdminRead
from app.services.affiliate_service import processar_gatilho_afiliado
from app.models.configuracao_models import TipoGatilhoAfiliado

from app.db.database import get_session, engine
from app.models.usuario_models import Usuario, RecargaSaldo
from app.schemas.recarga_schemas import (
    RecargaCreateRequest, 
    RecargaCreateResponse,
    WebhookRecargaRequest,
    WebhookRecargaResponse
)
from app.models.base import TipoStatusPagamento # Importa nosso ENUM
from app.services.notification_service import send_telegram_message, escape_markdown_v2
from decimal import Decimal

# Roteador para Recargas
router = APIRouter()

# Roteador para Webhooks (usado por gateways externos)
webhook_router = APIRouter()

# Router de recargas
admin_router = APIRouter(dependencies=[Depends(get_current_admin_user)])

@admin_router.get("/", response_model=List[RecargaAdminRead])
def get_admin_recargas(
    *,
    session: Session = Depends(get_session)
):
    """
    [ADMIN] Lista as 50 últimas recargas (pagas ou pendentes).
    """
    stmt = (
        select(
            RecargaSaldo,
            Usuario.telegram_id,
            Usuario.nome_completo
        )
        .join(Usuario, RecargaSaldo.usuario_id == Usuario.id)
        .order_by(RecargaSaldo.criado_em.desc())
        .limit(50)
    )
    
    resultados = session.exec(stmt).all()
    
    # Mapeia os resultados para o schema
    lista_recargas = [
        RecargaAdminRead(
            id=recarga.id,
            valor_solicitado=recarga.valor_solicitado,
            status_pagamento=recarga.status_pagamento,
            gateway_id=recarga.gateway_id,
            criado_em=recarga.criado_em,
            pago_em=recarga.pago_em,
            
            # Dados do JOIN
            usuario_telegram_id=tid,
            usuario_nome_completo=nome
        ) 
        for recarga, tid, nome in resultados
    ]
        
    return lista_recargas

@router.post("/", response_model=RecargaCreateResponse)
def create_pedido_de_recarga(
    *,
    session: Session = Depends(get_session),
    recarga_in: RecargaCreateRequest
):
    """
    [BOT] Cria um novo pedido de recarga (PIX) para um usuário.
    
    Irá encontrar ou criar o usuário baseado no telegram_id
    e então gerar um PIX de pagamento (simulado).
    """
    
    # 1. Validação de Valor
    if recarga_in.valor <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O valor da recarga deve ser positivo."
        )

    # 2. Encontra ou Cria o usuário no banco
    usuario = get_or_create_usuario(
        session=session,
        telegram_id=recarga_in.telegram_id,
        nome_completo=recarga_in.nome_completo
    )
    
    # Aplica o bônus de cashback pendente, se houver
    bonus_percent_aplicado = None
    if usuario.pending_cashback_percent:
        bonus_percent_aplicado = usuario.pending_cashback_percent
        
        # Zera o bônus pendente do usuário IMEDIATAMENTE
        # (para ele não gerar 2 PIX com bônus)
        usuario.pending_cashback_percent = None
        session.add(usuario)
        # Não damos commit ainda, faremos junto com a recarga
        
        print(f"CASHBACK: Aplicando bônus de {bonus_percent_aplicado}% para recarga do usuário {usuario.telegram_id}")

    # Define os dados do pagamento
    payment_data = {
        "transaction_amount": float(recarga_in.valor),
        "description": f"Recarga de saldo Ferreira Streamings (ID: {usuario.id})",
        "payment_method_id": "pix",
        "payer": {
            "email": f"user_{usuario.telegram_id}@ferreirastreamings.com", # Email fictício, mas obrigatório
            "first_name": usuario.nome_completo,
        },
        "notification_url": "http://177.11.152.132:8001/api/v1/webhook/recarga",
    }

    try:
        # 4. Faz a chamada real à API do Mercado Pago
        print("API: A contactar Mercado Pago para criar PIX...")
        payment_response = sdk.payment().create(payment_data)

        if payment_response["status"] != 201:
            # Se o MP falhar
            print(f"Erro do Mercado Pago: {payment_response}")
            raise HTTPException(status_code=500, detail="Erro ao gerar PIX no gateway.")

        payment_info = payment_response["response"]

        # 5. Extrai os dados do PIX (Copia e Cola / QR Code)
        gateway_id_real = str(payment_info["id"]) # ID do Pagamento (ex: 12345678)
        pix_copia_e_cola_real = payment_info["point_of_interaction"]["transaction_data"]["qr_code"]
        pix_qr_code_base64_real = payment_info["point_of_interaction"]["transaction_data"]["qr_code_base64"]

        print(f"API: PIX criado no MP com ID: {gateway_id_real}")

    except Exception as e:
        print(f"ERRO CRÍTICO na API do Mercado Pago: {e}")
        raise HTTPException(status_code=503, detail=f"Serviço de pagamento indisponível: {e}")

    # 4. Salva a transação PENDENTE no nosso banco
    nova_recarga = RecargaSaldo(
        usuario_id=usuario.id,
        valor_solicitado=recarga_in.valor,
        status_pagamento=TipoStatusPagamento.PENDENTE,
        gateway="MERCADOPAGO", # Agora é real
        gateway_id=gateway_id_real, # O ID real do MP
        pix_copia_e_cola=pix_copia_e_cola_real,
        bonus_cashback_percent=bonus_percent_aplicado
    )

    session.add(nova_recarga)
    session.commit()
    session.refresh(nova_recarga)
    
    # 5. Retorna os dados do PIX para o bot
    return RecargaCreateResponse(
        recarga_id=nova_recarga.id,
        status_pagamento=nova_recarga.status_pagamento,
        valor_solicitado=nova_recarga.valor_solicitado,
        pix_copia_e_cola=pix_copia_e_cola_real,
        pix_qr_code_base64=f"data:image/png;base64,{pix_qr_code_base64_real}"
    )

# --- 4. ENDPOINT NOVO (WEBHOOK DE CONFIRMAÇÃO) ---

@webhook_router.post(
    "/recarga", 
)
async def webhook_confirmacao_recarga_mp(
    *,
    request: Request,
    session: Session = Depends(get_session)
):
    """
    [WEBHOOK] Endpoint para o MERCADO PAGO confirmar um PIX.
    """
    
    data = await request.json()
    print(f"Webhook do Mercado Pago recebido: {data}")

    if data.get("type") != "payment" or data.get("action") != "payment.updated":
        print("Webhook ignorado (não é uma atualização de pagamento)")
        return {"status": "ignorado"}
        
    telegram_id_para_notificar = None
    mensagem_para_notificar = ""

    try:
        gateway_id_real = str(data["data"]["id"])
        print(f"A processar atualização para o payment_id: {gateway_id_real}")

        payment_info = sdk.payment().get(gateway_id_real)
        if payment_info["status"] != 200:
            print(f"Erro: Não foi possível buscar dados do payment_id {gateway_id_real} no MP")
            raise HTTPException(status_code=404, detail="Pagamento não encontrado no gateway.")

        payment_status = payment_info["response"]["status"]
        
        if payment_status == "approved":
            
            # --- TRANSAÇÃO DO BANCO ---
            # Envolvemos a lógica de banco em um 'with' separado
            # para garantir que ela seja concluída (commit) antes da notificação.
            
            with Session(engine) as session_tx:
                recarga = session_tx.exec(
                    select(RecargaSaldo).where(
                        RecargaSaldo.gateway_id == gateway_id_real
                    )
                ).first()
                
                if not recarga:
                    print(f"Erro: Pagamento {gateway_id_real} aprovado, mas não encontrado no nosso banco.")
                    return {"status": "recarga_nao_encontrada"}
                
                if recarga.status_pagamento == TipoStatusPagamento.PAGO:
                    print(f"Aviso: Recarga {recarga.id} já estava paga.")
                    return {"status": "ja_pago"}

                recarga.status_pagamento = TipoStatusPagamento.PAGO
                recarga.pago_em = datetime.datetime.utcnow()
                session_tx.add(recarga)
                
                usuario = session_tx.get(Usuario, recarga.usuario_id)
                if not usuario:
                    print(f"ERRO CRÍTICO: Usuário {recarga.usuario_id} não encontrado para creditar o saldo.")
                    session_tx.rollback()
                    return {"status": "usuario_nao_encontrado"}

                # Calcula o valor a ser creditado (incluindo bônus, se houver)
                valor_creditado = recarga.valor_solicitado
                valor_bonus = Decimal("0.0")
                
                # Verifica se esta recarga tinha um bônus
                if recarga.bonus_cashback_percent:
                    bonus_pc = Decimal(recarga.bonus_cashback_percent)
                    valor_bonus = (valor_creditado * (bonus_pc / 100)).quantize(Decimal("0.01"))
                    print(f"CASHBACK: Creditando bônus de R$ {valor_bonus} ({bonus_pc}%)")
                
                # Soma o valor + bônus
                novo_saldo = usuario.saldo_carteira + valor_creditado + valor_bonus
                
                usuario.saldo_carteira = novo_saldo
                session_tx.add(usuario)
                
                # --- Prepara os dados para a notificação ---
                # Nós preparamos as variáveis ANTES do commit
                telegram_id_para_notificar = usuario.telegram_id
                valor_f = escape_markdown_v2(f"{valor_creditado:.2f}")
                saldo_f = escape_markdown_v2(f"{novo_saldo:.2f}")
                
                mensagem_para_notificar = (
                    f"✅ *Pagamento Aprovado*\n\n"
                    f"O seu PIX no valor de *R$ {valor_f}* foi confirmado\\!\n\n"
                )
                
                if valor_bonus > 0:
                    bonus_f = escape_markdown_v2(f"{valor_bonus:.2f}")
                    mensagem_para_notificar += (
                        f"🎉 *Bônus de Indicação:* + R$ {bonus_f}\n"
                    )
                
                mensagem_para_notificar += (
                    f"O seu novo saldo é: *R$ {saldo_f}*"
                )

                processar_gatilho_afiliado(
                    db=session_tx,
                    usuario_indicado=usuario,
                    valor_evento=recarga.valor_solicitado,
                    gatilho=TipoGatilhoAfiliado.primeira_recarga
                )
                
                # --- Commit da transação ---
                session_tx.commit()
                print(f"SUCESSO: Saldo de {valor_creditado} creditado ao usuário {usuario.id}")
            
            # --- FIM DA TRANSAÇÃO DO BANCO ---

            # --- ENVIO DA NOTIFICAÇÃO ---
            # Esta parte agora está FORA do 'try/except' principal.
            # Se a notificação falhar, ela não causará um ROLLBACK.
            if telegram_id_para_notificar and mensagem_para_notificar:
                try:
                    send_telegram_message(
                        telegram_id=telegram_id_para_notificar,
                        message_text=mensagem_para_notificar
                    )
                except Exception as e_notify:
                    print(f"ERRO (NÃO-CRÍTICO): Falha ao enviar notificação de recarga para {telegram_id_para_notificar}: {e_notify}")
            
            return {"status": "pagamento_creditado_sucesso"}
        
        else:
            print(f"Pagamento {gateway_id_real} não está 'approved'. Status: {payment_status}")
            return {"status": f"pagamento_{payment_status}"}

    except Exception as e:
        # Este 'except' agora só pega erros ANTES do commit
        print(f"ERRO CRÍTICO no processamento do webhook: {e}")
        # session.rollback() # O 'with Session' já faz o rollback automático
        return {"status": "erro_interno"}