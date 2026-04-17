import datetime
import enum
import uuid
from typing import TYPE_CHECKING, List, Optional

import sqlalchemy as sa
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.pedido_models import Pedido
    from app.models.produto_models import Produto


class ContaMaeInviteJobStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_OTP = "WAITING_OTP"
    RETRY_WAIT = "RETRY_WAIT"
    SENT = "SENT"
    FAILED = "FAILED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class ContaMae(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    login: str = Field(nullable=False, index=True)
    senha: str = Field(nullable=False)
    max_slots: int = Field(default=1, nullable=False)
    slots_ocupados: int = Field(default=0, nullable=False)
    is_ativo: bool = Field(default=True, nullable=False)
    data_expiracao: Optional[datetime.date] = Field(default=None, nullable=True)
    email_monitor_account_id: Optional[uuid.UUID] = Field(
        default=None,
        foreign_key="email_monitor_accounts.id",
        nullable=True,
        index=True,
    )
    session_storage_path: Optional[str] = Field(default=None, nullable=True, max_length=500)
    ultimo_login_automatizado_em: Optional[datetime.datetime] = Field(default=None, nullable=True)
    ultimo_convite_sucesso_em: Optional[datetime.datetime] = Field(default=None, nullable=True)
    ultimo_erro_automacao: Optional[str] = Field(default=None, nullable=True, max_length=500)
    criado_em: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False)
    atualizado_em: datetime.datetime = Field(
        default_factory=datetime.datetime.utcnow,
        nullable=False,
        sa_column_kwargs={"onupdate": datetime.datetime.utcnow},
    )

    produto_id: uuid.UUID = Field(foreign_key="produto.id", nullable=False)
    produto: "Produto" = Relationship(back_populates="contas_mae")

    convites: List["ContaMaeConvite"] = Relationship(back_populates="conta_mae")
    pedidos: List["Pedido"] = Relationship(back_populates="conta_mae")
    invite_jobs: List["ContaMaeInviteJob"] = Relationship(back_populates="conta_mae")


class ContaMaeConvite(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email_cliente: str = Field(nullable=False, index=True)
    criado_em: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False)

    conta_mae_id: uuid.UUID = Field(foreign_key="contamae.id", nullable=False)
    pedido_id: Optional[uuid.UUID] = Field(default=None, foreign_key="pedido.id", nullable=True)

    conta_mae: ContaMae = Relationship(back_populates="convites")
    pedido: Optional["Pedido"] = Relationship(back_populates="conta_mae_convite")
    invite_job: Optional["ContaMaeInviteJob"] = Relationship(back_populates="convite")


class ContaMaeInviteJob(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    convite_id: uuid.UUID = Field(
        foreign_key="contamaeconvite.id",
        nullable=False,
        sa_column_kwargs={"unique": True},
    )
    conta_mae_id: uuid.UUID = Field(foreign_key="contamae.id", nullable=False, index=True)
    pedido_id: Optional[uuid.UUID] = Field(default=None, foreign_key="pedido.id", nullable=True, index=True)
    email_cliente: str = Field(nullable=False, index=True)
    status: ContaMaeInviteJobStatus = Field(
        default=ContaMaeInviteJobStatus.PENDING,
        sa_column=sa.Column(sa.Enum(ContaMaeInviteJobStatus, name="conta_mae_invite_job_status"), nullable=False, index=True),
    )
    attempt_count: int = Field(default=0, nullable=False)
    auth_path_used: Optional[str] = Field(default=None, nullable=True, max_length=80)
    auth_step_failed: Optional[str] = Field(default=None, nullable=True, max_length=80)
    last_error: Optional[str] = Field(default=None, nullable=True, max_length=500)
    evidence_path: Optional[str] = Field(default=None, nullable=True, max_length=500)
    locked_at: Optional[datetime.datetime] = Field(default=None, nullable=True, index=True)
    started_at: Optional[datetime.datetime] = Field(default=None, nullable=True)
    finished_at: Optional[datetime.datetime] = Field(default=None, nullable=True)
    next_retry_at: Optional[datetime.datetime] = Field(default=None, nullable=True, index=True)
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False, index=True)
    updated_at: datetime.datetime = Field(
        default_factory=datetime.datetime.utcnow,
        nullable=False,
        sa_column_kwargs={"onupdate": datetime.datetime.utcnow},
    )

    conta_mae: ContaMae = Relationship(back_populates="invite_jobs")
    convite: ContaMaeConvite = Relationship(back_populates="invite_job")
