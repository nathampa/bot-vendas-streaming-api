"""adiciona_cpf_cnpj_em_usuario

Revision ID: 5b7a91c2d4e6
Revises: c4e8b1a2d3f4
Create Date: 2026-04-13 02:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5b7a91c2d4e6"
down_revision: Union[str, Sequence[str], None] = "c4e8b1a2d3f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("usuario", sa.Column("cpf_cnpj", sa.String(), nullable=True))
    op.create_index("ix_usuario_cpf_cnpj", "usuario", ["cpf_cnpj"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_usuario_cpf_cnpj", table_name="usuario")
    op.drop_column("usuario", "cpf_cnpj")
