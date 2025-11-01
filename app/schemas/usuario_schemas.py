import uuid
from decimal import Decimal
from sqlmodel import SQLModel

# -----------------------------------------------------------------
# Schema de REQUEST (O que o bot envia para registar um user)
# -----------------------------------------------------------------
class UsuarioRegisterRequest(SQLModel):
    telegram_id: int
    nome_completo: str

# -----------------------------------------------------------------
# Schema de RESPONSE (O que a API retorna)
# -----------------------------------------------------------------
class UsuarioRead(SQLModel):
    id: uuid.UUID
    telegram_id: int
    nome_completo: str
    saldo_carteira: Decimal
    is_admin: bool