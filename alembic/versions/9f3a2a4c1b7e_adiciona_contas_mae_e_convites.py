"""adiciona_contas_mae_e_convites

Revision ID: 9f3a2a4c1b7e
Revises: b6d2d4d3a7e1
Create Date: 2026-01-22 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9f3a2a4c1b7e'
down_revision: Union[str, Sequence[str], None] = 'b6d2d4d3a7e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'contamae',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('login', sa.String(), nullable=False),
        sa.Column('senha', sa.String(), nullable=False),
        sa.Column('is_ativo', sa.Boolean(), nullable=False),
        sa.Column('data_expiracao', sa.Date(), nullable=True),
        sa.Column('criado_em', sa.DateTime(), nullable=False),
        sa.Column('atualizado_em', sa.DateTime(), nullable=False),
        sa.Column('produto_id', sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(['produto_id'], ['produto.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_contamae_login', 'contamae', ['login'])

    op.create_table(
        'contamaeconvite',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('email_cliente', sa.String(), nullable=False),
        sa.Column('criado_em', sa.DateTime(), nullable=False),
        sa.Column('conta_mae_id', sa.UUID(), nullable=False),
        sa.Column('pedido_id', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['conta_mae_id'], ['contamae.id']),
        sa.ForeignKeyConstraint(['pedido_id'], ['pedido.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_contamaeconvite_email_cliente', 'contamaeconvite', ['email_cliente'])

    op.add_column('pedido', sa.Column('conta_mae_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_pedido_conta_mae_id_contamae',
        'pedido',
        'contamae',
        ['conta_mae_id'],
        ['id']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_pedido_conta_mae_id_contamae', 'pedido', type_='foreignkey')
    op.drop_column('pedido', 'conta_mae_id')

    op.drop_index('ix_contamaeconvite_email_cliente', table_name='contamaeconvite')
    op.drop_table('contamaeconvite')

    op.drop_index('ix_contamae_login', table_name='contamae')
    op.drop_table('contamae')
