import datetime
import uuid
from typing import List, Optional

from sqlmodel import SQLModel


class OpenAIAccountCreationBatchItem(SQLModel):
    email: str
    senha: str
    outlook_email: Optional[str] = None
    outlook_senha: Optional[str] = None


class OpenAIAccountCreationBatchCreateRequest(SQLModel):
    items: List[OpenAIAccountCreationBatchItem]


class OpenAIAccountCreationBatchCreateResponse(SQLModel):
    created_requests: int
    created_jobs: int
    ignored_items: List[str]
    jobs: List["OpenAIAccountCreationJobRead"]


class OpenAIAccountCreationRequestRead(SQLModel):
    id: uuid.UUID
    email: str
    outlook_email: Optional[str] = None
    has_outlook_password: bool = False
    session_storage_path: Optional[str] = None
    workspace_name: Optional[str] = None
    status_atual: str
    ultimo_erro: Optional[str] = None
    criado_em: datetime.datetime
    atualizado_em: datetime.datetime


class OpenAIAccountCreationJobRead(SQLModel):
    id: uuid.UUID
    request_id: uuid.UUID
    email: str
    status: str
    attempt_count: int
    auth_path_used: Optional[str] = None
    last_error: Optional[str] = None
    evidence_path: Optional[str] = None
    locked_at: Optional[datetime.datetime] = None
    started_at: Optional[datetime.datetime] = None
    finished_at: Optional[datetime.datetime] = None
    next_retry_at: Optional[datetime.datetime] = None
    cancelled_at: Optional[datetime.datetime] = None
    otp_submitted_at: Optional[datetime.datetime] = None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    request_status_atual: str
    outlook_email: Optional[str] = None
    has_outlook_password: bool = False
    session_storage_path: Optional[str] = None
    workspace_name: Optional[str] = None


class OpenAIAccountCreationOTPSubmitRequest(SQLModel):
    otp_code: str


class OpenAIAccountCreationOutlookCredentialsBatchItem(SQLModel):
    email: str
    outlook_email: Optional[str] = None
    outlook_senha: str


class OpenAIAccountCreationOutlookCredentialsBatchRequest(SQLModel):
    items: List[OpenAIAccountCreationOutlookCredentialsBatchItem]


class OpenAIAccountCreationOutlookCredentialsBatchResponse(SQLModel):
    updated_requests: int
    ignored_items: List[str]
    requests: List[OpenAIAccountCreationRequestRead]


class OpenAIAccountCreationRetryResponse(SQLModel):
    message: str
    job: OpenAIAccountCreationJobRead


class OpenAIAccountCreationFetchOtpResponse(SQLModel):
    message: str
    fetch_status: str
    job: OpenAIAccountCreationJobRead


OpenAIAccountCreationBatchCreateResponse.model_rebuild()
