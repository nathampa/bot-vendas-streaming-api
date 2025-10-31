import uuid
import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from typing import List

from app.db.database import get_session
from app.models.usuario_models import Usuario, RecargaSaldo
from app.schemas.recarga_schemas import (
    RecargaCreateRequest, 
    RecargaCreateResponse,
    WebhookRecargaRequest,
    WebhookRecargaResponse
)
from app.models.base import TipoStatusPagamento # Importa nosso ENUM

# Roteador para Recargas
router = APIRouter()

# Roteador para Webhooks (usado por gateways externos)
webhook_router = APIRouter()

# --- Função Auxiliar (Helper) ---
def get_or_create_usuario(session: Session, telegram_id: int, nome_completo: str) -> Usuario:
    """
    Tenta encontrar um usuário pelo telegram_id.
    Se não encontrar, cria um novo usuário.
    """
    
    # 1. Tenta encontrar o usuário
    usuario = session.exec(
        select(Usuario).where(Usuario.telegram_id == telegram_id)
    ).first()
    
    if usuario:
        # Se encontrou, apenas retorna o usuário
        return usuario
    
    # 2. Se não encontrou, cria um novo
    print(f"Usuário com telegram_id {telegram_id} não encontrado. Criando novo usuário.")
    novo_usuario = Usuario(
        telegram_id=telegram_id,
        nome_completo=nome_completo
        # Saldo, is_admin, etc., já têm valores padrão no model
    )
    session.add(novo_usuario)
    session.commit()
    session.refresh(novo_usuario)
    return novo_usuario
# --- Fim da Função Auxiliar ---


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
    
    # 3. ========== TODO: Integração Real com Gateway de Pagamento ==========
    #    Neste ponto, faríamos uma chamada HTTP para o Mercado Pago, Asaas, etc.
    #    ex: gateway_response = mercadopago.create_payment(recarga_in.valor, usuario.id)
    #    Mas, por enquanto, vamos "mockar" (simular) a resposta.
    # ======================================================================
    
    # 4. Simulação (Mock) da resposta do Gateway
    gateway_id_mock = f"MOCK_PIX_{uuid.uuid4()}"
    pix_copia_e_cola_mock = "00020126330014br.gov.bcb.pix0111+55119... (PIX MOCKADO)"
    # Um QR Code de 1x1 pixel, apenas para teste
    pix_qr_code_base64_mock = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="

    # 5. Salva a transação PENDENTE no nosso banco
    nova_recarga = RecargaSaldo(
        usuario_id=usuario.id,
        valor_solicitado=recarga_in.valor,
        status_pagamento=TipoStatusPagamento.PENDENTE,
        gateway="MOCK_GATEWAY", # Para sabermos que é um teste
        gateway_id=gateway_id_mock,
        pix_copia_e_cola=pix_copia_e_cola_mock
    )
    
    session.add(nova_recarga)
    session.commit()
    session.refresh(nova_recarga)
    
    # 6. Retorna os dados do PIX para o bot
    return RecargaCreateResponse(
        recarga_id=nova_recarga.id,
        status_pagamento=nova_recarga.status_pagamento,
        valor_solicitado=nova_recarga.valor_solicitado,
        pix_copia_e_cola=pix_copia_e_cola_mock,
        pix_qr_code_base64=pix_qr_code_base64_mock
    )

# --- 4. ENDPOINT NOVO (WEBHOOK DE CONFIRMAÇÃO) ---

@webhook_router.post(
    "/recarga", 
    response_model=WebhookRecargaResponse
)
def webhook_confirmacao_recarga(
    *,
    session: Session = Depends(get_session),
    webhook_in: WebhookRecargaRequest
):
    """
    [WEBHOOK] Endpoint para o gateway de pagamento (simulado)
    confirmar que um PIX foi pago.
    
    Isto irá mudar o status da recarga para 'PAGO' e
    adicionar o saldo à carteira do usuário.
    """
    
    # TODO: Na vida real, validar a assinatura do webhook aqui.
    
    print(f"Webhook recebido para o gateway_id: {webhook_in.gateway_id}")
    
    # 1. Encontra a recarga pendente (usando o gateway_id)
    recarga = session.exec(
        select(RecargaSaldo).where(
            RecargaSaldo.gateway_id == webhook_in.gateway_id
        )
    ).first()
    
    if not recarga:
        print("ERRO: Webhook para gateway_id não encontrado.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recarga não encontrada para este ID de gateway."
        )
    
    # 2. Verifica se já foi paga (Idempotência)
    if recarga.status_pagamento == TipoStatusPagamento.PAGO:
        print("Aviso: Webhook recebido para recarga que já estava paga.")
        usuario = session.get(Usuario, recarga.usuario_id)
        return WebhookRecargaResponse(
            status="JA_PAGO",
            recarga_id=recarga.id,
            novo_saldo_usuario=usuario.saldo_carteira
        )

    # 3. Transação Principal: Atualiza a recarga e o saldo do usuário
    try:
        # a. Atualiza a recarga para PAGO
        recarga.status_pagamento = TipoStatusPagamento.PAGO
        recarga.pago_em = datetime.datetime.utcnow()
        session.add(recarga)
        
        # b. Encontra o usuário
        usuario = session.get(Usuario, recarga.usuario_id)
        if not usuario:
            raise HTTPException(status_code=500, detail="Usuário da recarga não encontrado.")
        
        # c. Credita o saldo na carteira
        usuario.saldo_carteira = usuario.saldo_carteira + recarga.valor_solicitado
        session.add(usuario)
        
        # d. Commita a transação
        session.commit()
        session.refresh(recarga)
        session.refresh(usuario)
        
        print(f"Sucesso: Saldo de {recarga.valor_solicitado} adicionado ao usuário {usuario.id}")
        
        # TODO: Enviar notificação para o bot/usuário informando do saldo.
        
        return WebhookRecargaResponse(
            status="PAGO_COM_SUCESSO",
            recarga_id=recarga.id,
            novo_saldo_usuario=usuario.saldo_carteira
        )
        
    except Exception as e:
        print(f"ERRO CRÍTICO na transação do webhook: {e}")
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro interno ao processar pagamento: {e}"
        )