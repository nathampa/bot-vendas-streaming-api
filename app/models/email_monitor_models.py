import datetime
import enum
import uuid
from typing import Optional

import sqlalchemy as sa
from sqlmodel import Field, Relationship, SQLModel


class EmailMonitorSyncStatus(str, enum.Enum):
    IDLE = "IDLE"
    SYNCING = "SYNCING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    DISABLED = "DISABLED"


class EmailMonitorSyncRunStatus(str, enum.Enum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class EmailMonitorWebhookStatus(str, enum.Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_logs"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    actor_usuario_id: Optional[uuid.UUID] = Field(default=None, foreign_key="usuario.id", index=True)
    event_type: str = Field(nullable=False, index=True, max_length=80)
    resource_type: str = Field(nullable=False, index=True, max_length=80)
    resource_id: Optional[str] = Field(default=None, index=True, max_length=120)
    message: str = Field(nullable=False, max_length=400)
    metadata_json: dict = Field(default_factory=dict, sa_column=sa.Column(sa.JSON(), nullable=False))
    ip_address: Optional[str] = Field(default=None, max_length=80)
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False, index=True)


class EmailMonitorAccount(SQLModel, table=True):
    __tablename__ = "email_monitor_accounts"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_usuario_id: Optional[uuid.UUID] = Field(default=None, foreign_key="usuario.id", index=True)
    display_name: str = Field(nullable=False, max_length=120)
    email: str = Field(nullable=False, index=True, max_length=255)
    imap_host: str = Field(nullable=False, max_length=255)
    imap_port: int = Field(default=993, nullable=False)
    imap_username: str = Field(nullable=False, max_length=255)
    imap_password_encrypted: str = Field(nullable=False)
    use_ssl: bool = Field(default=True, nullable=False)
    is_active: bool = Field(default=True, nullable=False, index=True)
    selected_folders_json: list[str] = Field(
        default_factory=lambda: ["INBOX"],
        sa_column=sa.Column(sa.JSON(), nullable=False),
    )
    sync_interval_minutes: int = Field(default=5, nullable=False)
    retain_irrelevant_days: int = Field(default=3, nullable=False)
    last_synced_at: Optional[datetime.datetime] = Field(default=None, index=True)
    last_success_at: Optional[datetime.datetime] = Field(default=None, index=True)
    last_error_at: Optional[datetime.datetime] = Field(default=None)
    last_error_message: Optional[str] = Field(default=None, max_length=500)
    last_outlook_otp_status: Optional[str] = Field(default=None, max_length=40)
    last_outlook_otp_code_encrypted: Optional[str] = Field(default=None)
    last_outlook_otp_fetched_at: Optional[datetime.datetime] = Field(default=None)
    last_outlook_otp_error_message: Optional[str] = Field(default=None, max_length=500)
    last_outlook_otp_evidence_path: Optional[str] = Field(default=None, max_length=1000)
    outlook_otp_fetch_locked_at: Optional[datetime.datetime] = Field(default=None)
    consecutive_failures: int = Field(default=0, nullable=False)
    next_retry_at: Optional[datetime.datetime] = Field(default=None, index=True)
    sync_status: EmailMonitorSyncStatus = Field(
        default=EmailMonitorSyncStatus.IDLE,
        sa_column=sa.Column(sa.Enum(EmailMonitorSyncStatus, name="email_monitor_sync_status"), nullable=False),
    )
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False)
    updated_at: datetime.datetime = Field(
        default_factory=datetime.datetime.utcnow,
        nullable=False,
        sa_column_kwargs={"onupdate": datetime.datetime.utcnow},
    )

    folder_states: list["EmailMonitorFolderState"] = Relationship(back_populates="account")
    rules: list["EmailMonitorRule"] = Relationship(back_populates="account")
    messages: list["EmailMonitorMessage"] = Relationship(back_populates="account")
    sync_runs: list["EmailMonitorSyncRun"] = Relationship(back_populates="account")
    alerts: list["EmailMonitorAlertEvent"] = Relationship(back_populates="account")


