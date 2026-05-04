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
from app.models.conta_mae_models import ContaMae
from app.models.suporte_models import TicketSuporte
from app.models.base import StatusEntregaPedido, TipoStatusTicket
from app.schemas.dashboard_schemas import (
    DashboardAnalitico,
    DashboardExpiringPedido,
    DashboardKPIs,
    DashboardOperationalHealth,
    DashboardTopProduto,
    DashboardEstoqueBaixo,
    DashboardRecentPedido
)
from app.api.v1.deps import get_current_admin_user # O "Cadeado" do Admin
from app.services.pedido_expiracao_service import resolver_data_expiracao_pedido

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


@router.get("/analitico", response_model=DashboardAnalitico)
def get_dashboard_analitico(
    *,
    session: Session = Depends(get_session),
    janela_dias: int = 7,
    limite: int = 20,
):
    """
    [ADMIN] Retorna indicadores operacionais para controle de contas, vendas e vencimentos.
    """
    if janela_dias < 1:
        janela_dias = 1
    if janela_dias > 90:
        janela_dias = 90
    if limite < 1:
        limite = 1
    if limite > 100:
        limite = 100

    today = datetime.date.today()

    produtos = session.exec(select(Produto)).all()
    estoque = session.exec(select(EstoqueConta)).all()
    contas_mae = session.exec(select(ContaMae)).all()

    estoque_ativo = [conta for conta in estoque if conta.is_ativo]
    contas_mae_ativas = [conta for conta in contas_mae if conta.is_ativo]

    pedidos_pendentes = session.exec(
        select(func.count(Pedido.id)).where(Pedido.status_entrega == StatusEntregaPedido.PENDENTE)
    ).first() or 0
    pedidos_com_ticket_aberto = session.exec(
        select(func.count(TicketSuporte.id)).where(TicketSuporte.status == TipoStatusTicket.ABERTO)
    ).first() or 0

    health = DashboardOperationalHealth(
        produtos_ativos=sum(1 for produto in produtos if produto.is_ativo),
        produtos_inativos=sum(1 for produto in produtos if not produto.is_ativo),
        estoque_ativo=len(estoque_ativo),
        estoque_inativo=sum(1 for conta in estoque if not conta.is_ativo),
        estoque_requer_atencao=sum(1 for conta in estoque if conta.is_ativo and conta.requer_atencao),
        estoque_slots_livres=sum(max(conta.max_slots - conta.slots_ocupados, 0) for conta in estoque_ativo),
        estoque_slots_ocupados=sum(conta.slots_ocupados for conta in estoque_ativo),
        contas_mae_ativas=len(contas_mae_ativas),
        contas_mae_inativas=sum(1 for conta in contas_mae if not conta.is_ativo),
        contas_mae_slots_livres=sum(max(conta.max_slots - conta.slots_ocupados, 0) for conta in contas_mae_ativas),
        contas_mae_slots_ocupados=sum(conta.slots_ocupados for conta in contas_mae_ativas),
        pedidos_pendentes=int(pedidos_pendentes),
        pedidos_com_ticket_aberto=int(pedidos_com_ticket_aberto),
    )

    stmt_pedidos = (
        select(
            Pedido,
            Produto.nome.label("produto_nome"),
            Usuario.nome_completo.label("usuario_nome_completo"),
            Usuario.telegram_id.label("usuario_telegram_id"),
            EstoqueConta.instrucoes_especificas,
        )
        .join(Produto, Pedido.produto_id == Produto.id)
        .join(Usuario, Pedido.usuario_id == Usuario.id)
        .join(EstoqueConta, Pedido.estoque_conta_id == EstoqueConta.id, isouter=True)
        .where(Pedido.status_entrega == StatusEntregaPedido.ENTREGUE)
        .order_by(Pedido.criado_em.desc())
    )

    vencendo_hoje = 0
    vencendo_7d = 0
    expirados = 0
    proximos_vencimentos: list[DashboardExpiringPedido] = []
    expirados_recentes: list[DashboardExpiringPedido] = []

    for pedido, produto_nome, usuario_nome, usuario_tid, instrucoes_especificas in session.exec(stmt_pedidos).all():
        data_expiracao, origem_expiracao = resolver_data_expiracao_pedido(
            session=session,
            pedido_id=pedido.id,
            email_cliente=pedido.email_cliente,
            estoque_conta_id=pedido.estoque_conta_id,
            conta_mae_id=pedido.conta_mae_id,
        )
        if not data_expiracao:
            continue

        dias_restantes = (data_expiracao - today).days
        if dias_restantes == 0:
            vencendo_hoje += 1
        if 0 <= dias_restantes <= 7:
            vencendo_7d += 1
        if dias_restantes < 0:
            expirados += 1

        if dias_restantes > janela_dias:
            continue

        item = DashboardExpiringPedido(
            pedido_id=pedido.id,
            produto_nome=produto_nome,
            usuario_nome_completo=usuario_nome,
            usuario_telegram_id=usuario_tid,
            email_cliente=pedido.email_cliente,
            entrega_info=instrucoes_especificas or pedido.email_cliente,
            data_expiracao=data_expiracao,
            dias_restantes=dias_restantes,
            origem_expiracao=origem_expiracao,
        )
        if dias_restantes < 0:
            expirados_recentes.append(item)
        else:
            proximos_vencimentos.append(item)

    proximos_vencimentos.sort(key=lambda item: (item.dias_restantes, item.produto_nome, item.usuario_nome_completo))
    expirados_recentes.sort(key=lambda item: (item.dias_restantes, item.produto_nome, item.usuario_nome_completo), reverse=True)

    return DashboardAnalitico(
        vencendo_hoje=vencendo_hoje,
        vencendo_7d=vencendo_7d,
        expirados=expirados,
        pedidos_pendentes=int(pedidos_pendentes),
        pedidos_com_ticket_aberto=int(pedidos_com_ticket_aberto),
        health=health,
        proximos_vencimentos=proximos_vencimentos[:limite],
        expirados_recentes=expirados_recentes[:limite],
    )
