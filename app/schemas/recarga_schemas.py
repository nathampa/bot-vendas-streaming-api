import uuid
from decimal import Decimal
from sqlmodel import SQLModel
from app.models.base import TipoStatusPagamento # Importa nosso ENUM

# -----------------------------------------------------------------
# Schema de REQUEST (O que o bot envia para a API)
# -----------------------------------------------------------------
class RecargaCreateRequest(SQLModel):
    telegram_id: int
    nome_completo: str # Para a API poder criar o usuário se ele for novo
    valor: Decimal # O valor (ex: 20.00) que o usuário quer adicionar

# -----------------------------------------------------------------
# Schema de RESPONSE (O que a API retorna para o bot)
# -----------------------------------------------------------------
class RecargaCreateResponse(SQLModel):
    recarga_id: uuid.UUID # O ID da nossa transação interna
    status_pagamento: TipoStatusPagamento
    valor_solicitado: Decimal
    pix_copia_e_cola: str # O código que o bot mostrará para o usuário
    pix_qr_code_base64: str # A imagem do QR Code que o bot mostrará

# -----------------------------------------------------------------
# Schema de REQUEST (O que o Gateway de Pagamento (simulado) nos envia)
# -----------------------------------------------------------------
class WebhookRecargaRequest(SQLModel):
    # Na vida real, o gateway pode enviar um objeto complexo.
    # Para o nosso mock, só precisamos do ID da transação que gerámos.
    gateway_id: str

# -----------------------------------------------------------------
# Schema de RESPONSE (O que respondemos ao Gateway)
# -----------------------------------------------------------------
class WebhookRecargaResponse(SQLModel):
    status: str
    recarga_id: uuid.UUID
    novo_saldo_usuario: Decimal