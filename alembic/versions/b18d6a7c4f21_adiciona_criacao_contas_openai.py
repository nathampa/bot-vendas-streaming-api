"""adiciona criacao de contas openai

Revision ID: b18d6a7c4f21
Revises: a4b8c2d9e6f1, 2a6f7c9d4b11
Create Date: 2026-04-30 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "b18d6a7c4f21"
down_revision: Union[str, Sequence[str], None] = ("a4b8c2d9e6f1", "2a6f7c9d4b11")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    request_status_enum = postgresql.ENUM(
        "PENDING",
        "RUNNING",
        "WAITING_OTP_INPUT",
        "RETRY_WAIT",
        "CREATED",
        "FAILED",
        "MANUAL_REVIEW",
        "CANCELLED",
        name="openai_account_creation_request_status",
        create_type=False,
    )
    request_status_enum.create(bind, checkfirst=True)

    job_status_enum = postgresql.ENUM(
        "PENDING",
        "RUNNING",
        "WAITING_OTP_INPUT",
        "RETRY_WAIT",
        "CREATED",
        "FAILED",
        "MANUAL_REVIEW",
        "CANCELLED",
        name="openai_account_creation_job_status",
        create_type=False,
    )
    job_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "openaiaccountcreationrequest",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("senha_encrypted", sa.String(), nullable=False),
        sa.Column("session_storage_path", sa.String(length=500), nullable=True),
        sa.Column("workspace_name", sa.String(length=255), nullable=True),
        sa.Column("status_atual", request_status_enum, nullable=False),
        sa.Column("ultimo_erro", sa.String(length=500), nullable=True),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_openaiaccountcreationrequest_email"),
        "openaiaccountcreationrequest",
        ["email"],
        unique=True,
    )

    op.create_table(
        "openaiaccountcreationjob",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", job_status_enum, nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("otp_code_encrypted", sa.String(length=512), nullable=True),
        sa.Column("otp_submitted_at", sa.DateTime(), nullable=True),
        sa.Column("auth_path_used", sa.String(length=80), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("evidence_path", sa.String(length=500), nullable=True),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["request_id"], ["openaiaccountcreationrequest.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_openaiaccountcreationjob_created_at"),
        "openaiaccountcreationjob",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_openaiaccountcreationjob_locked_at"),
        "openaiaccountcreationjob",
        ["locked_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_openaiaccountcreationjob_next_retry_at"),
        "openaiaccountcreationjob",
        ["next_retry_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_openaiaccountcreationjob_request_id"),
        "openaiaccountcreationjob",
        ["request_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_openaiaccountcreationjob_status"),
        "openaiaccountcreationjob",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_openaiaccountcreationjob_status"), table_name="openaiaccountcreationjob")
    op.drop_index(op.f("ix_openaiaccountcreationjob_request_id"), table_name="openaiaccountcreationjob")
    op.drop_index(op.f("ix_openaiaccountcreationjob_next_retry_at"), table_name="openaiaccountcreationjob")
    op.drop_index(op.f("ix_openaiaccountcreationjob_locked_at"), table_name="openaiaccountcreationjob")
    op.drop_index(op.f("ix_openaiaccountcreationjob_created_at"), table_name="openaiaccountcreationjob")
    op.drop_table("openaiaccountcreationjob")

    op.drop_index(op.f("ix_openaiaccountcreationrequest_email"), table_name="openaiaccountcreationrequest")
    op.drop_table("openaiaccountcreationrequest")

    bind = op.get_bind()
    postgresql.ENUM(name="openai_account_creation_job_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="openai_account_creation_request_status").drop(bind, checkfirst=True)
