"""adiciona fila de automacao de convites openai

Revision ID: d16b4c8e91fa
Revises: 5b7a91c2d4e6
Create Date: 2026-04-16 21:05:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "d16b4c8e91fa"
down_revision: Union[str, Sequence[str], None] = "5b7a91c2d4e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    invite_status_enum = postgresql.ENUM(
        "PENDING",
        "RUNNING",
        "WAITING_OTP",
        "SENT",
        "FAILED",
        "MANUAL_REVIEW",
        name="conta_mae_invite_job_status",
        create_type=False,
    )

    bind = op.get_bind()
    invite_status_enum.create(bind, checkfirst=True)

    op.add_column("contamae", sa.Column("email_monitor_account_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("contamae", sa.Column("session_storage_path", sa.String(length=500), nullable=True))
    op.add_column("contamae", sa.Column("ultimo_login_automatizado_em", sa.DateTime(), nullable=True))
    op.add_column("contamae", sa.Column("ultimo_convite_sucesso_em", sa.DateTime(), nullable=True))
    op.add_column("contamae", sa.Column("ultimo_erro_automacao", sa.String(length=500), nullable=True))
    op.create_index(op.f("ix_contamae_email_monitor_account_id"), "contamae", ["email_monitor_account_id"], unique=False)
    op.create_foreign_key(
        "fk_contamae_email_monitor_account_id_email_monitor_accounts",
        "contamae",
        "email_monitor_accounts",
        ["email_monitor_account_id"],
        ["id"],
    )

    op.create_table(
        "contamaeinvitejob",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("convite_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conta_mae_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pedido_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("email_cliente", sa.String(), nullable=False),
        sa.Column("status", invite_status_enum, nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("auth_path_used", sa.String(length=80), nullable=True),
        sa.Column("auth_step_failed", sa.String(length=80), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("evidence_path", sa.String(length=500), nullable=True),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["conta_mae_id"], ["contamae.id"]),
        sa.ForeignKeyConstraint(["convite_id"], ["contamaeconvite.id"]),
        sa.ForeignKeyConstraint(["pedido_id"], ["pedido.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("convite_id"),
    )
    op.create_index(op.f("ix_contamaeinvitejob_conta_mae_id"), "contamaeinvitejob", ["conta_mae_id"], unique=False)
    op.create_index(op.f("ix_contamaeinvitejob_created_at"), "contamaeinvitejob", ["created_at"], unique=False)
    op.create_index(op.f("ix_contamaeinvitejob_email_cliente"), "contamaeinvitejob", ["email_cliente"], unique=False)
    op.create_index(op.f("ix_contamaeinvitejob_locked_at"), "contamaeinvitejob", ["locked_at"], unique=False)
    op.create_index(op.f("ix_contamaeinvitejob_pedido_id"), "contamaeinvitejob", ["pedido_id"], unique=False)
    op.create_index(op.f("ix_contamaeinvitejob_status"), "contamaeinvitejob", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_contamaeinvitejob_status"), table_name="contamaeinvitejob")
    op.drop_index(op.f("ix_contamaeinvitejob_pedido_id"), table_name="contamaeinvitejob")
    op.drop_index(op.f("ix_contamaeinvitejob_locked_at"), table_name="contamaeinvitejob")
    op.drop_index(op.f("ix_contamaeinvitejob_email_cliente"), table_name="contamaeinvitejob")
    op.drop_index(op.f("ix_contamaeinvitejob_created_at"), table_name="contamaeinvitejob")
    op.drop_index(op.f("ix_contamaeinvitejob_conta_mae_id"), table_name="contamaeinvitejob")
    op.drop_table("contamaeinvitejob")

    op.drop_constraint("fk_contamae_email_monitor_account_id_email_monitor_accounts", "contamae", type_="foreignkey")
    op.drop_index(op.f("ix_contamae_email_monitor_account_id"), table_name="contamae")
    op.drop_column("contamae", "ultimo_erro_automacao")
    op.drop_column("contamae", "ultimo_convite_sucesso_em")
    op.drop_column("contamae", "ultimo_login_automatizado_em")
    op.drop_column("contamae", "session_storage_path")
    op.drop_column("contamae", "email_monitor_account_id")

    bind = op.get_bind()
    postgresql.ENUM(name="conta_mae_invite_job_status").drop(bind, checkfirst=True)
