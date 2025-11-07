import uuid
from decimal import Decimal
from sqlmodel import SQLModel
from typing import Optional
import datetime
from app.models.base import TipoStatusPagamento

# -----------------------------------------------------------------
# Schema de REQUEST (O que o bot envia para registar um user)
# -----------------------------------------------------------------
class UsuarioRegisterRequest(SQLModel):
    telegram_id: int
    nome_completo: str

# -----------------------------------------------------------------
# Schema de RESPONSE (O que a API retorna)
# -----------------------------------------------------------------
class UsuarioRead(SQLModel):
    id: uuid.UUID
    telegram_id: int
    nome_completo: str
    saldo_carteira: Decimal
    is_admin: bool

# -----------------------------------------------------------------
# Schema de RESPONSE (O que a API retorna para o histórico do bot)
# -----------------------------------------------------------------
class UsuarioPedidoRead(SQLModel):
    pedido_id: uuid.UUID
    produto_nome: str
    valor_pago: Decimal
    data_compra: datetime.datetime

# Schema para a lista de usuários no painel
class UsuarioAdminRead(SQLModel):
    id: uuid.UUID
    telegram_id: int
    nome_completo: str
    saldo_carteira: Decimal
    criado_em: datetime.datetime
    total_pedidos: int = 0

# Schema para a lista de recargas no painel
class RecargaAdminRead(SQLModel):
    id: uuid.UUID
    valor_solicitado: Decimal
    status_pagamento: TipoStatusPagamento
    gateway_id: Optional[str]
    criado_em: datetime.datetime
    pago_em: Optional[datetime.datetime]
    
    # Dados do JOIN
    usuario_telegram_id: int
    usuario_nome_completo: str

class UsuarioCreate(UsuarioBase):
    telegram_id: int
    nome_completo: str
    referrer_id: Optional[int] = None # ID do Telegram de quem indicou