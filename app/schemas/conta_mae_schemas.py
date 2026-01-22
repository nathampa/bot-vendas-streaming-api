import uuid
import datetime
from typing import Optional, List
from sqlmodel import SQLModel


class ContaMaeCreate(SQLModel):
    produto_id: uuid.UUID
    login: str
    senha: str
    max_slots: int = 1
    data_expiracao: Optional[datetime.date] = None
    is_ativo: bool = True


class ContaMaeUpdate(SQLModel):
    login: Optional[str] = None
    senha: Optional[str] = None
    max_slots: Optional[int] = None
    data_expiracao: Optional[datetime.date] = None
    is_ativo: Optional[bool] = None


class ContaMaeConviteRead(SQLModel):
    id: uuid.UUID
    email_cliente: str
    criado_em: datetime.datetime
    pedido_id: Optional[uuid.UUID] = None


class ContaMaeConviteCreate(SQLModel):
    email_cliente: str


class ContaMaeAdminRead(SQLModel):
    id: uuid.UUID
    produto_id: uuid.UUID
    login: str
    max_slots: int
    slots_ocupados: int
    is_ativo: bool
    data_expiracao: Optional[datetime.date] = None
    dias_restantes: Optional[int] = None
    total_convites: Optional[int] = None


class ContaMaeAdminDetails(ContaMaeAdminRead):
    senha: Optional[str]
    convites: List[ContaMaeConviteRead] = []
