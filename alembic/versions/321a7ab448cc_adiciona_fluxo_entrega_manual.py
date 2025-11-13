"""adiciona_fluxo_entrega_manual

Revision ID: 321a7ab448cc
Revises: bf72222b27c8
Create Date: 2025-11-13 09:25:00.000000 

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '321a7ab448cc'
down_revision: Union[str, Sequence[str], None] = 'bf72222b27c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# --- INÍCIO DA MUDANÇA ---
# Definimos os nossos novos tipos ENUM aqui
tipo_entrega_enum = sa.Enum('AUTOMATICA', 'SOLICITA_EMAIL', 'MANUAL_ADMIN', name='tipoentregaproduto')
status_entrega_enum = sa.Enum('ENTREGUE', 'PENDENTE', name='statusentregapedido')
# --- FIM DA MUDANÇA ---


def upgrade() -> None:
    """Upgrade schema."""
    # --- INÍCIO DA MUDANÇA ---
    # 1. Criamos os tipos ENUM no banco de dados PRIMEIRO
    tipo_entrega_enum.create(op.get_bind())
    status_entrega_enum.create(op.get_bind())
    
    # 2. Agora podemos adicionar as colunas que usam esses tipos
    op.add_column('pedido', sa.Column(
        'status_entrega',
        status_entrega_enum,
        nullable=False,
        server_default='ENTREGUE'  # Adiciona o valor padrão do model
    ))
    
    op.add_column('produto', sa.Column(
        'tipo_entrega',
        tipo_entrega_enum,
        nullable=False,
        server_default='AUTOMATICA' # Adiciona o valor padrão do model
    ))
    
    # 3. Finalmente, removemos a coluna antiga
    op.drop_column('produto', 'requer_email_cliente')
    # --- FIM DA MUDANÇA ---


def downgrade() -> None:
    """Downgrade schema."""
    # --- INÍCIO DA MUDANÇA ---
    # A ordem aqui é o OPOSTO do upgrade
    
    # 1. Recria a coluna antiga
    op.add_column('produto', sa.Column(
        'requer_email_cliente', 
        sa.Boolean(), 
        nullable=False, 
        # Restaura o server_default que existia antes
        server_default=sa.text('false') 
    ))
    
    # 2. Remove as colunas novas
    op.drop_column('produto', 'tipo_entrega')
    op.drop_column('pedido', 'status_entrega')
    
    # 3. Remove os tipos ENUM do banco de dados
    tipo_entrega_enum.drop(op.get_bind())
    status_entrega_enum.drop(op.get_bind())
    # --- FIM DA MUDANÇA ---