import datetime
import uuid
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.email_monitor_models import (
    EmailMonitorSyncRunStatus,
    EmailMonitorSyncStatus,
    EmailMonitorWebhookStatus,
)


class EmailMonitorFolderStateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    folder_name: str
    last_seen_uid: Optional[int] = None
    last_synced_at: Optional[datetime.datetime] = None
    last_success_at: Optional[datetime.datetime] = None
    last_error_at: Optional[datetime.datetime] = None
    last_error_message: Optional[str] = None
    consecutive_failures: int
    next_retry_at: Optional[datetime.datetime] = None


class EmailMonitorAccountCreate(BaseModel):
    display_name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=3, max_length=255)
    imap_host: str = Field(min_length=2, max_length=255)
    imap_port: int = Field(ge=1, le=65535)
    imap_username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=255)
    use_ssl: bool = True
    is_active: bool = True
    selected_folders: list[str] = Field(default_factory=lambda: ["INBOX"])
    sync_interval_minutes: int = Field(default=5, ge=1, le=1440)
    retain_irrelevant_days: int = Field(default=3, ge=1, le=365)


class EmailMonitorAccountUpdate(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    email: Optional[str] = Field(default=None, min_length=3, max_length=255)
    imap_host: Optional[str] = Field(default=None, min_length=2, max_length=255)
    imap_port: Optional[int] = Field(default=None, ge=1, le=65535)
    imap_username: Optional[str] = Field(default=None, min_length=1, max_length=255)
    password: Optional[str] = Field(default=None, min_length=1, max_length=255)
    use_ssl: Optional[bool] = None
    is_active: Optional[bool] = None
    selected_folders: Optional[list[str]] = None
    sync_interval_minutes: Optional[int] = Field(default=None, ge=1, le=1440)
    retain_irrelevant_days: Optional[int] = Field(default=None, ge=1, le=365)


class EmailMonitorAccountTestRequest(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=120)
    email: str = Field(min_length=3, max_length=255)
    imap_host: str = Field(min_length=2, max_length=255)
    imap_port: int = Field(ge=1, le=65535)
    imap_username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=255)
    use_ssl: bool = True


class EmailMonitorAccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    display_name: str
    email: str
    imap_host: str
    imap_port: int
    imap_username: str
    use_ssl: bool
    is_active: bool
    selected_folders: list[str]
    sync_interval_minutes: int
    retain_irrelevant_days: int
    last_synced_at: Optional[datetime.datetime] = None
    last_success_at: Optional[datetime.datetime] = None
    last_error_at: Optional[datetime.datetime] = None
    last_error_message: Optional[str] = None
    last_outlook_otp_status: Optional[str] = None
    last_outlook_otp_code: Optional[str] = None
    last_outlook_otp_fetched_at: Optional[datetime.datetime] = None
    last_outlook_otp_error_message: Optional[str] = None
    last_outlook_otp_evidence_path: Optional[str] = None
    outlook_otp_fetch_locked_at: Optional[datetime.datetime] = None
    consecutive_failures: int
    next_retry_at: Optional[datetime.datetime] = None
    sync_status: EmailMonitorSyncStatus
    created_at: datetime.datetime
    updated_at: datetime.datetime
    has_password: bool


class EmailMonitorAccountDetail(EmailMonitorAccountRead):
    folder_states: list[EmailMonitorFolderStateRead] = Field(default_factory=list)


class EmailMonitorConnectionTestResult(BaseModel):
    success: bool
    message: str
    folders: list[str] = Field(default_factory=list)


class EmailMonitorOutlookOtpFetchResponse(BaseModel):
    message: str
    fetch_status: str
    account: EmailMonitorAccountRead


class EmailMonitorRuleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    account_id: Optional[uuid.UUID] = None
    sender_pattern: Optional[str] = Field(default=None, max_length=255)
    subject_pattern: Optional[str] = Field(default=None, max_length=255)
    body_keywords: list[str] = Field(default_factory=list)
    folder_pattern: Optional[str] = Field(default=None, max_length=255)
    category: Optional[str] = Field(default=None, max_length=120)
    mark_relevant: bool = True
    raise_dashboard_alert: bool = False
    highlight: bool = False
    enabled: bool = True
    priority: int = Field(default=100, ge=0, le=10000)
    webhook_url: Optional[str] = Field(default=None, max_length=500)


class EmailMonitorRuleUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    account_id: Optional[uuid.UUID] = None
    sender_pattern: Optional[str] = Field(default=None, max_length=255)
    subject_pattern: Optional[str] = Field(default=None, max_length=255)
    body_keywords: Optional[list[str]] = None
    folder_pattern: Optional[str] = Field(default=None, max_length=255)
    category: Optional[str] = Field(default=None, max_length=120)
    mark_relevant: Optional[bool] = None
    raise_dashboard_alert: Optional[bool] = None
    highlight: Optional[bool] = None
    enabled: Optional[bool] = None
    priority: Optional[int] = Field(default=None, ge=0, le=10000)
    webhook_url: Optional[str] = Field(default=None, max_length=500)


class EmailMonitorRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    account_id: Optional[uuid.UUID] = None
    sender_pattern: Optional[str] = None
    subject_pattern: Optional[str] = None
    body_keywords: list[str] = Field(default_factory=list)
    folder_pattern: Optional[str] = None
    category: Optional[str] = None
    mark_relevant: bool
    raise_dashboard_alert: bool
    highlight: bool
    enabled: bool
    priority: int
    webhook_url: Optional[str] = None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    scope_label: str


class EmailMonitorSyncFailureItem(BaseModel):
    account_id: uuid.UUID
    account_display_name: str
    last_error_at: Optional[datetime.datetime] = None
    last_error_message: Optional[str] = None
    consecutive_failures: int
    next_retry_at: Optional[datetime.datetime] = None


class EmailMonitorAlertItem(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    account_display_name: str
    message_id: uuid.UUID
    category: Optional[str] = None
    sender_email: Optional[str] = None
    subject: Optional[str] = None
    is_read: bool
    webhook_status: EmailMonitorWebhookStatus
    created_at: datetime.datetime


class EmailMonitorOverviewMessageItem(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    account_display_name: str
    sender_email: Optional[str] = None
    subject: Optional[str] = None
    sent_at: Optional[datetime.datetime] = None
    category: Optional[str] = None
    matched_rule_name: Optional[str] = None
    is_read_internal: bool
    is_highlighted: bool


class EmailMonitorOverviewResponse(BaseModel):
    total_active_accounts: int
    emails_synced_today: int
    relevant_today: int
    unread_alerts: int
    recent_failures: list[EmailMonitorSyncFailureItem] = Field(default_factory=list)
    recent_relevant_messages: list[EmailMonitorOverviewMessageItem] = Field(default_factory=list)
    recent_alerts: list[EmailMonitorAlertItem] = Field(default_factory=list)


class EmailMonitorMessageListItem(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    account_display_name: str
    folder_name: str
    sender_email: Optional[str] = None
    subject: Optional[str] = None
    sent_at: Optional[datetime.datetime] = None
    category: Optional[str] = None
    matched_rule_name: Optional[str] = None
    is_relevant: bool
    is_read_remote: bool
    is_read_internal: bool
    is_archived: bool
    is_highlighted: bool
    body_preview: Optional[str] = None


class EmailMonitorMessageMatchRead(BaseModel):
    id: uuid.UUID
    rule_id: uuid.UUID
    rule_name: str
    matched_at: datetime.datetime
    reason_summary: str


class EmailMonitorMessageDetail(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    account_display_name: str
    account_email: str
    folder_name: str
    sender_name: Optional[str] = None
    sender_email: Optional[str] = None
    recipient_email: Optional[str] = None
    subject: Optional[str] = None
    sent_at: Optional[datetime.datetime] = None
    internal_date: Optional[datetime.datetime] = None
    category: Optional[str] = None
    matched_rule_name: Optional[str] = None
    is_relevant: bool
    is_read_remote: bool
    is_read_internal: bool
    is_archived: bool
    is_highlighted: bool
    body_text: Optional[str] = None
    body_html_sanitized: Optional[str] = None
    headers: dict[str, Any]
    provider_message_url: Optional[str] = None
    matches: list[EmailMonitorMessageMatchRead] = Field(default_factory=list)


class EmailMonitorMessagesPage(BaseModel):
    items: list[EmailMonitorMessageListItem]
    page: int
    page_size: int
    total: int
    total_pages: int


class EmailMonitorMessageUpdate(BaseModel):
    is_read_internal: Optional[bool] = None
    is_archived: Optional[bool] = None
    is_highlighted: Optional[bool] = None
    category: Optional[str] = Field(default=None, max_length=120)


class EmailMonitorSyncResult(BaseModel):
    account_id: uuid.UUID
    account_display_name: str
    status: EmailMonitorSyncRunStatus
    messages_scanned: int
    messages_saved: int
    relevant_messages: int
    started_at: datetime.datetime
    finished_at: Optional[datetime.datetime] = None
    error_message: Optional[str] = None


class EmailMonitorSyncBatchResponse(BaseModel):
    results: list[EmailMonitorSyncResult]


class EmailMonitorAuditLogRead(BaseModel):
    id: uuid.UUID
    actor_usuario_id: Optional[uuid.UUID] = None
    event_type: str
    resource_type: str
    resource_id: Optional[str] = None
    message: str
    metadata_json: dict[str, Any]
    ip_address: Optional[str] = None
    created_at: datetime.datetime
