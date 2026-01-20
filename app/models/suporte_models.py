import uuid
import datetime
from decimal import Decimal
from typing import Optional, TYPE_CHECKING
from sqlmodel import Field, SQLModel, Relationship

from app.models.base import (
    TipoStatusTicket, 
    TipoResolucaoTicket, 
    TipoMotivoTicket
)

if TYPE_CHECKING:
    from app.models.usuario_models import Usuario
    from app.models.pedido_models import Pedido
    from app.models.produto_models import EstoqueConta

# --- Tabela: tickets_suporte ---
class TicketSuporte(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    motivo: TipoMotivoTicket = Field(nullable=False)
    descricao_outros: Optional[str] = Field(default=None)
    status: TipoStatusTicket = Field(default=TipoStatusTicket.ABERTO, nullable=False, index=True)
    resolucao: TipoResolucaoTicket = Field(default=TipoResolucaoTicket.NA, nullable=False)
    criado_em: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False)
    atualizado_em: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False, sa_column_kwargs={"onupdate": datetime.datetime.utcnow})

    usuario_id: uuid.UUID = Field(foreign_key="usuario.id", nullable=False)
    pedido_id: uuid.UUID = Field(foreign_key="pedido.id", nullable=False, unique=True)
    estoque_conta_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="estoqueconta.id", nullable=True
    )

    usuario: "Usuario" = Relationship(back_populates="tickets")
    estoque_conta: Optional["EstoqueConta"] = Relationship(back_populates="tickets_problema")
    pedido: "Pedido" = Relationship(back_populates="ticket")

# --- Tabela: gift_cards ---
class GiftCard(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    codigo: str = Field(unique=True, index=True, nullable=False)
    valor: Decimal = Field(max_digits=10, decimal_places=2, nullable=False)
    is_utilizado: bool = Field(default=False, nullable=False)
    criado_em: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False)
    utilizado_em: Optional[datetime.datetime] = Field(default=None)

    criado_por_admin_id: uuid.UUID = Field(foreign_key="usuario.id", nullable=False)
    utilizado_por_usuario_id: Optional[uuid.UUID] = Field(default=None, foreign_key="usuario.id")

    # --- Relacionamentos de Usuario (Corrigidos) ---
    criado_por_admin: "Usuario" = Relationship(
        back_populates="gift_cards_criados",
        sa_relationship_kwargs={"foreign_keys": "GiftCard.criado_por_admin_id"}
    )
    
    utilizado_por_usuario: Optional["Usuario"] = Relationship(
        back_populates="gift_cards_resgatados",
        sa_relationship_kwargs={"foreign_keys": "GiftCard.utilizado_por_usuario_id"}
    )
