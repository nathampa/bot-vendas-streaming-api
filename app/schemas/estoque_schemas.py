import uuid
import datetime
from typing import Optional
from sqlmodel import SQLModel

class EstoqueCreate(SQLModel):
    produto_id: uuid.UUID
    login: str
    senha: str
    max_slots: int = 2
    data_expiracao: Optional[datetime.date] = None
    instrucoes_especificas: Optional[str] = None

class EstoqueAdminRead(SQLModel):
    id: uuid.UUID
    produto_id: uuid.UUID
    login: str
    max_slots: int
    slots_ocupados: int
    is_ativo: bool
    requer_atencao: bool
    data_expiracao: Optional[datetime.date] = None
    dias_restantes: Optional[int] = None
    instrucoes_especificas: Optional[str] = None

class EstoqueAdminReadDetails(EstoqueAdminRead):
    senha: Optional[str]

class EstoqueUpdate(SQLModel):
    login: Optional[str] = None
    senha: Optional[str] = None
    max_slots: Optional[int] = None
    slots_ocupados: Optional[int] = None
    is_ativo: Optional[bool] = None
    requer_atencao: Optional[bool] = None
    data_expiracao: Optional[datetime.date] = None
    instrucoes_especificas: Optional[str] = None