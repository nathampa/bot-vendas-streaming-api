import datetime
import uuid
from typing import List, Optional

from sqlmodel import Field, SQLModel


class ContaMaeCreate(SQLModel):
    produto_id: uuid.UUID
    login: str
    senha: str
    max_slots: int = 1
    data_expiracao: Optional[datetime.date] = None
    is_ativo: bool = True
    email_monitor_account_id: Optional[uuid.UUID] = None
    session_storage_path: Optional[str] = None


class ContaMaeUpdate(SQLModel):
    login: Optional[str] = None
    senha: Optional[str] = None
    max_slots: Optional[int] = None
    data_expiracao: Optional[datetime.date] = None
    is_ativo: Optional[bool] = None
    email_monitor_account_id: Optional[uuid.UUID] = None
    session_storage_path: Optional[str] = None


class ContaMaeConviteRead(SQLModel):
    id: uuid.UUID
    email_cliente: str
    criado_em: datetime.datetime
    pedido_id: Optional[uuid.UUID] = None


class ContaMaeConviteCreate(SQLModel):
    email_cliente: str


class ContaMaeInviteJobRead(SQLModel):
    id: uuid.UUID
    convite_id: uuid.UUID
    conta_mae_id: uuid.UUID
    pedido_id: Optional[uuid.UUID] = None
    email_cliente: str
    status: str
    attempt_count: int
    auth_path_used: Optional[str] = None
    auth_step_failed: Optional[str] = None
    last_error: Optional[str] = None
    evidence_path: Optional[str] = None
    locked_at: Optional[datetime.datetime] = None
    started_at: Optional[datetime.datetime] = None
    finished_at: Optional[datetime.datetime] = None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ContaMaeSessionPrepareResponse(SQLModel):
    conta_mae_id: uuid.UUID
    session_storage_path: str
    launch_url: str
    launch_command: str
    browser_hint: str


class ContaMaeSessionTestResponse(SQLModel):
    conta_mae_id: uuid.UUID
    session_storage_path: str
    status: str
    message: str
    tested_at: datetime.datetime
    current_url: Optional[str] = None
    evidence_path: Optional[str] = None


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
    emails_vinculados: List[str] = Field(default_factory=list)
    email_monitor_account_id: Optional[uuid.UUID] = None
    session_storage_path: Optional[str] = None
    ultimo_login_automatizado_em: Optional[datetime.datetime] = None
    ultimo_convite_sucesso_em: Optional[datetime.datetime] = None
    ultimo_erro_automacao: Optional[str] = None


class ContaMaeAdminDetails(ContaMaeAdminRead):
    senha: Optional[str]
    convites: List[ContaMaeConviteRead] = Field(default_factory=list)
    invite_jobs: List[ContaMaeInviteJobRead] = Field(default_factory=list)
