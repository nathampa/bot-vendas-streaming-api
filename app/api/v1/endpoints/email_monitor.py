import datetime
import math
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func
from sqlmodel import Session, select

from app.api.v1.deps import get_current_admin_user
from app.db.database import get_session
from app.models.email_monitor_models import (
    AuditLog,
    EmailMonitorAccount,
    EmailMonitorAlertEvent,
    EmailMonitorMessage,
    EmailMonitorMessageMatch,
    EmailMonitorRule,
    EmailMonitorSyncRun,
)
from app.models.usuario_models import Usuario
from app.schemas.email_monitor_schemas import (
    EmailMonitorAccountCreate,
    EmailMonitorAccountDetail,
    EmailMonitorAccountRead,
    EmailMonitorAccountTestRequest,
    EmailMonitorOutlookOtpFetchResponse,
    EmailMonitorAccountUpdate,
    EmailMonitorAlertItem,
    EmailMonitorAuditLogRead,
    EmailMonitorConnectionTestResult,
    EmailMonitorMessageDetail,
    EmailMonitorMessageListItem,
    EmailMonitorMessageMatchRead,
    EmailMonitorMessageUpdate,
    EmailMonitorMessagesPage,
    EmailMonitorOverviewMessageItem,
    EmailMonitorOverviewResponse,
    EmailMonitorRuleCreate,
    EmailMonitorRuleRead,
    EmailMonitorRuleUpdate,
    EmailMonitorSyncBatchResponse,
    EmailMonitorSyncFailureItem,
    EmailMonitorSyncResult,
)
from app.services.email_monitor_service import (
    account_to_schema_payload,
    delete_account_permanently,
    enqueue_email_monitor_outlook_otp_fetch,
    log_audit,
    normalize_folder_list,
    normalize_rule_keywords,
    start_email_monitor_outlook_otp_fetch,
    sync_account,
    sync_active_accounts,
    test_imap_connection,
)
from app.services.security import encrypt_data

router = APIRouter(dependencies=[Depends(get_current_admin_user)])


def get_client_ip(request: Request) -> Optional[str]:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


@router.get("/overview", response_model=EmailMonitorOverviewResponse)
def get_overview(
    *,
    session: Session = Depends(get_session),
):
    now = datetime.datetime.utcnow()
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

    total_active_accounts = session.exec(
        select(func.count()).select_from(EmailMonitorAccount).where(EmailMonitorAccount.is_active == True)
    ).one()
    emails_synced_today = session.exec(
        select(func.count()).select_from(EmailMonitorMessage).where(EmailMonitorMessage.created_at >= start_of_day)
    ).one()
    relevant_today = session.exec(
        select(func.count()).select_from(EmailMonitorMessage).where(
            EmailMonitorMessage.created_at >= start_of_day,
            EmailMonitorMessage.is_relevant == True,
        )
    ).one()
    unread_alerts = session.exec(
        select(func.count()).select_from(EmailMonitorAlertEvent).where(EmailMonitorAlertEvent.is_read == False)
    ).one()

    failure_rows = session.exec(
        select(EmailMonitorAccount)
        .where(EmailMonitorAccount.last_error_at.is_not(None))
        .order_by(EmailMonitorAccount.last_error_at.desc())
        .limit(5)
    ).all()
    recent_failures = [
        EmailMonitorSyncFailureItem(
            account_id=account.id,
            account_display_name=account.display_name,
            last_error_at=account.last_error_at,
            last_error_message=account.last_error_message,
            consecutive_failures=account.consecutive_failures,
            next_retry_at=account.next_retry_at,
        )
        for account in failure_rows
    ]

    relevant_rows = session.exec(
        select(EmailMonitorMessage, EmailMonitorAccount.display_name)
        .join(EmailMonitorAccount, EmailMonitorMessage.account_id == EmailMonitorAccount.id)
        .where(EmailMonitorMessage.is_relevant == True, EmailMonitorMessage.is_archived == False)
        .order_by(EmailMonitorMessage.sent_at.desc().nullslast(), EmailMonitorMessage.created_at.desc())
        .limit(8)
    ).all()
    recent_relevant = [
        EmailMonitorOverviewMessageItem(
            id=message.id,
            account_id=message.account_id,
            account_display_name=display_name,
            sender_email=message.sender_email,
            subject=message.subject,
            sent_at=message.sent_at,
            category=message.category,
            matched_rule_name=message.matched_rule_name,
            is_read_internal=message.is_read_internal,
            is_highlighted=message.is_highlighted,
        )
        for message, display_name in relevant_rows
    ]

    alert_rows = session.exec(
        select(EmailMonitorAlertEvent, EmailMonitorAccount.display_name)
        .join(EmailMonitorAccount, EmailMonitorAlertEvent.account_id == EmailMonitorAccount.id)
        .order_by(EmailMonitorAlertEvent.created_at.desc())
        .limit(8)
    ).all()
    recent_alerts = [
        EmailMonitorAlertItem(
            id=alert.id,
            account_id=alert.account_id,
            account_display_name=display_name,
            message_id=alert.message_id,
            category=alert.category,
            sender_email=alert.sender_email,
            subject=alert.subject,
            is_read=alert.is_read,
            webhook_status=alert.webhook_status,
            created_at=alert.created_at,
        )
        for alert, display_name in alert_rows
    ]

    return EmailMonitorOverviewResponse(
        total_active_accounts=total_active_accounts or 0,
        emails_synced_today=emails_synced_today or 0,
        relevant_today=relevant_today or 0,
        unread_alerts=unread_alerts or 0,
        recent_failures=recent_failures,
        recent_relevant_messages=recent_relevant,
        recent_alerts=recent_alerts,
    )


