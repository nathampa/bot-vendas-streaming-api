import uuid
import datetime
from typing import Optional, List, TYPE_CHECKING
from sqlmodel import Field, SQLModel, Relationship

if TYPE_CHECKING:
    from app.models.produto_models import Produto
    from app.models.pedido_models import Pedido


class ContaMae(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    login: str = Field(nullable=False, index=True)
    senha: str = Field(nullable=False)
    max_slots: int = Field(default=1, nullable=False)
    slots_ocupados: int = Field(default=0, nullable=False)
    is_ativo: bool = Field(default=True, nullable=False)
    data_expiracao: Optional[datetime.date] = Field(default=None, nullable=True)
    criado_em: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False)
    atualizado_em: datetime.datetime = Field(
        default_factory=datetime.datetime.utcnow,
        nullable=False,
        sa_column_kwargs={"onupdate": datetime.datetime.utcnow},
    )

    produto_id: uuid.UUID = Field(foreign_key="produto.id", nullable=False)
    produto: "Produto" = Relationship(back_populates="contas_mae")

    convites: List["ContaMaeConvite"] = Relationship(back_populates="conta_mae")
    pedidos: List["Pedido"] = Relationship(back_populates="conta_mae")


class ContaMaeConvite(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email_cliente: str = Field(nullable=False, index=True)
    criado_em: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False)

    conta_mae_id: uuid.UUID = Field(foreign_key="contamae.id", nullable=False)
    pedido_id: Optional[uuid.UUID] = Field(default=None, foreign_key="pedido.id", nullable=True)

    conta_mae: ContaMae = Relationship(back_populates="convites")
    pedido: Optional["Pedido"] = Relationship(back_populates="conta_mae_convite")
