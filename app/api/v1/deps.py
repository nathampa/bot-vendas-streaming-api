import uuid
from typing import Generator
from fastapi import Depends, HTTPException, status
from sqlmodel import Session

from app.db.database import get_session
from app.models.usuario_models import Usuario
from app.services import security # Nosso service de tokens e senhas

def get_current_admin_user(
    # 1. Pega a sessão do banco
    session: Session = Depends(get_session),
    # 2. Pega o token do header 'Authorization: Bearer <token>'
    token: str = Depends(security.oauth2_scheme)
) -> Usuario:
    """
    Dependência para obter o usuário admin logado.
    Usado para proteger endpoints de admin.
    """
    
    # 3. Decodifica o token para obter o ID do usuário ('sub')
    user_id = security.decode_access_token(token) # Já lida com 401 se o token for inválido
    if user_id is None:
        security.raise_auth_exception()
        
    # 4. Busca o usuário no banco de dados
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        # Se o 'sub' do token não for um UUID válido
        security.raise_auth_exception()
        
    usuario = session.get(Usuario, user_uuid)
    
    # 5. Valida se o usuário existe E se é um admin
    if usuario is None:
        security.raise_auth_exception()
    
    if not usuario.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="O usuário não tem permissão de administrador",
        )
        
    # 6. Sucesso! Retorna o objeto do admin
    return usuario