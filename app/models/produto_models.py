import uuid
import datetime
from decimal import Decimal
from typing import Optional, List
from sqlmodel import Field, SQLModel, Relationship

# Importando 'Pedido' e 'TicketSuporte' como strings
# para evitar erros de "Importação Circular"
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.models.pedido_models import Pedido
    from app.models.suporte_models import TicketSuporte

# --- Tabela: produtos ---
class Produto(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    nome: str = Field(unique=True, index=True, nullable=False)
    descricao: Optional[str] = Field(default=None)
    preco: Decimal = Field(max_digits=10, decimal_places=2, nullable=False)
    is_ativo: bool = Field(default=True, nullable=False)
    requer_email_cliente: bool = Field(default=False, nullable=False)
    criado_em: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False)
    atualizado_em: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False, sa_column_kwargs={"onupdate": datetime.datetime.utcnow})
    
    # Relacionamentos
    contas_estoque: List["EstoqueConta"] = Relationship(back_populates="produto")
    pedidos: List["Pedido"] = Relationship(back_populates="produto")

# --- Tabela: estoque_contas ---
class EstoqueConta(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    login: str = Field(nullable=False)
    senha: str = Field(nullable=False) # Lembrete: Criptografada pela API
    max_slots: int = Field(default=2, nullable=False)
    slots_ocupados: int = Field(default=0, nullable=False)
    is_ativo: bool = Field(default=True, nullable=False)
    requer_atencao: bool = Field(default=False, nullable=False)
    criado_em: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False)
    atualizado_em: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False, sa_column_kwargs={"onupdate": datetime.datetime.utcnow})

    # Chave Estrangeira
    produto_id: uuid.UUID = Field(foreign_key="produto.id", nullable=False)
    # Relacionamento
    produto: Produto = Relationship(back_populates="contas_estoque")

    # Relacionamentos
    pedidos: List["Pedido"] = Relationship(back_populates="estoque_conta")
    tickets_problema: List["TicketSuporte"] = Relationship(back_populates="estoque_conta")