import datetime
import enum
import uuid
from typing import List, Optional

import sqlalchemy as sa
from sqlmodel import Field, Relationship, SQLModel


class OpenAIAccountCreationRequestStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_OTP_INPUT = "WAITING_OTP_INPUT"
    RETRY_WAIT = "RETRY_WAIT"
    CREATED = "CREATED"
    FAILED = "FAILED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    CANCELLED = "CANCELLED"


class OpenAIAccountCreationJobStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_OTP_INPUT = "WAITING_OTP_INPUT"
    RETRY_WAIT = "RETRY_WAIT"
    CREATED = "CREATED"
    FAILED = "FAILED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    CANCELLED = "CANCELLED"


class OpenAIAccountCreationRequest(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email: str = Field(nullable=False, index=True)
    senha_encrypted: str = Field(nullable=False, max_length=1200)
    outlook_email: Optional[str] = Field(default=None, nullable=True, index=True, max_length=255)
    outlook_password_encrypted: Optional[str] = Field(default=None, nullable=True, max_length=1200)
    session_storage_path: Optional[str] = Field(default=None, nullable=True, max_length=500)
    workspace_name: Optional[str] = Field(default=None, nullable=True, max_length=120)
    status_atual: OpenAIAccountCreationRequestStatus = Field(
        default=OpenAIAccountCreationRequestStatus.PENDING,
        sa_column=sa.Column(
            sa.Enum(OpenAIAccountCreationRequestStatus, name="openai_account_creation_request_status"),
            nullable=False,
            index=True,
        ),
    )
    ultimo_erro: Optional[str] = Field(default=None, nullable=True, max_length=500)
    criado_em: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False, index=True)
    atualizado_em: datetime.datetime = Field(
        default_factory=datetime.datetime.utcnow,
        nullable=False,
        sa_column_kwargs={"onupdate": datetime.datetime.utcnow},
    )

    jobs: List["OpenAIAccountCreationJob"] = Relationship(back_populates="request")


class OpenAIAccountCreationJob(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    request_id: uuid.UUID = Field(
        foreign_key="openaiaccountcreationrequest.id",
        nullable=False,
        index=True,
    )
    status: OpenAIAccountCreationJobStatus = Field(
        default=OpenAIAccountCreationJobStatus.PENDING,
        sa_column=sa.Column(
            sa.Enum(OpenAIAccountCreationJobStatus, name="openai_account_creation_job_status"),
            nullable=False,
            index=True,
        ),
    )
    attempt_count: int = Field(default=0, nullable=False)
    otp_code_encrypted: Optional[str] = Field(default=None, nullable=True, max_length=1200)
    otp_submitted_at: Optional[datetime.datetime] = Field(default=None, nullable=True)
    auth_path_used: Optional[str] = Field(default=None, nullable=True, max_length=120)
    last_error: Optional[str] = Field(default=None, nullable=True, max_length=500)
    evidence_path: Optional[str] = Field(default=None, nullable=True, max_length=500)
    locked_at: Optional[datetime.datetime] = Field(default=None, nullable=True, index=True)
    started_at: Optional[datetime.datetime] = Field(default=None, nullable=True)
    finished_at: Optional[datetime.datetime] = Field(default=None, nullable=True)
    next_retry_at: Optional[datetime.datetime] = Field(default=None, nullable=True, index=True)
    cancelled_at: Optional[datetime.datetime] = Field(default=None, nullable=True)
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False, index=True)
    updated_at: datetime.datetime = Field(
        default_factory=datetime.datetime.utcnow,
        nullable=False,
        sa_column_kwargs={"onupdate": datetime.datetime.utcnow},
    )

    request: OpenAIAccountCreationRequest = Relationship(back_populates="jobs")
