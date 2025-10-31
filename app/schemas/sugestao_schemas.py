import uuid
import datetime
from sqlmodel import SQLModel

# -----------------------------------------------------------------
# Schema de REQUEST (O que o bot envia para a API)
# -----------------------------------------------------------------
class SugestaoCreateRequest(SQLModel):
    telegram_id: int
    nome_streaming: str # Ex: "Disney Plus", "Star+", etc.

# -----------------------------------------------------------------
# Schema de RESPONSE (O que a API responde ao bot)
# -----------------------------------------------------------------
class SugestaoCreateResponse(SQLModel):
    id: uuid.UUID
    nome_streaming: str
    status: str
    criado_em: datetime.datetime

# -----------------------------------------------------------------
# Schema de ADMIN (O que o Admin vê na lista de sugestões)
# -----------------------------------------------------------------
class SugestaoAdminRead(SQLModel):
    nome_streaming: str
    contagem: int  # Quantos utilizadores pediram isto
    status: str    # O status (ex: PENDENTE)