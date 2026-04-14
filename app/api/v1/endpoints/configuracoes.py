from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.api.v1.deps import get_bot_api_key, get_current_admin_user
from app.db.database import get_session
from app.models.configuracao_models import Configuracao
from app.models.usuario_models import Usuario
from app.schemas.configuracao_schemas import (
    ConfiguracaoBotManutencaoUpdateRequest,
    ConfiguracaoBotStatusRead,
)
from app.services.affiliate_service import _get_configuracao

router = APIRouter(dependencies=[Depends(get_current_admin_user)])
bot_router = APIRouter(dependencies=[Depends(get_bot_api_key)])


@router.get("/", response_model=Configuracao)
def get_config(*, session: Session = Depends(get_session)):
    """[ADMIN] Obtém a configuração do sistema (ou cria a padrão)."""
    return _get_configuracao(session)


@router.put("/", response_model=Configuracao)
def update_config(*, session: Session = Depends(get_session), config_in: Configuracao):
    """[ADMIN] Atualiza a configuração do sistema."""
    db_config = session.get(Configuracao, config_in.id)
    if not db_config:
        raise HTTPException(status_code=404, detail="Configuração não encontrada")

    update_data = config_in.model_dump(exclude_unset=True)
    db_config.sqlmodel_update(update_data)

    session.add(db_config)
    session.commit()
    session.refresh(db_config)
    return db_config


@bot_router.get("/status-bot", response_model=ConfiguracaoBotStatusRead)
def get_bot_status(*, session: Session = Depends(get_session)):
    config = _get_configuracao(session)
    return ConfiguracaoBotStatusRead(modo_manutencao=config.modo_manutencao)


@bot_router.put("/manutencao", response_model=ConfiguracaoBotStatusRead)
def update_bot_maintenance_mode(
    *,
    session: Session = Depends(get_session),
    payload: ConfiguracaoBotManutencaoUpdateRequest,
):
    usuario = session.exec(select(Usuario).where(Usuario.telegram_id == payload.telegram_id)).first()
    if not usuario or not usuario.is_admin:
        raise HTTPException(status_code=403, detail="Usuário não autorizado a alterar o modo manutenção.")

    config = _get_configuracao(session)
    config.modo_manutencao = payload.ativo
    session.add(config)
    session.commit()
    session.refresh(config)
    return ConfiguracaoBotStatusRead(modo_manutencao=config.modo_manutencao)
