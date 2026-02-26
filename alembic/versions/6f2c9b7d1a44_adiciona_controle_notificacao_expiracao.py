"""adiciona_controle_notificacao_expiracao

Revision ID: 6f2c9b7d1a44
Revises: e2a9c1f4d5b6
Create Date: 2026-02-26 20:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6f2c9b7d1a44"
down_revision: Union[str, Sequence[str], None] = "e2a9c1f4d5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "pedido",
        sa.Column("ultima_data_expiracao_notificada", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("pedido", "ultima_data_expiracao_notificada")
