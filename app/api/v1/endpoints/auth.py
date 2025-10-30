from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select

from app.db.database import get_session
from app.models.usuario_models import Usuario
from app.schemas.auth_schemas import Token
from app.services import security

router = APIRouter()

@router.post(
    "/login", 
    response_model=Token, 
    tags=["Admin - Autenticação"]
)
def login_admin_para_access_token(
    session: Session = Depends(get_session),
    # O FastAPI usa este 'form_data' especial para o /docs
    # Ele entende o 'OAuth2PasswordRequestForm' e cria um formulário de login
    # username = email, password = senha
    form_data: OAuth2PasswordRequestForm = Depends()
):
    """
    Endpoint de login para o Painel Admin.
    Recebe email (como 'username') e senha (como 'password').
    Retorna um Token JWT.
    """
    
    # 1. Encontrar o usuário pelo email (que vem no campo 'username')
    query = select(Usuario).where(Usuario.email == form_data.username)
    usuario = session.exec(query).first()

    # 2. Validar o usuário
    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Email ou senha incorretos"
        )
    if not usuario.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="O usuário não é um administrador"
        )
    if not usuario.password_hash:
        # Medida de segurança caso o admin não tenha hash de senha
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Administrador não possui credenciais configuradas"
        )
        
    # 3. Validar a senha (usando nosso service)
    if not security.verify_password(form_data.password, usuario.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Email ou senha incorretos"
        )

    # 4. Criar e retornar o Token JWT (usando nosso service)
    # O 'sub' (subject) do token será o ID do usuário (convertido para str)
    access_token = security.create_access_token(
        data={"sub": str(usuario.id)}
    )
    
    return Token(access_token=access_token)