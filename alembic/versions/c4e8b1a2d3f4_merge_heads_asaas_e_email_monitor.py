"""merge_heads_asaas_e_email_monitor

Revision ID: c4e8b1a2d3f4
Revises: f1c2d3e4b5a6, 7f6b9d2c4a10
Create Date: 2026-04-13 00:10:00.000000

"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "c4e8b1a2d3f4"
down_revision: Union[str, Sequence[str], None] = ("f1c2d3e4b5a6", "7f6b9d2c4a10")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