class EmailMonitorFolderState(SQLModel, table=True):
    __tablename__ = "email_monitor_folder_states"
    __table_args__ = (sa.UniqueConstraint("account_id", "folder_name", name="uq_email_monitor_folder_state"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    account_id: uuid.UUID = Field(foreign_key="email_monitor_accounts.id", nullable=False, index=True)
    folder_name: str = Field(nullable=False, max_length=255)
    last_seen_uid: Optional[int] = Field(default=None)
    last_seen_internaldate: Optional[datetime.datetime] = Field(default=None)
    last_seen_message_id: Optional[str] = Field(default=None, max_length=255)
    last_synced_at: Optional[datetime.datetime] = Field(default=None, index=True)
    last_success_at: Optional[datetime.datetime] = Field(default=None)
    last_error_at: Optional[datetime.datetime] = Field(default=None)
    last_error_message: Optional[str] = Field(default=None, max_length=500)
    consecutive_failures: int = Field(default=0, nullable=False)
    next_retry_at: Optional[datetime.datetime] = Field(default=None)
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False)
    updated_at: datetime.datetime = Field(
        default_factory=datetime.datetime.utcnow,
        nullable=False,
        sa_column_kwargs={"onupdate": datetime.datetime.utcnow},
    )

    account: EmailMonitorAccount = Relationship(back_populates="folder_states")


class EmailMonitorRule(SQLModel, table=True):
    __tablename__ = "email_monitor_rules"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_usuario_id: Optional[uuid.UUID] = Field(default=None, foreign_key="usuario.id", index=True)
    account_id: Optional[uuid.UUID] = Field(default=None, foreign_key="email_monitor_accounts.id", index=True)
    name: str = Field(nullable=False, max_length=120)
    sender_pattern: Optional[str] = Field(default=None, max_length=255)
    subject_pattern: Optional[str] = Field(default=None, max_length=255)
    body_keywords_json: list[str] = Field(default_factory=list, sa_column=sa.Column(sa.JSON(), nullable=False))
    folder_pattern: Optional[str] = Field(default=None, max_length=255)
    category: Optional[str] = Field(default=None, max_length=120)
    mark_relevant: bool = Field(default=True, nullable=False)
    raise_dashboard_alert: bool = Field(default=False, nullable=False)
    highlight: bool = Field(default=False, nullable=False)
    enabled: bool = Field(default=True, nullable=False, index=True)
    priority: int = Field(default=100, nullable=False, index=True)
    webhook_url: Optional[str] = Field(default=None, max_length=500)
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False)
    updated_at: datetime.datetime = Field(
        default_factory=datetime.datetime.utcnow,
        nullable=False,
        sa_column_kwargs={"onupdate": datetime.datetime.utcnow},
    )

    account: Optional[EmailMonitorAccount] = Relationship(back_populates="rules")
    matches: list["EmailMonitorMessageMatch"] = Relationship(back_populates="rule")
    alerts: list["EmailMonitorAlertEvent"] = Relationship(back_populates="rule")


