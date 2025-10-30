import uuid
import datetime
from decimal import Decimal
from typing import Optional, TYPE_CHECKING
from sqlmodel import Field, SQLModel, Relationship

# Usamos o TYPE_CHECKING para importar classes
# que também dependem desta, evitando erros de importação circular.
if TYPE_CHECKING:
    from app.models.usuario_models import Usuario
    from app.models.produto_models import Produto, EstoqueConta
    from app.models.suporte_models import TicketSuporte

# --- Tabela: pedidos ---
class Pedido(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    valor_pago: Decimal = Field(max_digits=10, decimal_places=2, nullable=False)
    criado_em: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False)

    # --- Chaves Estrangeiras ---
    usuario_id: uuid.UUID = Field(foreign_key="usuario.id", nullable=False)
    produto_id: uuid.UUID = Field(foreign_key="produto.id", nullable=False)
    estoque_conta_id: uuid.UUID = Field(foreign_key="estoqueconta.id", nullable=False)

    # --- Relacionamentos (Lado "Muitos") ---
    usuario: "Usuario" = Relationship(back_populates="pedidos")
    produto: "Produto" = Relationship(back_populates="pedidos")
    estoque_conta: "EstoqueConta" = Relationship(back_populates="pedidos")

    # --- Relacionamento 1-para-1 ---
    # Um pedido pode ter, no máximo, UM ticket de suporte.
    ticket: Optional["TicketSuporte"] = Relationship(back_populates="pedido")