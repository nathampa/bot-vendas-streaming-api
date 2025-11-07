import uuid
import datetime
from decimal import Decimal
from typing import Optional, List, TYPE_CHECKING
from sqlmodel import Field, SQLModel, Relationship
import sqlalchemy as sa

from app.models.base import TipoStatusPagamento

# Bloco de importação para evitar erros de importação circular
if TYPE_CHECKING:
    from app.models.pedido_models import Pedido
    from app.models.suporte_models import TicketSuporte, GiftCard

# --- Tabela: usuarios ---
class Usuario(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    telegram_id: int = Field(sa_column=sa.Column(sa.BigInteger(), unique=True, index=True, nullable=False))
    nome_completo: str = Field(nullable=False)
    saldo_carteira: Decimal = Field(default=0.0, max_digits=10, decimal_places=2, nullable=False)
    is_admin: bool = Field(default=False, nullable=False)
    
    email: Optional[str] = Field(default=None, unique=True, index=True)
    password_hash: Optional[str] = Field(default=None)

    criado_em: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False)
    atualizado_em: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False, sa_column_kwargs={"onupdate": datetime.datetime.utcnow})

    # Armazena quem indicou o usuário
    referrer_id: Optional[uuid.UUID] = Field(default=None, foreign_key="usuario.id",nullable=True)

    # Prêmio cashback pendente
    pending_cashback_percent: Optional[int] = Field(default=None, nullable=True)

    # --- Relacionamentos ---
    recargas: List["RecargaSaldo"] = Relationship(back_populates="usuario")
    pedidos: List["Pedido"] = Relationship(back_populates="usuario")
    tickets: List["TicketSuporte"] = Relationship(back_populates="usuario")
    sugestoes: List["SugestaoStreaming"] = Relationship(back_populates="usuario")

    # Relacionamentos de GiftCard (Corrigidos)
    gift_cards_resgatados: List["GiftCard"] = Relationship(
        back_populates="utilizado_por_usuario",
        sa_relationship_kwargs={"foreign_keys": "GiftCard.utilizado_por_usuario_id"}
    )
    gift_cards_criados: List["GiftCard"] = Relationship(
        back_populates="criado_por_admin",
        sa_relationship_kwargs={"foreign_keys": "GiftCard.criado_por_admin_id"}
    )

    # Relação para que possamos acessar o objeto 'Usuario' de quem indicou
    referrer: Optional["Usuario"] = Relationship(
        back_populates="referrals",
        sa_relationship_kwargs={"foreign_keys": "[Usuario.referrer_id]"}
    )

    # Relação para ver todos os usuários que 'este' usuário indicou
    referrals: List["Usuario"] = Relationship(
        back_populates="referrer",
        sa_relationship_kwargs={"primaryjoin": "Usuario.id == Usuario.referrer_id"}
    )

# --- Tabela: recargas_saldo ---
class RecargaSaldo(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    valor_solicitado: Decimal = Field(max_digits=10, decimal_places=2, nullable=False)
    status_pagamento: TipoStatusPagamento = Field(default=TipoStatusPagamento.PENDENTE, nullable=False)
    gateway: str = Field(nullable=False)
    gateway_id: str = Field(nullable=True, index=True)
    pix_copia_e_cola: Optional[str] = Field(default=None)
    criado_em: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False)
    pago_em: Optional[datetime.datetime] = Field(default=None)

    usuario_id: uuid.UUID = Field(foreign_key="usuario.id", nullable=False)
    usuario: Usuario = Relationship(back_populates="recargas")

# --- Tabela: sugestoes_streaming ---
class SugestaoStreaming(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    nome_streaming: str = Field(nullable=False, index=True)
    status: str = Field(default="PENDENTE", nullable=False)
    criado_em: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False)

    usuario_id: uuid.UUID = Field(foreign_key="usuario.id", nullable=False)
    usuario: Usuario = Relationship(back_populates="sugestoes")