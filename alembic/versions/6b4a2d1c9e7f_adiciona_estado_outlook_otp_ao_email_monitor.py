"""adiciona estado outlook otp ao email monitor

Revision ID: 6b4a2d1c9e7f
Revises: c31f8a9d7e2b
Create Date: 2026-05-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "6b4a2d1c9e7f"
down_revision = "c31f8a9d7e2b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "email_monitor_accounts",
        sa.Column("last_outlook_otp_status", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "email_monitor_accounts",
        sa.Column("last_outlook_otp_code_encrypted", sa.Text(), nullable=True),
    )
    op.add_column(
        "email_monitor_accounts",
        sa.Column("last_outlook_otp_fetched_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "email_monitor_accounts",
        sa.Column("last_outlook_otp_error_message", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "email_monitor_accounts",
        sa.Column("last_outlook_otp_evidence_path", sa.String(length=1000), nullable=True),
    )
    op.add_column(
        "email_monitor_accounts",
        sa.Column("outlook_otp_fetch_locked_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("email_monitor_accounts", "outlook_otp_fetch_locked_at")
    op.drop_column("email_monitor_accounts", "last_outlook_otp_evidence_path")
    op.drop_column("email_monitor_accounts", "last_outlook_otp_error_message")
    op.drop_column("email_monitor_accounts", "last_outlook_otp_fetched_at")
    op.drop_column("email_monitor_accounts", "last_outlook_otp_code_encrypted")
    op.drop_column("email_monitor_accounts", "last_outlook_otp_status")
