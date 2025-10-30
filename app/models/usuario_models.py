import uuid
import datetime
from decimal import Decimal
from typing import Optional, List
from sqlmodel import Field, SQLModel, Relationship

from app.models.base import TipoStatusPagamento # Importando nosso ENUM

# --- Tabela: usuarios ---
# Esta classe define a tabela E servirá como nosso Schema de Leitura (Read)
class Usuario(SQLModel, table=True):
    # Colunas
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    telegram_id: int = Field(unique=True, index=True, nullable=False)
    nome_completo: str = Field(nullable=False)
    saldo_carteira: Decimal = Field(default=0.0, max_digits=10, decimal_places=2, nullable=False)
    is_admin: bool = Field(default=False, nullable=False)
    
    # Colunas de login do Admin (nulas para usuários normais)
    email: Optional[str] = Field(default=None, unique=True, index=True)
    password_hash: Optional[str] = Field(default=None)

    criado_em: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False)
    atualizado_em: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False, sa_column_kwargs={"onupdate": datetime.datetime.utcnow})

    # Relacionamentos (O "back_populates" é como o SQLModel conecta as duas pontas)
    recargas: List["RecargaSaldo"] = Relationship(back_populates="usuario")
    pedidos: List["Pedido"] = Relationship(back_populates="usuario")
    tickets: List["TicketSuporte"] = Relationship(back_populates="usuario")
    sugestoes: List["SugestaoStreaming"] = Relationship(back_populates="usuario")
    gift_cards_resgatados: List["GiftCard"] = Relationship(back_populates="utilizado_por_usuario")
    gift_cards_criados: List["GiftCard"] = Relationship(back_populates="criado_por_admin")

# --- Tabela: recargas_saldo ---
class RecargaSaldo(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    valor_solicitado: Decimal = Field(max_digits=10, decimal_places=2, nullable=False)
    status_pagamento: TipoStatusPagamento = Field(default=TipoStatusPagamento.PENDENTE, nullable=False)
    gateway: str = Field(nullable=False)
    gateway_id: str = Field(nullable=True, index=True) # Pode ser nulo se a criação falhar
    pix_copia_e_cola: Optional[str] = Field(default=None)
    criado_em: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False)
    pago_em: Optional[datetime.datetime] = Field(default=None)

    # Chave Estrangeira (O 'link' com o usuário)
    usuario_id: uuid.UUID = Field(foreign_key="usuario.id", nullable=False)
    # Relacionamento (A 'conexão' com o usuário)
    usuario: Usuario = Relationship(back_populates="recargas")

# --- Tabela: sugestoes_streaming ---
class SugestaoStreaming(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    nome_streaming: str = Field(nullable=False, index=True)
    status: str = Field(default="PENDENTE", nullable=False) # Enum não é crítico aqui
    criado_em: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False)

    # Chave Estrangeira
    usuario_id: uuid.UUID = Field(foreign_key="usuario.id", nullable=False)
    # Relacionamento
    usuario: Usuario = Relationship(back_populates="sugestoes")