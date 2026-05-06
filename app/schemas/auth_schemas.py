from sqlmodel import SQLModel
import uuid
import datetime

# Schema para o corpo (JSON) do pedido de login
class LoginRequest(SQLModel):
    email: str
    senha: str

# Schema para a resposta (JSON) do token
class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


class AdminProfileRead(SQLModel):
    id: uuid.UUID
    nome_completo: str
    email: str | None = None
    telegram_id: int
    is_admin: bool
    criado_em: datetime.datetime
