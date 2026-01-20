"""torna_ticket_estoque_id_opcional

Revision ID: b6d2d4d3a7e1
Revises: 4d237e3b5ee6
Create Date: 2026-01-20 10:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b6d2d4d3a7e1'
down_revision: Union[str, Sequence[str], None] = '4d237e3b5ee6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('ticketsuporte', 'estoque_conta_id',
               existing_type=sa.UUID(),
               nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('ticketsuporte', 'estoque_conta_id',
               existing_type=sa.UUID(),
               nullable=False)
