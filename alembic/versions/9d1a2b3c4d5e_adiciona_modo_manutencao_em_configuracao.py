"""adiciona modo manutencao em configuracao

Revision ID: 9d1a2b3c4d5e
Revises: 5b7a91c2d4e6
Create Date: 2026-04-14 02:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "9d1a2b3c4d5e"
down_revision = "5b7a91c2d4e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("configuracao", sa.Column("modo_manutencao", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column("configuracao", "modo_manutencao", server_default=None)


def downgrade() -> None:
    op.drop_column("configuracao", "modo_manutencao")
