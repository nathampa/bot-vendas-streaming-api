import uuid
import datetime
from typing import Optional
from sqlmodel import SQLModel
from app.models.base import TipoStatusTicket, TipoMotivoTicket, TipoResolucaoTicket
from app.schemas.estoque_schemas import EstoqueAdminReadDetails

# -----------------------------------------------------------------
# Schema de REQUEST (O que o bot envia para criar um ticket)
# -----------------------------------------------------------------
class TicketCreateRequest(SQLModel):
    telegram_id: int
    pedido_id: uuid.UUID  # O ID do pedido que deu problema
    motivo: TipoMotivoTicket # "LOGIN_INVALIDO", "SEM_ASSINATURA", etc.
    descricao_outros: Optional[str] = None

# -----------------------------------------------------------------
# Schema de RESPONSE (O que a API responde ao bot)
# -----------------------------------------------------------------
class TicketCreateResponse(SQLModel):
    id: uuid.UUID
    status: TipoStatusTicket
    motivo: TipoMotivoTicket
    criado_em: datetime.datetime

# -----------------------------------------------------------------
# Schema de ADMIN (O que o Admin vê na lista de tickets)
# -----------------------------------------------------------------
class TicketAdminRead(SQLModel):
    id: uuid.UUID
    status: TipoStatusTicket
    motivo: TipoMotivoTicket
    criado_em: datetime.datetime
    usuario_id: uuid.UUID
    pedido_id: uuid.UUID

# -----------------------------------------------------------------
# Schema de ADMIN (A ação que o Admin toma para resolver)
# -----------------------------------------------------------------
class TicketResolveRequest(SQLModel):
    # Ex: "TROCAR_CONTA", "REEMBOLSAR_CARTEIRA", "FECHAR_MANUALMENTE"
    acao: str
    mensagem: Optional[str] = None

# -----------------------------------------------------------------
# Schema de ADMIN (Detalhes de UM ticket)
# -----------------------------------------------------------------
# Este schema é o que o admin vê quando clica num ticket
class TicketAdminReadDetails(TicketAdminRead):
    descricao_outros: Optional[str]
    resolucao: TipoResolucaoTicket
    atualizado_em: datetime.datetime
    
    # Informação extra que o endpoint irá preencher:
    usuario_telegram_id: int
    produto_nome: str
    conta_problematica: Optional[EstoqueAdminReadDetails] = None # Mostra a conta (com senha)
