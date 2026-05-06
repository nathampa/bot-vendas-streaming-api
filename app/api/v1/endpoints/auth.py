from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select

from app.api.v1.deps import get_current_admin_user
from app.db.database import get_session
from app.models.usuario_models import Usuario
from app.schemas.auth_schemas import AdminProfileRead, Token
from app.services import security
from app.services.email_monitor_service import log_audit

router = APIRouter()


@router.get("/me", response_model=AdminProfileRead, tags=["Admin - Autenticação"])
def get_admin_me(
    current_admin: Usuario = Depends(get_current_admin_user),
):
    return AdminProfileRead(
        id=current_admin.id,
        nome_completo=current_admin.nome_completo,
        email=current_admin.email,
        telegram_id=current_admin.telegram_id,
        is_admin=current_admin.is_admin,
        criado_em=current_admin.criado_em,
    )


@router.post(
    "/login",
    response_model=Token,
    tags=["Admin - Autenticação"],
)
def login_admin_para_access_token(
    request: Request,
    session: Session = Depends(get_session),
    form_data: OAuth2PasswordRequestForm = Depends(),
):
    query = select(Usuario).where(Usuario.email == form_data.username)
    usuario = session.exec(query).first()
    client_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else None)

    if not usuario:
        log_audit(
            session,
            actor_usuario_id=None,
            event_type="admin.login.failed",
            resource_type="admin_auth",
            message="Tentativa de login com email inexistente.",
            metadata={"email": form_data.username},
            ip_address=client_ip,
        )
        session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email ou senha incorretos")

    if not usuario.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="O usuário não é um administrador")
    if not usuario.password_hash:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Administrador não possui credenciais configuradas",
        )
    if not security.verify_password(form_data.password, usuario.password_hash):
        log_audit(
            session,
            actor_usuario_id=usuario.id,
            event_type="admin.login.failed",
            resource_type="admin_auth",
            message="Tentativa de login com senha inválida.",
            metadata={"email": usuario.email},
            ip_address=client_ip,
        )
        session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email ou senha incorretos")

    access_token = security.create_access_token(data={"sub": str(usuario.id)})
    log_audit(
        session,
        actor_usuario_id=usuario.id,
        event_type="admin.login",
        resource_type="admin_auth",
        resource_id=str(usuario.id),
        message="Login administrativo realizado com sucesso.",
        metadata={"email": usuario.email},
        ip_address=client_ip,
    )
    session.commit()
    return Token(access_token=access_token)