class EmailMonitorMessage(SQLModel, table=True):
    __tablename__ = "email_monitor_messages"
    __table_args__ = (
        sa.UniqueConstraint("account_id", "folder_name", "message_uid", name="uq_email_monitor_message_uid"),
        sa.Index("ix_email_monitor_message_account_message_hash", "account_id", "message_id_hash"),
        sa.Index("ix_email_monitor_message_category_sent", "category", "sent_at"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    account_id: uuid.UUID = Field(foreign_key="email_monitor_accounts.id", nullable=False, index=True)
    matched_rule_id: Optional[uuid.UUID] = Field(default=None, foreign_key="email_monitor_rules.id", index=True)
    folder_name: str = Field(nullable=False, max_length=255, index=True)
    message_uid: int = Field(nullable=False)
    message_id: Optional[str] = Field(default=None, max_length=255)
    message_id_hash: str = Field(nullable=False, max_length=64)
    sender_name: Optional[str] = Field(default=None, max_length=255)
    sender_email: Optional[str] = Field(default=None, max_length=255, index=True)
    recipient_email: Optional[str] = Field(default=None, max_length=255)
    subject: Optional[str] = Field(default=None, max_length=500, index=True)
    sent_at: Optional[datetime.datetime] = Field(default=None, index=True)
    internal_date: Optional[datetime.datetime] = Field(default=None, index=True)
    headers_json: dict = Field(default_factory=dict, sa_column=sa.Column(sa.JSON(), nullable=False))
    body_text: Optional[str] = Field(default=None, sa_column=sa.Column(sa.Text(), nullable=True))
    body_html_sanitized: Optional[str] = Field(default=None, sa_column=sa.Column(sa.Text(), nullable=True))
    body_preview: Optional[str] = Field(default=None, max_length=500)
    raw_size_bytes: int = Field(default=0, nullable=False)
    body_hash: str = Field(nullable=False, max_length=64, index=True)
    is_relevant: bool = Field(default=False, nullable=False, index=True)
    is_read_remote: bool = Field(default=False, nullable=False)
    is_read_internal: bool = Field(default=False, nullable=False, index=True)
    is_archived: bool = Field(default=False, nullable=False, index=True)
    is_highlighted: bool = Field(default=False, nullable=False)
    category: Optional[str] = Field(default=None, max_length=120, index=True)
    matched_rule_name: Optional[str] = Field(default=None, max_length=120)
    matched_at: Optional[datetime.datetime] = Field(default=None)
    provider_message_url: Optional[str] = Field(default=None, max_length=500)
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False)
    updated_at: datetime.datetime = Field(
        default_factory=datetime.datetime.utcnow,
        nullable=False,
        sa_column_kwargs={"onupdate": datetime.datetime.utcnow},
    )

    account: EmailMonitorAccount = Relationship(back_populates="messages")
    matches: list["EmailMonitorMessageMatch"] = Relationship(back_populates="message")
    alerts: list["EmailMonitorAlertEvent"] = Relationship(back_populates="message")


class EmailMonitorMessageMatch(SQLModel, table=True):
    __tablename__ = "email_monitor_message_matches"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    message_id: uuid.UUID = Field(foreign_key="email_monitor_messages.id", nullable=False, index=True)
    rule_id: uuid.UUID = Field(foreign_key="email_monitor_rules.id", nullable=False, index=True)
    matched_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False)
    reason_summary: str = Field(nullable=False, max_length=255)
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False)

    message: EmailMonitorMessage = Relationship(back_populates="matches")
    rule: EmailMonitorRule = Relationship(back_populates="matches")


class EmailMonitorAlertEvent(SQLModel, table=True):
    __tablename__ = "email_monitor_alert_events"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    account_id: uuid.UUID = Field(foreign_key="email_monitor_accounts.id", nullable=False, index=True)
    message_id: uuid.UUID = Field(foreign_key="email_monitor_messages.id", nullable=False, index=True)
    rule_id: Optional[uuid.UUID] = Field(default=None, foreign_key="email_monitor_rules.id", index=True)
    category: Optional[str] = Field(default=None, max_length=120)
    sender_email: Optional[str] = Field(default=None, max_length=255)
    subject: Optional[str] = Field(default=None, max_length=500)
    is_read: bool = Field(default=False, nullable=False, index=True)
    webhook_status: EmailMonitorWebhookStatus = Field(
        default=EmailMonitorWebhookStatus.PENDING,
        sa_column=sa.Column(sa.Enum(EmailMonitorWebhookStatus, name="email_monitor_webhook_status"), nullable=False),
    )
    webhook_error: Optional[str] = Field(default=None, max_length=500)
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False, index=True)

    account: EmailMonitorAccount = Relationship(back_populates="alerts")
    message: EmailMonitorMessage = Relationship(back_populates="alerts")
    rule: Optional[EmailMonitorRule] = Relationship(back_populates="alerts")


class EmailMonitorSyncRun(SQLModel, table=True):
    __tablename__ = "email_monitor_sync_runs"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    account_id: uuid.UUID = Field(foreign_key="email_monitor_accounts.id", nullable=False, index=True)
    trigger_source: str = Field(default="manual", nullable=False, max_length=40)
    status: EmailMonitorSyncRunStatus = Field(
        default=EmailMonitorSyncRunStatus.RUNNING,
        sa_column=sa.Column(sa.Enum(EmailMonitorSyncRunStatus, name="email_monitor_sync_run_status"), nullable=False),
    )
    started_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False, index=True)
    finished_at: Optional[datetime.datetime] = Field(default=None)
    folders_scanned: int = Field(default=0, nullable=False)
    messages_scanned: int = Field(default=0, nullable=False)
    messages_saved: int = Field(default=0, nullable=False)
    relevant_messages: int = Field(default=0, nullable=False)
    error_message: Optional[str] = Field(default=None, max_length=500)

    account: EmailMonitorAccount = Relationship(back_populates="sync_runs")
