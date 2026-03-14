"""adiciona modulo email monitor

Revision ID: f1c2d3e4b5a6
Revises: 6f2c9b7d1a44
Create Date: 2025-03-14 02:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f1c2d3e4b5a6'
down_revision: Union[str, Sequence[str], None] = '6f2c9b7d1a44'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    sync_status_enum = postgresql.ENUM('IDLE', 'SYNCING', 'SUCCESS', 'FAILED', 'DISABLED', name='email_monitor_sync_status', create_type=False)
    sync_run_status_enum = postgresql.ENUM('RUNNING', 'SUCCESS', 'FAILED', name='email_monitor_sync_run_status', create_type=False)
    webhook_status_enum = postgresql.ENUM('PENDING', 'SENT', 'FAILED', 'SKIPPED', name='email_monitor_webhook_status', create_type=False)

    bind = op.get_bind()
    sync_status_enum.create(bind, checkfirst=True)
    sync_run_status_enum.create(bind, checkfirst=True)
    webhook_status_enum.create(bind, checkfirst=True)

    op.create_table(
        'audit_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('actor_usuario_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('event_type', sa.String(length=80), nullable=False),
        sa.Column('resource_type', sa.String(length=80), nullable=False),
        sa.Column('resource_id', sa.String(length=120), nullable=True),
        sa.Column('message', sa.String(length=400), nullable=False),
        sa.Column('metadata_json', sa.JSON(), nullable=False),
        sa.Column('ip_address', sa.String(length=80), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['actor_usuario_id'], ['usuario.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_audit_logs_actor_usuario_id'), 'audit_logs', ['actor_usuario_id'], unique=False)
    op.create_index(op.f('ix_audit_logs_created_at'), 'audit_logs', ['created_at'], unique=False)
    op.create_index(op.f('ix_audit_logs_event_type'), 'audit_logs', ['event_type'], unique=False)
    op.create_index(op.f('ix_audit_logs_resource_id'), 'audit_logs', ['resource_id'], unique=False)
    op.create_index(op.f('ix_audit_logs_resource_type'), 'audit_logs', ['resource_type'], unique=False)

    op.create_table(
        'email_monitor_accounts',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('owner_usuario_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('display_name', sa.String(length=120), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('imap_host', sa.String(length=255), nullable=False),
        sa.Column('imap_port', sa.Integer(), nullable=False),
        sa.Column('imap_username', sa.String(length=255), nullable=False),
        sa.Column('imap_password_encrypted', sa.Text(), nullable=False),
        sa.Column('use_ssl', sa.Boolean(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('selected_folders_json', sa.JSON(), nullable=False),
        sa.Column('sync_interval_minutes', sa.Integer(), nullable=False),
        sa.Column('retain_irrelevant_days', sa.Integer(), nullable=False),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.Column('last_success_at', sa.DateTime(), nullable=True),
        sa.Column('last_error_at', sa.DateTime(), nullable=True),
        sa.Column('last_error_message', sa.String(length=500), nullable=True),
        sa.Column('consecutive_failures', sa.Integer(), nullable=False),
        sa.Column('next_retry_at', sa.DateTime(), nullable=True),
        sa.Column('sync_status', sync_status_enum, nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['owner_usuario_id'], ['usuario.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_email_monitor_accounts_email'), 'email_monitor_accounts', ['email'], unique=False)
    op.create_index(op.f('ix_email_monitor_accounts_is_active'), 'email_monitor_accounts', ['is_active'], unique=False)
    op.create_index(op.f('ix_email_monitor_accounts_last_success_at'), 'email_monitor_accounts', ['last_success_at'], unique=False)
    op.create_index(op.f('ix_email_monitor_accounts_last_synced_at'), 'email_monitor_accounts', ['last_synced_at'], unique=False)
    op.create_index(op.f('ix_email_monitor_accounts_next_retry_at'), 'email_monitor_accounts', ['next_retry_at'], unique=False)
    op.create_index(op.f('ix_email_monitor_accounts_owner_usuario_id'), 'email_monitor_accounts', ['owner_usuario_id'], unique=False)

    op.create_table(
        'email_monitor_folder_states',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('folder_name', sa.String(length=255), nullable=False),
        sa.Column('last_seen_uid', sa.Integer(), nullable=True),
        sa.Column('last_seen_internaldate', sa.DateTime(), nullable=True),
        sa.Column('last_seen_message_id', sa.String(length=255), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.Column('last_success_at', sa.DateTime(), nullable=True),
        sa.Column('last_error_at', sa.DateTime(), nullable=True),
        sa.Column('last_error_message', sa.String(length=500), nullable=True),
        sa.Column('consecutive_failures', sa.Integer(), nullable=False),
        sa.Column('next_retry_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['email_monitor_accounts.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('account_id', 'folder_name', name='uq_email_monitor_folder_state'),
    )
    op.create_index(op.f('ix_email_monitor_folder_states_account_id'), 'email_monitor_folder_states', ['account_id'], unique=False)
    op.create_index(op.f('ix_email_monitor_folder_states_last_synced_at'), 'email_monitor_folder_states', ['last_synced_at'], unique=False)

    op.create_table(
        'email_monitor_rules',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('owner_usuario_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('sender_pattern', sa.String(length=255), nullable=True),
        sa.Column('subject_pattern', sa.String(length=255), nullable=True),
        sa.Column('body_keywords_json', sa.JSON(), nullable=False),
        sa.Column('folder_pattern', sa.String(length=255), nullable=True),
        sa.Column('category', sa.String(length=120), nullable=True),
        sa.Column('mark_relevant', sa.Boolean(), nullable=False),
        sa.Column('raise_dashboard_alert', sa.Boolean(), nullable=False),
        sa.Column('highlight', sa.Boolean(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('webhook_url', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['email_monitor_accounts.id']),
        sa.ForeignKeyConstraint(['owner_usuario_id'], ['usuario.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_email_monitor_rules_account_id'), 'email_monitor_rules', ['account_id'], unique=False)
    op.create_index(op.f('ix_email_monitor_rules_enabled'), 'email_monitor_rules', ['enabled'], unique=False)
    op.create_index(op.f('ix_email_monitor_rules_owner_usuario_id'), 'email_monitor_rules', ['owner_usuario_id'], unique=False)
    op.create_index(op.f('ix_email_monitor_rules_priority'), 'email_monitor_rules', ['priority'], unique=False)

    op.create_table(
        'email_monitor_messages',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('matched_rule_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('folder_name', sa.String(length=255), nullable=False),
        sa.Column('message_uid', sa.Integer(), nullable=False),
        sa.Column('message_id', sa.String(length=255), nullable=True),
        sa.Column('message_id_hash', sa.String(length=64), nullable=False),
        sa.Column('sender_name', sa.String(length=255), nullable=True),
        sa.Column('sender_email', sa.String(length=255), nullable=True),
        sa.Column('recipient_email', sa.String(length=255), nullable=True),
        sa.Column('subject', sa.String(length=500), nullable=True),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('internal_date', sa.DateTime(), nullable=True),
        sa.Column('headers_json', sa.JSON(), nullable=False),
        sa.Column('body_text', sa.Text(), nullable=True),
        sa.Column('body_html_sanitized', sa.Text(), nullable=True),
        sa.Column('body_preview', sa.String(length=500), nullable=True),
        sa.Column('raw_size_bytes', sa.Integer(), nullable=False),
        sa.Column('body_hash', sa.String(length=64), nullable=False),
        sa.Column('is_relevant', sa.Boolean(), nullable=False),
        sa.Column('is_read_remote', sa.Boolean(), nullable=False),
        sa.Column('is_read_internal', sa.Boolean(), nullable=False),
        sa.Column('is_archived', sa.Boolean(), nullable=False),
        sa.Column('is_highlighted', sa.Boolean(), nullable=False),
        sa.Column('category', sa.String(length=120), nullable=True),
        sa.Column('matched_rule_name', sa.String(length=120), nullable=True),
        sa.Column('matched_at', sa.DateTime(), nullable=True),
        sa.Column('provider_message_url', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['email_monitor_accounts.id']),
        sa.ForeignKeyConstraint(['matched_rule_id'], ['email_monitor_rules.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('account_id', 'folder_name', 'message_uid', name='uq_email_monitor_message_uid'),
    )
    op.create_index(op.f('ix_email_monitor_messages_account_id'), 'email_monitor_messages', ['account_id'], unique=False)
    op.create_index(op.f('ix_email_monitor_messages_body_hash'), 'email_monitor_messages', ['body_hash'], unique=False)
    op.create_index('ix_email_monitor_message_account_message_hash', 'email_monitor_messages', ['account_id', 'message_id_hash'], unique=False)
    op.create_index('ix_email_monitor_message_category_sent', 'email_monitor_messages', ['category', 'sent_at'], unique=False)
    op.create_index(op.f('ix_email_monitor_messages_category'), 'email_monitor_messages', ['category'], unique=False)
    op.create_index(op.f('ix_email_monitor_messages_folder_name'), 'email_monitor_messages', ['folder_name'], unique=False)
    op.create_index(op.f('ix_email_monitor_messages_is_archived'), 'email_monitor_messages', ['is_archived'], unique=False)
    op.create_index(op.f('ix_email_monitor_messages_is_read_internal'), 'email_monitor_messages', ['is_read_internal'], unique=False)
    op.create_index(op.f('ix_email_monitor_messages_is_relevant'), 'email_monitor_messages', ['is_relevant'], unique=False)
    op.create_index(op.f('ix_email_monitor_messages_matched_rule_id'), 'email_monitor_messages', ['matched_rule_id'], unique=False)
    op.create_index(op.f('ix_email_monitor_messages_sender_email'), 'email_monitor_messages', ['sender_email'], unique=False)
    op.create_index(op.f('ix_email_monitor_messages_sent_at'), 'email_monitor_messages', ['sent_at'], unique=False)
    op.create_index(op.f('ix_email_monitor_messages_subject'), 'email_monitor_messages', ['subject'], unique=False)
    op.create_index(op.f('ix_email_monitor_messages_internal_date'), 'email_monitor_messages', ['internal_date'], unique=False)

    op.create_table(
        'email_monitor_message_matches',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('message_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('rule_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('matched_at', sa.DateTime(), nullable=False),
        sa.Column('reason_summary', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['message_id'], ['email_monitor_messages.id']),
        sa.ForeignKeyConstraint(['rule_id'], ['email_monitor_rules.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_email_monitor_message_matches_message_id'), 'email_monitor_message_matches', ['message_id'], unique=False)
    op.create_index(op.f('ix_email_monitor_message_matches_rule_id'), 'email_monitor_message_matches', ['rule_id'], unique=False)

    op.create_table(
        'email_monitor_alert_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('message_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('rule_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('category', sa.String(length=120), nullable=True),
        sa.Column('sender_email', sa.String(length=255), nullable=True),
        sa.Column('subject', sa.String(length=500), nullable=True),
        sa.Column('is_read', sa.Boolean(), nullable=False),
        sa.Column('webhook_status', webhook_status_enum, nullable=False),
        sa.Column('webhook_error', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['email_monitor_accounts.id']),
        sa.ForeignKeyConstraint(['message_id'], ['email_monitor_messages.id']),
        sa.ForeignKeyConstraint(['rule_id'], ['email_monitor_rules.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_email_monitor_alert_events_account_id'), 'email_monitor_alert_events', ['account_id'], unique=False)
    op.create_index(op.f('ix_email_monitor_alert_events_created_at'), 'email_monitor_alert_events', ['created_at'], unique=False)
    op.create_index(op.f('ix_email_monitor_alert_events_is_read'), 'email_monitor_alert_events', ['is_read'], unique=False)
    op.create_index(op.f('ix_email_monitor_alert_events_message_id'), 'email_monitor_alert_events', ['message_id'], unique=False)
    op.create_index(op.f('ix_email_monitor_alert_events_rule_id'), 'email_monitor_alert_events', ['rule_id'], unique=False)

    op.create_table(
        'email_monitor_sync_runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('trigger_source', sa.String(length=40), nullable=False),
        sa.Column('status', sync_run_status_enum, nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('folders_scanned', sa.Integer(), nullable=False),
        sa.Column('messages_scanned', sa.Integer(), nullable=False),
        sa.Column('messages_saved', sa.Integer(), nullable=False),
        sa.Column('relevant_messages', sa.Integer(), nullable=False),
        sa.Column('error_message', sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(['account_id'], ['email_monitor_accounts.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_email_monitor_sync_runs_account_id'), 'email_monitor_sync_runs', ['account_id'], unique=False)
    op.create_index(op.f('ix_email_monitor_sync_runs_started_at'), 'email_monitor_sync_runs', ['started_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_email_monitor_sync_runs_started_at'), table_name='email_monitor_sync_runs')
    op.drop_index(op.f('ix_email_monitor_sync_runs_account_id'), table_name='email_monitor_sync_runs')
    op.drop_table('email_monitor_sync_runs')

    op.drop_index(op.f('ix_email_monitor_alert_events_rule_id'), table_name='email_monitor_alert_events')
    op.drop_index(op.f('ix_email_monitor_alert_events_message_id'), table_name='email_monitor_alert_events')
    op.drop_index(op.f('ix_email_monitor_alert_events_is_read'), table_name='email_monitor_alert_events')
    op.drop_index(op.f('ix_email_monitor_alert_events_created_at'), table_name='email_monitor_alert_events')
    op.drop_index(op.f('ix_email_monitor_alert_events_account_id'), table_name='email_monitor_alert_events')
    op.drop_table('email_monitor_alert_events')

    op.drop_index(op.f('ix_email_monitor_message_matches_rule_id'), table_name='email_monitor_message_matches')
    op.drop_index(op.f('ix_email_monitor_message_matches_message_id'), table_name='email_monitor_message_matches')
    op.drop_table('email_monitor_message_matches')

    op.drop_index(op.f('ix_email_monitor_messages_internal_date'), table_name='email_monitor_messages')
    op.drop_index(op.f('ix_email_monitor_messages_subject'), table_name='email_monitor_messages')
    op.drop_index(op.f('ix_email_monitor_messages_sent_at'), table_name='email_monitor_messages')
    op.drop_index(op.f('ix_email_monitor_messages_sender_email'), table_name='email_monitor_messages')
    op.drop_index(op.f('ix_email_monitor_messages_matched_rule_id'), table_name='email_monitor_messages')
    op.drop_index(op.f('ix_email_monitor_messages_is_relevant'), table_name='email_monitor_messages')
    op.drop_index(op.f('ix_email_monitor_messages_is_read_internal'), table_name='email_monitor_messages')
    op.drop_index(op.f('ix_email_monitor_messages_is_archived'), table_name='email_monitor_messages')
    op.drop_index(op.f('ix_email_monitor_messages_folder_name'), table_name='email_monitor_messages')
    op.drop_index(op.f('ix_email_monitor_messages_category'), table_name='email_monitor_messages')
    op.drop_index('ix_email_monitor_message_category_sent', table_name='email_monitor_messages')
    op.drop_index('ix_email_monitor_message_account_message_hash', table_name='email_monitor_messages')
    op.drop_index(op.f('ix_email_monitor_messages_body_hash'), table_name='email_monitor_messages')
    op.drop_index(op.f('ix_email_monitor_messages_account_id'), table_name='email_monitor_messages')
    op.drop_table('email_monitor_messages')

    op.drop_index(op.f('ix_email_monitor_rules_priority'), table_name='email_monitor_rules')
    op.drop_index(op.f('ix_email_monitor_rules_owner_usuario_id'), table_name='email_monitor_rules')
    op.drop_index(op.f('ix_email_monitor_rules_enabled'), table_name='email_monitor_rules')
    op.drop_index(op.f('ix_email_monitor_rules_account_id'), table_name='email_monitor_rules')
    op.drop_table('email_monitor_rules')

    op.drop_index(op.f('ix_email_monitor_folder_states_last_synced_at'), table_name='email_monitor_folder_states')
    op.drop_index(op.f('ix_email_monitor_folder_states_account_id'), table_name='email_monitor_folder_states')
    op.drop_table('email_monitor_folder_states')

    op.drop_index(op.f('ix_email_monitor_accounts_owner_usuario_id'), table_name='email_monitor_accounts')
    op.drop_index(op.f('ix_email_monitor_accounts_next_retry_at'), table_name='email_monitor_accounts')
    op.drop_index(op.f('ix_email_monitor_accounts_last_synced_at'), table_name='email_monitor_accounts')
    op.drop_index(op.f('ix_email_monitor_accounts_last_success_at'), table_name='email_monitor_accounts')
    op.drop_index(op.f('ix_email_monitor_accounts_is_active'), table_name='email_monitor_accounts')
    op.drop_index(op.f('ix_email_monitor_accounts_email'), table_name='email_monitor_accounts')
    op.drop_table('email_monitor_accounts')

    op.drop_index(op.f('ix_audit_logs_resource_type'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_resource_id'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_event_type'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_created_at'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_actor_usuario_id'), table_name='audit_logs')
    op.drop_table('audit_logs')

    bind = op.get_bind()
    postgresql.ENUM(name='email_monitor_webhook_status').drop(bind, checkfirst=True)
    postgresql.ENUM(name='email_monitor_sync_run_status').drop(bind, checkfirst=True)
    postgresql.ENUM(name='email_monitor_sync_status').drop(bind, checkfirst=True)
