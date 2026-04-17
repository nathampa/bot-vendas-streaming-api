"""adiciona invite_provider ao produto

Revision ID: c7f9e2a1b3c4
Revises: 3b7d2c4e5f61, 9d1a2b3c4d5e
Create Date: 2026-04-17 13:40:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c7f9e2a1b3c4"
down_revision: Union[str, Sequence[str], None] = ("3b7d2c4e5f61", "9d1a2b3c4d5e")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    invite_provider_enum = postgresql.ENUM(
        "NONE",
        "OPENAI",
        name="invite_provider_produto",
        create_type=False,
    )
    bind = op.get_bind()
    invite_provider_enum.create(bind, checkfirst=True)

    op.add_column(
        "produto",
        sa.Column(
            "invite_provider",
            invite_provider_enum,
            nullable=False,
            server_default="NONE",
        ),
    )
    op.alter_column("produto", "invite_provider", server_default=None)


def downgrade() -> None:
    op.drop_column("produto", "invite_provider")
    bind = op.get_bind()
    postgresql.ENUM(name="invite_provider_produto").drop(bind, checkfirst=True)