@router.get("/accounts", response_model=list[EmailMonitorAccountRead])
def list_accounts(*, session: Session = Depends(get_session)):
    accounts = session.exec(select(EmailMonitorAccount).order_by(EmailMonitorAccount.display_name.asc())).all()
    return [EmailMonitorAccountRead(**account_to_schema_payload(account)) for account in accounts]


@router.get("/accounts/{account_id}", response_model=EmailMonitorAccountDetail)
def get_account(*, session: Session = Depends(get_session), account_id: uuid.UUID):
    account = session.get(EmailMonitorAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Conta IMAP não encontrada.")
    payload = account_to_schema_payload(account)
    payload["folder_states"] = list(account.folder_states)
    return EmailMonitorAccountDetail(**payload)


@router.post("/accounts/test", response_model=EmailMonitorConnectionTestResult)
def test_account_connection(payload: EmailMonitorAccountTestRequest):
    success, message, folders = test_imap_connection(
        imap_host=payload.imap_host,
        imap_port=payload.imap_port,
        imap_username=payload.imap_username,
        password=payload.password,
        use_ssl=payload.use_ssl,
    )
    return EmailMonitorConnectionTestResult(success=success, message=message, folders=folders)


@router.post("/accounts", response_model=EmailMonitorAccountRead, status_code=status.HTTP_201_CREATED)
def create_account(
    *,
    payload: EmailMonitorAccountCreate,
    request: Request,
    session: Session = Depends(get_session),
    current_admin: Usuario = Depends(get_current_admin_user),
):
    account = EmailMonitorAccount(
        owner_usuario_id=current_admin.id,
        display_name=payload.display_name.strip(),
        email=payload.email.strip(),
        imap_host=payload.imap_host.strip(),
        imap_port=payload.imap_port,
        imap_username=payload.imap_username.strip(),
        imap_password_encrypted=encrypt_data(payload.password),
        use_ssl=payload.use_ssl,
        is_active=payload.is_active,
        selected_folders_json=normalize_folder_list(payload.selected_folders),
        sync_interval_minutes=payload.sync_interval_minutes,
        retain_irrelevant_days=payload.retain_irrelevant_days,
    )
    session.add(account)
    log_audit(
        session,
        actor_usuario_id=current_admin.id,
        event_type="email_monitor.account.created",
        resource_type="email_monitor_account",
        resource_id=str(account.id),
        message=f"Conta IMAP '{account.display_name}' cadastrada.",
        metadata={
            "email": account.email,
            "imap_host": account.imap_host,
            "selected_folders": account.selected_folders_json,
        },
        ip_address=get_client_ip(request),
    )
    session.commit()
    session.refresh(account)
    return EmailMonitorAccountRead(**account_to_schema_payload(account))


@router.put("/accounts/{account_id}", response_model=EmailMonitorAccountRead)
def update_account(
    *,
    account_id: uuid.UUID,
    payload: EmailMonitorAccountUpdate,
    request: Request,
    session: Session = Depends(get_session),
    current_admin: Usuario = Depends(get_current_admin_user),
):
    account = session.get(EmailMonitorAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Conta IMAP não encontrada.")

    update_data = payload.model_dump(exclude_unset=True)
    if "display_name" in update_data:
        account.display_name = payload.display_name.strip()  # type: ignore[union-attr]
    if "email" in update_data:
        account.email = payload.email.strip()  # type: ignore[union-attr]
    if "imap_host" in update_data:
        account.imap_host = payload.imap_host.strip()  # type: ignore[union-attr]
    if "imap_port" in update_data:
        account.imap_port = payload.imap_port  # type: ignore[assignment]
    if "imap_username" in update_data:
        account.imap_username = payload.imap_username.strip()  # type: ignore[union-attr]
    if "password" in update_data and payload.password:
        account.imap_password_encrypted = encrypt_data(payload.password)
    if "use_ssl" in update_data:
        account.use_ssl = bool(payload.use_ssl)
    if "is_active" in update_data:
        account.is_active = bool(payload.is_active)
    if "selected_folders" in update_data:
        account.selected_folders_json = normalize_folder_list(payload.selected_folders)
    if "sync_interval_minutes" in update_data and payload.sync_interval_minutes is not None:
        account.sync_interval_minutes = payload.sync_interval_minutes
    if "retain_irrelevant_days" in update_data and payload.retain_irrelevant_days is not None:
        account.retain_irrelevant_days = payload.retain_irrelevant_days

    session.add(account)
    log_audit(
        session,
        actor_usuario_id=current_admin.id,
        event_type="email_monitor.account.updated",
        resource_type="email_monitor_account",
        resource_id=str(account.id),
        message=f"Conta IMAP '{account.display_name}' atualizada.",
        metadata={
            "email": account.email,
            "imap_host": account.imap_host,
            "selected_folders": account.selected_folders_json,
            "is_active": account.is_active,
        },
        ip_address=get_client_ip(request),
    )
    session.commit()
    session.refresh(account)
    return EmailMonitorAccountRead(**account_to_schema_payload(account))


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    *,
    account_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    current_admin: Usuario = Depends(get_current_admin_user),
):
    account = session.get(EmailMonitorAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Conta IMAP não encontrada.")

    account_name = account.display_name
    account_email = account.email
    try:
        deleted_items = delete_account_permanently(session, account)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    log_audit(
        session,
        actor_usuario_id=current_admin.id,
        event_type="email_monitor.account.deleted",
        resource_type="email_monitor_account",
        resource_id=str(account_id),
        message=f"Conta IMAP '{account_name}' excluida permanentemente.",
        metadata={
            "email": account_email,
            "deleted_items": deleted_items,
        },
        ip_address=get_client_ip(request),
    )
    session.commit()
    return None


@router.post("/accounts/{account_id}/sync", response_model=EmailMonitorSyncResult)
def sync_single_account(
    *,
    account_id: uuid.UUID,
    force: bool = False,
    request: Request,
    session: Session = Depends(get_session),
    current_admin: Usuario = Depends(get_current_admin_user),
):
    account = session.get(EmailMonitorAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Conta IMAP não encontrada.")
    try:
        sync_run = sync_account(session, account, trigger_source="manual", force=force)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    log_audit(
        session,
        actor_usuario_id=current_admin.id,
        event_type="email_monitor.sync.manual",
        resource_type="email_monitor_account",
        resource_id=str(account.id),
        message=f"Sincronização manual executada para '{account.display_name}'.",
        metadata={
            "status": sync_run.status.value,
            "messages_scanned": sync_run.messages_scanned,
            "messages_saved": sync_run.messages_saved,
            "relevant_messages": sync_run.relevant_messages,
        },
        ip_address=get_client_ip(request),
    )
    session.commit()
    return EmailMonitorSyncResult(
        account_id=account.id,
        account_display_name=account.display_name,
        status=sync_run.status,
        messages_scanned=sync_run.messages_scanned,
        messages_saved=sync_run.messages_saved,
        relevant_messages=sync_run.relevant_messages,
        started_at=sync_run.started_at,
        finished_at=sync_run.finished_at,
        error_message=sync_run.error_message,
    )


@router.post("/accounts/{account_id}/fetch-outlook-otp", response_model=EmailMonitorOutlookOtpFetchResponse)
def fetch_outlook_otp_for_account(
    *,
    account_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    current_admin: Usuario = Depends(get_current_admin_user),
):
    account = session.get(EmailMonitorAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Conta IMAP não encontrada.")

    try:
        start_email_monitor_outlook_otp_fetch(session, account)
        log_audit(
            session,
            actor_usuario_id=current_admin.id,
            event_type="email_monitor.account.fetch_outlook_otp_started",
            resource_type="email_monitor_account",
            resource_id=str(account.id),
            message=f"Busca de OTP Outlook iniciada para '{account.display_name}'.",
            metadata={"email": account.email},
            ip_address=get_client_ip(request),
        )
        session.commit()
        session.refresh(account)
        enqueue_email_monitor_outlook_otp_fetch(account.id)
        return EmailMonitorOutlookOtpFetchResponse(
            message="Busca de OTP Outlook iniciada. Atualize a lista em instantes para ver o código.",
            fetch_status="FETCH_STARTED",
            account=EmailMonitorAccountRead(**account_to_schema_payload(account)),
        )
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/sync", response_model=EmailMonitorSyncBatchResponse)
def sync_all_accounts(
    *,
    force: bool = False,
    request: Request,
    session: Session = Depends(get_session),
    current_admin: Usuario = Depends(get_current_admin_user),
):
    runs = sync_active_accounts(trigger_source="manual", force=force)
    results = []
    for sync_run in runs:
        account = session.get(EmailMonitorAccount, sync_run.account_id)
        if not account:
            continue
        results.append(
            EmailMonitorSyncResult(
                account_id=account.id,
                account_display_name=account.display_name,
                status=sync_run.status,
                messages_scanned=sync_run.messages_scanned,
                messages_saved=sync_run.messages_saved,
                relevant_messages=sync_run.relevant_messages,
                started_at=sync_run.started_at,
                finished_at=sync_run.finished_at,
                error_message=sync_run.error_message,
            )
        )
    log_audit(
        session,
        actor_usuario_id=current_admin.id,
        event_type="email_monitor.sync.manual_batch",
        resource_type="email_monitor",
        message="Sincronização manual em lote executada.",
        metadata={"accounts_processed": len(results), "force": force},
        ip_address=get_client_ip(request),
    )
    session.commit()
    return EmailMonitorSyncBatchResponse(results=results)


@router.get("/rules", response_model=list[EmailMonitorRuleRead])
def list_rules(*, session: Session = Depends(get_session)):
    rules = session.exec(select(EmailMonitorRule).order_by(EmailMonitorRule.priority.asc(), EmailMonitorRule.name.asc())).all()
    return [
        EmailMonitorRuleRead(
            id=rule.id,
            name=rule.name,
            account_id=rule.account_id,
            sender_pattern=rule.sender_pattern,
            subject_pattern=rule.subject_pattern,
            body_keywords=normalize_rule_keywords(rule.body_keywords_json),
            folder_pattern=rule.folder_pattern,
            category=rule.category,
            mark_relevant=rule.mark_relevant,
            raise_dashboard_alert=rule.raise_dashboard_alert,
            highlight=rule.highlight,
            enabled=rule.enabled,
            priority=rule.priority,
            webhook_url=rule.webhook_url,
            created_at=rule.created_at,
            updated_at=rule.updated_at,
            scope_label="Global" if rule.account_id is None else "Conta",
        )
        for rule in rules
    ]


@router.post("/rules", response_model=EmailMonitorRuleRead, status_code=status.HTTP_201_CREATED)
def create_rule(
    *,
    payload: EmailMonitorRuleCreate,
    request: Request,
    session: Session = Depends(get_session),
    current_admin: Usuario = Depends(get_current_admin_user),
):
    if payload.account_id and not session.get(EmailMonitorAccount, payload.account_id):
        raise HTTPException(status_code=404, detail="Conta IMAP vinculada à regra não encontrada.")
    rule = EmailMonitorRule(
        owner_usuario_id=current_admin.id,
        account_id=payload.account_id,
        name=payload.name.strip(),
        sender_pattern=payload.sender_pattern.strip() if payload.sender_pattern else None,
        subject_pattern=payload.subject_pattern.strip() if payload.subject_pattern else None,
        body_keywords_json=normalize_rule_keywords(payload.body_keywords),
        folder_pattern=payload.folder_pattern.strip() if payload.folder_pattern else None,
        category=payload.category.strip() if payload.category else None,
        mark_relevant=payload.mark_relevant,
        raise_dashboard_alert=payload.raise_dashboard_alert,
        highlight=payload.highlight,
        enabled=payload.enabled,
        priority=payload.priority,
        webhook_url=payload.webhook_url.strip() if payload.webhook_url else None,
    )
    session.add(rule)
    log_audit(
        session,
        actor_usuario_id=current_admin.id,
        event_type="email_monitor.rule.created",
        resource_type="email_monitor_rule",
        resource_id=str(rule.id),
        message=f"Regra '{rule.name}' criada.",
        metadata={"account_id": str(rule.account_id) if rule.account_id else None, "priority": rule.priority},
        ip_address=get_client_ip(request),
    )
    session.commit()
    session.refresh(rule)
    return EmailMonitorRuleRead(
        id=rule.id,
        name=rule.name,
        account_id=rule.account_id,
        sender_pattern=rule.sender_pattern,
        subject_pattern=rule.subject_pattern,
        body_keywords=normalize_rule_keywords(rule.body_keywords_json),
        folder_pattern=rule.folder_pattern,
        category=rule.category,
        mark_relevant=rule.mark_relevant,
        raise_dashboard_alert=rule.raise_dashboard_alert,
        highlight=rule.highlight,
        enabled=rule.enabled,
        priority=rule.priority,
        webhook_url=rule.webhook_url,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
        scope_label="Global" if rule.account_id is None else "Conta",
    )


@router.put("/rules/{rule_id}", response_model=EmailMonitorRuleRead)
def update_rule(
    *,
    rule_id: uuid.UUID,
    payload: EmailMonitorRuleUpdate,
    request: Request,
    session: Session = Depends(get_session),
    current_admin: Usuario = Depends(get_current_admin_user),
):
    rule = session.get(EmailMonitorRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Regra não encontrada.")
    if payload.account_id and not session.get(EmailMonitorAccount, payload.account_id):
        raise HTTPException(status_code=404, detail="Conta IMAP vinculada à regra não encontrada.")

    update_data = payload.model_dump(exclude_unset=True)
    for field_name, value in update_data.items():
        if field_name == "body_keywords":
            rule.body_keywords_json = normalize_rule_keywords(value)
        elif field_name in {"sender_pattern", "subject_pattern", "folder_pattern", "category", "webhook_url"}:
            setattr(rule, field_name, value.strip() if isinstance(value, str) and value else None)
        elif field_name == "name" and isinstance(value, str):
            rule.name = value.strip()
        else:
            setattr(rule, field_name, value)
    session.add(rule)
    log_audit(
        session,
        actor_usuario_id=current_admin.id,
        event_type="email_monitor.rule.updated",
        resource_type="email_monitor_rule",
        resource_id=str(rule.id),
        message=f"Regra '{rule.name}' atualizada.",
        metadata={"account_id": str(rule.account_id) if rule.account_id else None, "priority": rule.priority},
        ip_address=get_client_ip(request),
    )
    session.commit()
    session.refresh(rule)
    return EmailMonitorRuleRead(
        id=rule.id,
        name=rule.name,
        account_id=rule.account_id,
        sender_pattern=rule.sender_pattern,
        subject_pattern=rule.subject_pattern,
        body_keywords=normalize_rule_keywords(rule.body_keywords_json),
        folder_pattern=rule.folder_pattern,
        category=rule.category,
        mark_relevant=rule.mark_relevant,
        raise_dashboard_alert=rule.raise_dashboard_alert,
        highlight=rule.highlight,
        enabled=rule.enabled,
        priority=rule.priority,
        webhook_url=rule.webhook_url,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
        scope_label="Global" if rule.account_id is None else "Conta",
    )


@router.get("/messages", response_model=EmailMonitorMessagesPage)
def list_messages(
    *,
    session: Session = Depends(get_session),
    account_id: Optional[uuid.UUID] = None,
    sender: Optional[str] = None,
    category: Optional[str] = None,
    folder: Optional[str] = None,
    search: Optional[str] = None,
    days: Optional[int] = Query(default=None, ge=1, le=365),
    relevant_only: bool = False,
    archived: Optional[bool] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    filters = []
    if account_id:
        filters.append(EmailMonitorMessage.account_id == account_id)
    if sender:
        filters.append(EmailMonitorMessage.sender_email.ilike(f"%{sender.strip()}%"))
    if category:
        filters.append(EmailMonitorMessage.category.ilike(f"%{category.strip()}%"))
    if folder:
        filters.append(EmailMonitorMessage.folder_name.ilike(f"%{folder.strip()}%"))
    if relevant_only:
        filters.append(EmailMonitorMessage.is_relevant == True)
    if archived is not None:
        filters.append(EmailMonitorMessage.is_archived == archived)
    if days:
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=days)
        filters.append(EmailMonitorMessage.created_at >= cutoff)
    if search:
        term = f"%{search.strip()}%"
        filters.append(
            (EmailMonitorMessage.subject.ilike(term))
            | (EmailMonitorMessage.body_preview.ilike(term))
            | (EmailMonitorMessage.sender_email.ilike(term))
        )

    total = session.exec(
        select(func.count()).select_from(EmailMonitorMessage).where(*filters)
    ).one()
    rows = session.exec(
        select(EmailMonitorMessage, EmailMonitorAccount.display_name)
        .join(EmailMonitorAccount, EmailMonitorMessage.account_id == EmailMonitorAccount.id)
        .where(*filters)
        .order_by(EmailMonitorMessage.sent_at.desc().nullslast(), EmailMonitorMessage.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    items = [
        EmailMonitorMessageListItem(
            id=message.id,
            account_id=message.account_id,
            account_display_name=display_name,
            folder_name=message.folder_name,
            sender_email=message.sender_email,
            subject=message.subject,
            sent_at=message.sent_at,
            category=message.category,
            matched_rule_name=message.matched_rule_name,
            is_relevant=message.is_relevant,
            is_read_remote=message.is_read_remote,
            is_read_internal=message.is_read_internal,
            is_archived=message.is_archived,
            is_highlighted=message.is_highlighted,
            body_preview=message.body_preview,
        )
        for message, display_name in rows
    ]

    return EmailMonitorMessagesPage(
        items=items,
        page=page,
        page_size=page_size,
        total=total or 0,
        total_pages=max(1, math.ceil((total or 0) / page_size)) if page_size else 1,
    )


@router.get("/messages/{message_id}", response_model=EmailMonitorMessageDetail)
def get_message_detail(*, session: Session = Depends(get_session), message_id: uuid.UUID):
    message = session.get(EmailMonitorMessage, message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Mensagem não encontrada.")
    account = session.get(EmailMonitorAccount, message.account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Conta de origem não encontrada.")
    match_rows = session.exec(
        select(EmailMonitorMessageMatch, EmailMonitorRule.name)
        .join(EmailMonitorRule, EmailMonitorMessageMatch.rule_id == EmailMonitorRule.id)
        .where(EmailMonitorMessageMatch.message_id == message.id)
        .order_by(EmailMonitorMessageMatch.matched_at.asc())
    ).all()
    matches = [
        EmailMonitorMessageMatchRead(
            id=match.id,
            rule_id=match.rule_id,
            rule_name=rule_name,
            matched_at=match.matched_at,
            reason_summary=match.reason_summary,
        )
        for match, rule_name in match_rows
    ]
    return EmailMonitorMessageDetail(
        id=message.id,
        account_id=message.account_id,
        account_display_name=account.display_name,
        account_email=account.email,
        folder_name=message.folder_name,
        sender_name=message.sender_name,
        sender_email=message.sender_email,
        recipient_email=message.recipient_email,
        subject=message.subject,
        sent_at=message.sent_at,
        internal_date=message.internal_date,
        category=message.category,
        matched_rule_name=message.matched_rule_name,
        is_relevant=message.is_relevant,
        is_read_remote=message.is_read_remote,
        is_read_internal=message.is_read_internal,
        is_archived=message.is_archived,
        is_highlighted=message.is_highlighted,
        body_text=message.body_text,
        body_html_sanitized=message.body_html_sanitized,
        headers=message.headers_json,
        provider_message_url=message.provider_message_url,
        matches=matches,
    )


@router.patch("/messages/{message_id}", response_model=EmailMonitorMessageDetail)
def update_message(
    *,
    message_id: uuid.UUID,
    payload: EmailMonitorMessageUpdate,
    request: Request,
    session: Session = Depends(get_session),
    current_admin: Usuario = Depends(get_current_admin_user),
):
    message = session.get(EmailMonitorMessage, message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Mensagem não encontrada.")
    update_data = payload.model_dump(exclude_unset=True)
    for field_name, value in update_data.items():
        setattr(message, field_name, value)
    session.add(message)
    log_audit(
        session,
        actor_usuario_id=current_admin.id,
        event_type="email_monitor.message.updated",
        resource_type="email_monitor_message",
        resource_id=str(message.id),
        message=f"Mensagem '{message.subject or message.id}' atualizada.",
        metadata=update_data,
        ip_address=get_client_ip(request),
    )
    session.commit()
    return get_message_detail(session=session, message_id=message_id)


@router.get("/alerts", response_model=list[EmailMonitorAlertItem])
def list_alerts(*, session: Session = Depends(get_session), unread_only: bool = False):
    filters = [EmailMonitorAlertEvent.is_read == False] if unread_only else []
    rows = session.exec(
        select(EmailMonitorAlertEvent, EmailMonitorAccount.display_name)
        .join(EmailMonitorAccount, EmailMonitorAlertEvent.account_id == EmailMonitorAccount.id)
        .where(*filters)
        .order_by(EmailMonitorAlertEvent.created_at.desc())
        .limit(50)
    ).all()
    return [
        EmailMonitorAlertItem(
            id=alert.id,
            account_id=alert.account_id,
            account_display_name=display_name,
            message_id=alert.message_id,
            category=alert.category,
            sender_email=alert.sender_email,
            subject=alert.subject,
            is_read=alert.is_read,
            webhook_status=alert.webhook_status,
            created_at=alert.created_at,
        )
        for alert, display_name in rows
    ]


@router.post("/alerts/{alert_id}/ack", response_model=EmailMonitorAlertItem)
def acknowledge_alert(
    *,
    alert_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    current_admin: Usuario = Depends(get_current_admin_user),
):
    alert = session.get(EmailMonitorAlertEvent, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alerta não encontrado.")
    alert.is_read = True
    session.add(alert)
    log_audit(
        session,
        actor_usuario_id=current_admin.id,
        event_type="email_monitor.alert.ack",
        resource_type="email_monitor_alert",
        resource_id=str(alert.id),
        message="Alerta do dashboard marcado como lido.",
        metadata={"message_id": str(alert.message_id)},
        ip_address=get_client_ip(request),
    )
    session.commit()
    account = session.get(EmailMonitorAccount, alert.account_id)
    return EmailMonitorAlertItem(
        id=alert.id,
        account_id=alert.account_id,
        account_display_name=account.display_name if account else "Conta removida",
        message_id=alert.message_id,
        category=alert.category,
        sender_email=alert.sender_email,
        subject=alert.subject,
        is_read=alert.is_read,
        webhook_status=alert.webhook_status,
        created_at=alert.created_at,
    )


@router.get("/audit", response_model=list[EmailMonitorAuditLogRead])
def list_audit_logs(*, session: Session = Depends(get_session), limit: int = Query(default=50, ge=1, le=200)):
    logs = session.exec(
        select(AuditLog)
        .where(AuditLog.event_type.ilike("email_monitor.%") | (AuditLog.event_type == "admin.login"))
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    ).all()
    return [
        EmailMonitorAuditLogRead(
            id=log.id,
            actor_usuario_id=log.actor_usuario_id,
            event_type=log.event_type,
            resource_type=log.resource_type,
            resource_id=log.resource_id,
            message=log.message,
            metadata_json=log.metadata_json,
            ip_address=log.ip_address,
            created_at=log.created_at,
        )
        for log in logs
    ]
