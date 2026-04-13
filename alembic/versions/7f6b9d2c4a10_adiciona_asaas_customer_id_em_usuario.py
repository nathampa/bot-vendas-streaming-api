"""adiciona_asaas_customer_id_em_usuario

Revision ID: 7f6b9d2c4a10
Revises: f1c2d3e4b5a6
Create Date: 2026-04-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7f6b9d2c4a10"
down_revision: Union[str, Sequence[str], None] = "f1c2d3e4b5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("usuario", sa.Column("asaas_customer_id", sa.String(), nullable=True))
    op.create_index("ix_usuario_asaas_customer_id", "usuario", ["asaas_customer_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_usuario_asaas_customer_id", table_name="usuario")
    op.drop_column("usuario", "asaas_customer_id")
