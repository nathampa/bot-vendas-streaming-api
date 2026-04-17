"""adiciona cancelamento e resolucao manual em jobs de convite

Revision ID: 3b7d2c4e5f61
Revises: 2a6f7c9d4b11
Create Date: 2026-04-17 12:25:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "3b7d2c4e5f61"
down_revision: Union[str, Sequence[str], None] = "2a6f7c9d4b11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE conta_mae_invite_job_status ADD VALUE IF NOT EXISTS 'CANCELLED'")

    op.add_column(
        "contamaeinvitejob",
        sa.Column("resolved_manually", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("contamaeinvitejob", sa.Column("manual_resolution_at", sa.DateTime(), nullable=True))
    op.add_column("contamaeinvitejob", sa.Column("manual_resolution_note", sa.String(length=500), nullable=True))
    op.add_column("contamaeinvitejob", sa.Column("cancelled_at", sa.DateTime(), nullable=True))
    op.alter_column("contamaeinvitejob", "resolved_manually", server_default=None)


def downgrade() -> None:
    op.drop_column("contamaeinvitejob", "cancelled_at")
    op.drop_column("contamaeinvitejob", "manual_resolution_note")
    op.drop_column("contamaeinvitejob", "manual_resolution_at")
    op.drop_column("contamaeinvitejob", "resolved_manually")
