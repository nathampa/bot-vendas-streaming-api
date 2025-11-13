import uuid
import datetime
from decimal import Decimal
from typing import Optional
from app.models.base import TipoEntregaProduto
from sqlmodel import SQLModel

# -----------------------------------------------------------------
# Schema de REQUEST (O que o bot envia para a API)
# -----------------------------------------------------------------
class CompraCreateRequest(SQLModel):
    telegram_id: int      # Quem está a comprar
    produto_id: uuid.UUID   # O que está a comprar
    email_cliente: Optional[str] = None

# -----------------------------------------------------------------
# Schema de RESPONSE (O que a API retorna para o bot)
# -----------------------------------------------------------------
class CompraCreateResponse(SQLModel):
    # O "Recibo"
    pedido_id: uuid.UUID
    data_compra: datetime.datetime
    valor_pago: Decimal
    novo_saldo: Decimal
    
    # O "Produto"
    produto_nome: str
    login: Optional[str] = None
    senha: Optional[str] = None
    tipo_entrega: TipoEntregaProduto
    mensagem_entrega: str