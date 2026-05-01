"""adiciona credenciais outlook na criacao openai

Revision ID: c31f8a9d7e2b
Revises: b18d6a7c4f21
Create Date: 2026-05-01 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c31f8a9d7e2b"
down_revision: Union[str, Sequence[str], None] = "b18d6a7c4f21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "openaiaccountcreationrequest",
        sa.Column("outlook_email", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "openaiaccountcreationrequest",
        sa.Column("outlook_password_encrypted", sa.String(length=1200), nullable=True),
    )
    op.create_index(
        op.f("ix_openaiaccountcreationrequest_outlook_email"),
        "openaiaccountcreationrequest",
        ["outlook_email"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_openaiaccountcreationrequest_outlook_email"), table_name="openaiaccountcreationrequest")
    op.drop_column("openaiaccountcreationrequest", "outlook_password_encrypted")
    op.drop_column("openaiaccountcreationrequest", "outlook_email")
