"""adiciona retry wait aos convites openai

Revision ID: 2a6f7c9d4b11
Revises: d16b4c8e91fa
Create Date: 2026-04-17 02:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2a6f7c9d4b11"
down_revision: Union[str, Sequence[str], None] = "d16b4c8e91fa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE conta_mae_invite_job_status ADD VALUE IF NOT EXISTS 'RETRY_WAIT'")
    op.add_column("contamaeinvitejob", sa.Column("next_retry_at", sa.DateTime(), nullable=True))
    op.create_index(op.f("ix_contamaeinvitejob_next_retry_at"), "contamaeinvitejob", ["next_retry_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_contamaeinvitejob_next_retry_at"), table_name="contamaeinvitejob")
    op.drop_column("contamaeinvitejob", "next_retry_at")
