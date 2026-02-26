import uuid
import datetime
from decimal import Decimal
from typing import Optional, TYPE_CHECKING
from sqlmodel import Field, SQLModel, Relationship
from app.models.base import StatusEntregaPedido

# Usamos o TYPE_CHECKING para importar classes
# que também dependem desta, evitando erros de importação circular.
if TYPE_CHECKING:
    from app.models.usuario_models import Usuario
    from app.models.produto_models import Produto, EstoqueConta
    from app.models.conta_mae_models import ContaMae, ContaMaeConvite
    from app.models.suporte_models import TicketSuporte

# --- Tabela: pedidos ---
class Pedido(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    valor_pago: Decimal = Field(max_digits=10, decimal_places=2, nullable=False)
    criado_em: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False)
    email_cliente: Optional[str] = Field(default=None, nullable=True, index=True)
    ultima_data_expiracao_notificada: Optional[datetime.date] = Field(default=None, nullable=True)
    status_entrega: StatusEntregaPedido = Field(
        default=StatusEntregaPedido.ENTREGUE, 
        nullable=False
    )

    # --- Chaves Estrangeiras ---
    usuario_id: uuid.UUID = Field(foreign_key="usuario.id", nullable=False)
    produto_id: uuid.UUID = Field(foreign_key="produto.id", nullable=False)
    estoque_conta_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="estoqueconta.id", nullable=True
    )
    conta_mae_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="contamae.id", nullable=True
    )

    # --- Relacionamentos (Lado "Muitos") ---
    usuario: "Usuario" = Relationship(back_populates="pedidos")
    produto: "Produto" = Relationship(back_populates="pedidos")
    estoque_conta: Optional["EstoqueConta"] = Relationship(back_populates="pedidos")
    conta_mae: Optional["ContaMae"] = Relationship(back_populates="pedidos")
    conta_mae_convite: Optional["ContaMaeConvite"] = Relationship(back_populates="pedido")

    # --- Relacionamento 1-para-1 ---
    # Um pedido pode ter, no máximo, UM ticket de suporte.
    ticket: Optional["TicketSuporte"] = Relationship(back_populates="pedido")
