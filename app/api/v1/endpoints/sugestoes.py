import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from sqlalchemy import func # Importamos 'func' para usar 'func.count'
from typing import List

from app.db.database import get_session
from app.models.usuario_models import Usuario, SugestaoStreaming
from app.schemas.sugestao_schemas import (
    SugestaoCreateRequest,
    SugestaoCreateResponse,
    SugestaoAdminRead
)
from app.api.v1.deps import get_current_admin_user # O "Cadeado" do Admin

# Roteador para o Bot (criação de sugestões)
router = APIRouter()
# Roteador para o Admin (gestão de sugestões)
admin_router = APIRouter(dependencies=[Depends(get_current_admin_user)])

# --- ENDPOINT DO BOT ---

@router.post("/", response_model=SugestaoCreateResponse, status_code=status.HTTP_201_CREATED)
def create_sugestao(
    *,
    session: Session = Depends(get_session),
    sugestao_in: SugestaoCreateRequest
):
    """
    [BOT] Envia uma nova sugestão de streaming.
    """
    
    # 1. Encontra o usuário
    usuario = session.exec(
        select(Usuario).where(Usuario.telegram_id == sugestao_in.telegram_id)
    ).first()
    
    if not usuario:
        # Se o usuário não existe, ele não pode sugerir.
        # (Ele deve ser criado primeiro por outro fluxo, ex: /start ou recarga)
        raise HTTPException(status_code=404, detail="Usuário não encontrado. Inicie o bot primeiro.")
        
    # 2. Normaliza o nome do streaming
    nome_normalizado = sugestao_in.nome_streaming.strip().lower()
    
    if len(nome_normalizado) < 3:
        raise HTTPException(status_code=400, detail="Nome do streaming muito curto.")

    # 3. Cria e salva a sugestão
    nova_sugestao = SugestaoStreaming(
        usuario_id=usuario.id,
        nome_streaming=nome_normalizado,
        status="PENDENTE" # Status padrão
    )
    
    session.add(nova_sugestao)
    session.commit()
    session.refresh(nova_sugestao)
    
    return nova_sugestao

# --- ENDPOINT DE ADMIN ---

@admin_router.get("/", response_model=List[SugestaoAdminRead])
def get_lista_sugestoes(
    *,
    session: Session = Depends(get_session)
):
    """
    [ADMIN] Lista as sugestões, agrupadas por nome e contagem,
    ordenadas pela mais pedida.
    """
    
    # Esta é uma query de Agregação (GROUP BY)
    stmt = (
        select(
            SugestaoStreaming.nome_streaming,
            func.count(SugestaoStreaming.id).label("contagem"),
            SugestaoStreaming.status # Usamos o status da primeira entrada
        )
        .group_by(SugestaoStreaming.nome_streaming, SugestaoStreaming.status)
        .order_by(func.count(SugestaoStreaming.id).desc())
    )
    
    resultados = session.exec(stmt).all()
    
    # Mapeia os resultados para o nosso schema de resposta
    lista_resposta = [
        SugestaoAdminRead(
            nome_streaming=nome,
            contagem=contagem,
            status=status
        ) for nome, contagem, status in resultados
    ]
    
    return lista_resposta