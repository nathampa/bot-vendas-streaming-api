from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from typing import List

from app.db.database import get_session
from app.models.configuracao_models import Configuracao
from app.api.v1.deps import get_current_admin_user
from app.services.affiliate_service import _get_configuracao

# Roteador de Admin
router = APIRouter(dependencies=[Depends(get_current_admin_user)])

@router.get("/", response_model=Configuracao)
def get_config(
    *,
    session: Session = Depends(get_session)
):
    """
    [ADMIN] Obtém a configuração do sistema (ou cria a padrão).
    """
    # Usamos a função do affiliate_service para garantir que ela seja criada
    return _get_configuracao(session)


@router.put("/", response_model=Configuracao)
def update_config(
    *,
    session: Session = Depends(get_session),
    config_in: Configuracao # O painel envia o objeto 'Configuracao' inteiro
):
    """
    [ADMIN] Atualiza a configuração do sistema.
    """
    db_config = session.get(Configuracao, config_in.id)
    if not db_config:
        raise HTTPException(status_code=404, detail="Configuração não encontrada")
        
    # Atualiza os dados
    update_data = config_in.model_dump(exclude_unset=True)
    db_config.sqlmodel_update(update_data)
    
    session.add(db_config)
    session.commit()
    session.refresh(db_config)
    return db_config