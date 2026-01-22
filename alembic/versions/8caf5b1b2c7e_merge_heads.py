"""merge heads

Revision ID: 8caf5b1b2c7e
Revises: c1d5e6a7b9f0, xxxx
Create Date: 2026-01-22 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '8caf5b1b2c7e'
down_revision: Union[str, Sequence[str], None] = ('c1d5e6a7b9f0', 'xxxx')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
