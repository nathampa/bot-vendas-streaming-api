"""adiciona instrucoes especificas ao estoque

Revision ID: xxxx
Revises: 321a7ab448cc
Create Date: 2025-11-28 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ATENÇÃO: Substitua 'xxxx' pelo ID gerado automaticamente se usar o comando alembic revision
revision: str = 'xxxx_adiciona_instrucoes_especificas'
down_revision: Union[str, Sequence[str], None] = '321a7ab448cc' # Aponta para a última revisão conhecida
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Adiciona a coluna 'instrucoes_especificas' na tabela 'estoqueconta'
    op.add_column('estoqueconta', sa.Column('instrucoes_especificas', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # Remove a coluna em caso de rollback
    op.drop_column('estoqueconta', 'instrucoes_especificas')