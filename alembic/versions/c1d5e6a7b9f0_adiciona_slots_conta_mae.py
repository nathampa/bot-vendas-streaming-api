"""adiciona_slots_conta_mae

Revision ID: c1d5e6a7b9f0
Revises: 9f3a2a4c1b7e
Create Date: 2026-01-22 20:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1d5e6a7b9f0'
down_revision: Union[str, Sequence[str], None] = '9f3a2a4c1b7e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('contamae', sa.Column('max_slots', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('contamae', sa.Column('slots_ocupados', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('contamae', 'slots_ocupados')
    op.drop_column('contamae', 'max_slots')
