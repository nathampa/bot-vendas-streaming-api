"""adiciona_historico_ajustes_saldo

Revision ID: e2a9c1f4d5b6
Revises: 8caf5b1b2c7e
Create Date: 2026-02-21 21:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e2a9c1f4d5b6"
down_revision: Union[str, Sequence[str], None] = "8caf5b1b2c7e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ajustesaldousuario",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "operacao",
            sa.Enum("ADICIONAR", "REMOVER", "DEFINIR", name="tipooperacaoajustesaldo"),
            nullable=False,
        ),
        sa.Column("valor", sa.Numeric(10, 2), nullable=False),
        sa.Column("saldo_anterior", sa.Numeric(10, 2), nullable=False),
        sa.Column("saldo_atual", sa.Numeric(10, 2), nullable=False),
        sa.Column("motivo", sa.String(length=240), nullable=True),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.Column("usuario_id", sa.UUID(), nullable=False),
        sa.Column("admin_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuario.id"]),
        sa.ForeignKeyConstraint(["admin_id"], ["usuario.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ajustesaldousuario_usuario_id", "ajustesaldousuario", ["usuario_id"])
    op.create_index("ix_ajustesaldousuario_admin_id", "ajustesaldousuario", ["admin_id"])
    op.create_index("ix_ajustesaldousuario_criado_em", "ajustesaldousuario", ["criado_em"])


def downgrade() -> None:
    op.drop_index("ix_ajustesaldousuario_criado_em", table_name="ajustesaldousuario")
    op.drop_index("ix_ajustesaldousuario_admin_id", table_name="ajustesaldousuario")
    op.drop_index("ix_ajustesaldousuario_usuario_id", table_name="ajustesaldousuario")
    op.drop_table("ajustesaldousuario")
    op.execute("DROP TYPE IF EXISTS tipooperacaoajustesaldo")
