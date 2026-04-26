"""adiciona remocao automatica de membros openai

Revision ID: a4b8c2d9e6f1
Revises: c7f9e2a1b3c4
Create Date: 2026-04-26 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "a4b8c2d9e6f1"
down_revision: Union[str, Sequence[str], None] = "c7f9e2a1b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    removal_status_enum = postgresql.ENUM(
        "PENDING",
        "RUNNING",
        "RETRY_WAIT",
        "REMOVED",
        "NOT_FOUND",
        "FAILED",
        "MANUAL_REVIEW",
        "CANCELLED",
        name="conta_mae_member_removal_job_status",
        create_type=False,
    )
    bind = op.get_bind()
    removal_status_enum.create(bind, checkfirst=True)

    op.add_column(
        "contamaeconvite",
        sa.Column("aviso_remocao_workspace_enviado_em", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "contamaeconvite",
        sa.Column("removido_workspace_em", sa.DateTime(), nullable=True),
    )
    op.create_index(
        op.f("ix_contamaeconvite_aviso_remocao_workspace_enviado_em"),
        "contamaeconvite",
        ["aviso_remocao_workspace_enviado_em"],
        unique=False,
    )
    op.create_index(
        op.f("ix_contamaeconvite_removido_workspace_em"),
        "contamaeconvite",
        ["removido_workspace_em"],
        unique=False,
    )

    op.create_table(
        "contamaememberremovaljob",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("convite_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conta_mae_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pedido_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("email_cliente", sa.String(), nullable=False),
        sa.Column("status", removal_status_enum, nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
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
        sa.ForeignKeyConstraint(["conta_mae_id"], ["contamae.id"]),
        sa.ForeignKeyConstraint(["convite_id"], ["contamaeconvite.id"]),
        sa.ForeignKeyConstraint(["pedido_id"], ["pedido.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("convite_id"),
    )
    op.create_index(
        op.f("ix_contamaememberremovaljob_conta_mae_id"),
        "contamaememberremovaljob",
        ["conta_mae_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_contamaememberremovaljob_created_at"),
        "contamaememberremovaljob",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_contamaememberremovaljob_email_cliente"),
        "contamaememberremovaljob",
        ["email_cliente"],
        unique=False,
    )
    op.create_index(
        op.f("ix_contamaememberremovaljob_locked_at"),
        "contamaememberremovaljob",
        ["locked_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_contamaememberremovaljob_next_retry_at"),
        "contamaememberremovaljob",
        ["next_retry_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_contamaememberremovaljob_pedido_id"),
        "contamaememberremovaljob",
        ["pedido_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_contamaememberremovaljob_status"),
        "contamaememberremovaljob",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_contamaememberremovaljob_status"), table_name="contamaememberremovaljob")
    op.drop_index(op.f("ix_contamaememberremovaljob_pedido_id"), table_name="contamaememberremovaljob")
    op.drop_index(op.f("ix_contamaememberremovaljob_next_retry_at"), table_name="contamaememberremovaljob")
    op.drop_index(op.f("ix_contamaememberremovaljob_locked_at"), table_name="contamaememberremovaljob")
    op.drop_index(op.f("ix_contamaememberremovaljob_email_cliente"), table_name="contamaememberremovaljob")
    op.drop_index(op.f("ix_contamaememberremovaljob_created_at"), table_name="contamaememberremovaljob")
    op.drop_index(op.f("ix_contamaememberremovaljob_conta_mae_id"), table_name="contamaememberremovaljob")
    op.drop_table("contamaememberremovaljob")

    op.drop_index(op.f("ix_contamaeconvite_removido_workspace_em"), table_name="contamaeconvite")
    op.drop_index(op.f("ix_contamaeconvite_aviso_remocao_workspace_enviado_em"), table_name="contamaeconvite")
    op.drop_column("contamaeconvite", "removido_workspace_em")
    op.drop_column("contamaeconvite", "aviso_remocao_workspace_enviado_em")

    bind = op.get_bind()
    postgresql.ENUM(name="conta_mae_member_removal_job_status").drop(bind, checkfirst=True)
