from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

# ===================================================================
# 1. HASHING DE SENHA (Para Admin Login)
# ===================================================================

# Define o contexto do passlib, usando bcrypt como padrão
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password: str) -> str:
    """Gera o hash de uma senha em texto plano."""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica se a senha em texto plano bate com o hash."""
    return pwd_context.verify(plain_password, hashed_password)


# ===================================================================
# 2. AUTENTICAÇÃO JWT (Para Sessão do Admin)
# ===================================================================

# Chave secreta e algoritmo (lidos do .env)
SECRET_KEY = settings.JWT_SECRET_KEY
ALGORITHM = "HS256"
# Define o tempo de expiração do token (ex: 7 dias)
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7 

# Define o "esquema" de segurança OAuth2. 
# Ele diz ao FastAPI para procurar um token no 'Authorization: Bearer <token>'
# O 'tokenUrl' é o endpoint que o /docs usará para logar.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/admin/login")

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Cria um novo token de acesso JWT."""
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str) -> Optional[str]:
    """
    Decodifica um token JWT. Retorna o 'subject' (ID do usuário) se válido,
    ou lança uma exceção se inválido.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        # 'sub' (subject) é o campo padrão do JWT para o ID do usuário
        user_id: Optional[str] = payload.get("sub")
        
        if user_id is None:
            raise_auth_exception()
        return user_id
        
    except JWTError:
        # Se o token estiver expirado ou for inválido
        raise_auth_exception()

def raise_auth_exception():
    """Função auxiliar para lançar o erro padrão 401."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    raise credentials_exception

# ===================================================================
# 3. CRIPTOGRAFIA SIMÉTRICA (Para Senhas de Streaming)
# ===================================================================

# Carrega a chave AES que geramos e colocamos no .env
# O Fernet espera que a chave esteja em bytes
try:
    fernet_key = settings.AES_ENCRYPTION_KEY.encode('utf-8')
    cipher_suite = Fernet(fernet_key)
except Exception as e:
    print(f"ERRO CRÍTICO: 'AES_ENCRYPTION_KEY' inválida no .env. {e}")
    # Se a chave for inválida (ex: não gerada pelo Fernet), a API falhará ao iniciar.
    # Isso é uma 'feature', não um bug, para garantir a segurança.
    raise ValueError("Chave AES_ENCRYPTION_KEY inválida. Use o script para gerar uma.")

def encrypt_data(data: str) -> str:
    """Criptografa uma string (ex: senha de streaming)."""
    encrypted_text = cipher_suite.encrypt(data.encode('utf-8'))
    return encrypted_text.decode('utf-8') # Salva como string no banco

def decrypt_data(encrypted_data: str) -> Optional[str]:
    """Descriptografa uma string. Retorna None se a chave ou o token for inválido."""
    try:
        decrypted_text = cipher_suite.decrypt(encrypted_data.encode('utf-8'))
        return decrypted_text.decode('utf-8')
    except InvalidToken:
        # Isso acontece se a chave de criptografia mudou ou 
        # se o dado no banco está corrompido
        return None