import uuid
from decimal import Decimal
from sqlmodel import SQLModel
from typing import Optional, Literal
import datetime
from app.models.base import TipoStatusPagamento

# -----------------------------------------------------------------
# Schema de REQUEST (O que o bot envia para registar um user)
# -----------------------------------------------------------------
class UsuarioRegisterRequest(SQLModel):
    telegram_id: int
    nome_completo: str
    referrer_id: Optional[int] = None

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
    data_expiracao: Optional[datetime.date] = None
    dias_restantes: Optional[int] = None
    conta_expirada: bool = False
    origem_expiracao: Optional[Literal["ESTOQUE", "CONTA_MAE"]] = None

# Schema para a lista de usuários no painel
class UsuarioAdminRead(SQLModel):
    id: uuid.UUID
    telegram_id: int
    nome_completo: str
    saldo_carteira: Decimal
    criado_em: datetime.datetime
    total_pedidos: int = 0

class UsuarioSaldoAjusteRequest(SQLModel):
    operacao: Literal["ADICIONAR", "REMOVER", "DEFINIR"]
    valor: Decimal
    motivo: Optional[str] = None

class UsuarioSaldoAjusteResponse(SQLModel):
    usuario_id: uuid.UUID
    operacao: Literal["ADICIONAR", "REMOVER", "DEFINIR"]
    valor: Decimal
    saldo_anterior: Decimal
    saldo_atual: Decimal
    motivo: Optional[str] = None
    ajustado_em: datetime.datetime

class UsuarioSaldoHistoricoRead(SQLModel):
    id: uuid.UUID
    operacao: Literal["ADICIONAR", "REMOVER", "DEFINIR"]
    valor: Decimal
    saldo_anterior: Decimal
    saldo_atual: Decimal
    motivo: Optional[str] = None
    criado_em: datetime.datetime
    admin_id: uuid.UUID
    admin_nome_completo: str
    admin_telegram_id: int

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
