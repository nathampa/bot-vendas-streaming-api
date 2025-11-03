import uuid
import datetime
from decimal import Decimal
from fastapi import APIRouter, Depends
from sqlmodel import Session, select
from sqlalchemy import func # Importamos 'func' para usar 'func.count' e 'func.sum'
from typing import List

from app.db.database import get_session
from app.models.usuario_models import Usuario
from app.models.pedido_models import Pedido
from app.models.produto_models import Produto, EstoqueConta
from app.models.suporte_models import TicketSuporte
from app.models.base import TipoStatusTicket
from app.schemas.dashboard_schemas import (
    DashboardKPIs,
    DashboardTopProduto,
    DashboardEstoqueBaixo,
    DashboardRecentPedido
)
from app.api.v1.deps import get_current_admin_user # O "Cadeado" do Admin

# Roteador para o Dashboard (só admin)
router = APIRouter(dependencies=[Depends(get_current_admin_user)])

# --- ENDPOINTS DE DASHBOARD ---

@router.get("/kpis", response_model=DashboardKPIs)
def get_dashboard_kpis(
    *,
    session: Session = Depends(get_session)
):
    """
    [ADMIN] Retorna os principais Indicadores de Performance (KPIs).
    """
    
    # 1. Define o período de tempo (últimas 24 horas)
    time_24h_ago = datetime.datetime.utcnow() - datetime.timedelta(days=1)
    
    # 2. Query: Faturamento 24h
    q_faturamento = select(func.sum(Pedido.valor_pago)).where(
        Pedido.criado_em >= time_24h_ago
    )
    # --- CORREÇÃO APLICADA AQUI ---
    faturamento_24h = session.exec(q_faturamento).first() or Decimal("0.0")

    # 3. Query: Vendas 24h
    q_vendas = select(func.count(Pedido.id)).where(
        Pedido.criado_em >= time_24h_ago
    )
    # --- CORREÇÃO APLICADA AQUI ---
    vendas_24h = session.exec(q_vendas).first() or 0
    
    # 4. Query: Novos Usuários 24h
    q_novos_usuarios = select(func.count(Usuario.id)).where(
        Usuario.criado_em >= time_24h_ago
    )
    # --- CORREÇÃO APLICADA AQUI ---
    novos_usuarios_24h = session.exec(q_novos_usuarios).first() or 0

    # 5. Query: Tickets Abertos
    q_tickets_abertos = select(func.count(TicketSuporte.id)).where(
        TicketSuporte.status == TipoStatusTicket.ABERTO
    )
    # --- CORREÇÃO APLICADA AQUI ---
    tickets_abertos = session.exec(q_tickets_abertos).first() or 0
    
    return DashboardKPIs(
        faturamento_24h=faturamento_24h,
        vendas_24h=vendas_24h,
        novos_usuarios_24h=novos_usuarios_24h,
        tickets_abertos=tickets_abertos
    )

@router.get("/top-produtos", response_model=List[DashboardTopProduto])
def get_top_produtos(
    *,
    session: Session = Depends(get_session)
):
    """
    [ADMIN] Retorna os 5 produtos mais vendidos por faturamento.
    """
    stmt = (
        select(
            Produto.nome.label("produto_nome"),
            func.count(Pedido.id).label("total_vendas"),
            func.sum(Pedido.valor_pago).label("faturamento_total")
        )
        .join(Produto, Pedido.produto_id == Produto.id)
        .group_by(Produto.nome)
        .order_by(func.sum(Pedido.valor_pago).desc())
        .limit(5)
    )
    
    resultados = session.exec(stmt).all()
    # O .all() já retorna uma lista de Rows que o FastAPI/Pydantic
    # consegue mapear para o 'DashboardTopProduto'
    return resultados

@router.get("/estoque-baixo", response_model=List[DashboardEstoqueBaixo])
def get_estoque_baixo(
    *,
    session: Session = Depends(get_session),
    limite: int = 5 # Opcional: ?limite=5
):
    """
    [ADMIN] Lista produtos com baixo número de contas disponíveis
    (contas com pelo menos 1 slot livre).
    """
    
    # Esta query agrupa por produto e conta quantas contas
    # AINDA TÊM SLOTS LIVRES
    stmt = (
        select(
            Produto.nome.label("produto_nome"),
            func.count(EstoqueConta.id).label("contas_disponiveis")
        )
        .join(Produto, EstoqueConta.produto_id == Produto.id)
        .where(EstoqueConta.is_ativo == True)
        .where(EstoqueConta.requer_atencao == False)
        .where(EstoqueConta.slots_ocupados < EstoqueConta.max_slots) # Filtra contas com slots
        .group_by(Produto.nome)
        .having(func.count(EstoqueConta.id) < limite) # Filtra produtos abaixo do limite
        .order_by(func.count(EstoqueConta.id).asc()) # Mostra os mais críticos primeiro
    )
    
    resultados = session.exec(stmt).all()
    return resultados

@router.get("/recentes-pedidos", response_model=List[DashboardRecentPedido])
def get_recentes_pedidos(
    *,
    session: Session = Depends(get_session)
):
    """
    [ADMIN] Retorna os 5 últimos pedidos realizados.
    """
    stmt = (
        select(
            Pedido.id,
            Produto.nome.label("produto_nome"),
            Pedido.valor_pago,
            Pedido.criado_em,
            Usuario.telegram_id.label("usuario_telegram_id"),
            Usuario.nome_completo.label("nome_completo")
        )
        .join(Produto, Pedido.produto_id == Produto.id)
        .join(Usuario, Pedido.usuario_id == Usuario.id)
        .order_by(Pedido.criado_em.desc())
        .limit(5)
    )
    
    resultados = session.exec(stmt).all()
    return resultados