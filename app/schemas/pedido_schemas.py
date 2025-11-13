import uuid
import datetime
from decimal import Decimal
from typing import Optional
from sqlmodel import SQLModel
from app.models.base import StatusEntregaPedido

# -----------------------------------------------------------------
# Schema para a CONTA (login/senha) aninhada nos detalhes
# -----------------------------------------------------------------
class PedidoAdminConta(SQLModel):
    login: str
    senha: str # A API vai preencher isso com a senha descriptografada

# -----------------------------------------------------------------
# Schema de REQUEST (O que o Admin envia para ENTREGAR um pedido)
# -----------------------------------------------------------------
class PedidoAdminEntregaRequest(SQLModel):
    login: str
    senha: str

# -----------------------------------------------------------------
# Schema para a LISTA de pedidos (o que aparece na tabela)
# -----------------------------------------------------------------
class PedidoAdminList(SQLModel):
    id: uuid.UUID
    criado_em: datetime.datetime
    valor_pago: Decimal
    status_entrega: StatusEntregaPedido
    
    # Dados do JOIN
    produto_nome: str
    usuario_nome_completo: str
    usuario_telegram_id: int
    email_cliente: Optional[str] = None

# -----------------------------------------------------------------
# Schema para os DETALHES de um pedido (o que aparece no modal)
# -----------------------------------------------------------------
class PedidoAdminDetails(PedidoAdminList):
    # Herda tudo da lista e adiciona a conta
    conta: Optional[PedidoAdminConta] = None