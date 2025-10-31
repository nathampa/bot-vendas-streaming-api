import uuid
import secrets  # Importação necessária
from typing import Generator
from fastapi import Depends, HTTPException, status
# Importação-chave corrigida: adiciona APIKeyHeader
from fastapi.security import OAuth2PasswordBearer, APIKeyHeader 
from sqlmodel import Session

from app.db.database import get_session
from app.models.usuario_models import Usuario
from app.services import security
from app.core.config import settings # Importação necessária

# --- CADEADO 1: ADMIN (JWT) ---
# (Este é o seu código de admin existente, que está correto)
def get_current_admin_user(
    session: Session = Depends(get_session),
    token: str = Depends(security.oauth2_scheme)
) -> Usuario:
    """
    Dependência para obter o usuário admin logado.
    Usado para proteger endpoints de admin.
    """

    user_id = security.decode_access_token(token) 
    if user_id is None:
        security.raise_auth_exception()

    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        security.raise_auth_exception()

    usuario = session.get(Usuario, user_uuid)

    if usuario is None:
        security.raise_auth_exception()

    if not usuario.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="O usuário não tem permissão de administrador",
        )

    return usuario

# --- CADEADO 2: BOT (API Key) ---

# 1. Define o esquema: procurar por um cabeçalho chamado 'X-API-Key'
api_key_header_scheme = APIKeyHeader(name="X-API-Key")

def get_bot_api_key(
    api_key: str = Depends(api_key_header_scheme)
):
    """
    Dependência para proteger rotas do bot.
    Verifica se o cabeçalho X-API-Key corresponde à chave no .env
    """

    # 2. Compara as chaves de forma segura
    is_correct = secrets.compare_digest(api_key, settings.BOT_API_KEY)

    if not is_correct:
        # 3. Se falhar, rejeita o pedido
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Chave de API inválida ou em falta (X-API-Key)",
        )

    # 4. Se for bem-sucedido, permite que o pedido continue
    return True