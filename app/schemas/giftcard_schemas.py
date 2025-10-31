import uuid
import datetime
from decimal import Decimal
from typing import Optional
from sqlmodel import SQLModel

# -----------------------------------------------------------------
# Schema de ADMIN (O que o Admin envia para CRIAR um gift card)
# -----------------------------------------------------------------
class GiftCardCreateRequest(SQLModel):
    valor: Decimal
    quantidade: int = 1 # Quantos códigos gerar (ex: 10 de R$ 20,00)
    codigo_personalizado: Optional[str] = None # Opcional (ex: "NATAL2025")

# -----------------------------------------------------------------
# Schema de ADMIN (O que a API retorna após a CRIAÇÃO)
# -----------------------------------------------------------------
class GiftCardCreateResponse(SQLModel):
    codigos_gerados: list[str] # Retorna uma lista dos códigos criados
    valor: Decimal
    quantidade: int

# -----------------------------------------------------------------
# Schema de ADMIN (O que o Admin vê na lista de gift cards)
# -----------------------------------------------------------------
class GiftCardAdminRead(SQLModel):
    id: uuid.UUID
    codigo: str
    valor: Decimal
    is_utilizado: bool
    criado_em: datetime.datetime
    utilizado_em: Optional[datetime.datetime]
    utilizado_por_telegram_id: Optional[int] = None # Campo extra que o endpoint preencherá

# -----------------------------------------------------------------
# Schema de BOT (O que o Bot envia para RESGATAR)
# -----------------------------------------------------------------
class GiftCardResgatarRequest(SQLModel):
    telegram_id: int
    codigo: str

# -----------------------------------------------------------------
# Schema de BOT (O que a API retorna após o RESGATE)
# -----------------------------------------------------------------
class GiftCardResgatarResponse(SQLModel):
    valor_resgatado: Decimal
    novo_saldo_total: Decimal