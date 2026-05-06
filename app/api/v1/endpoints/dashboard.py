import uuid
import datetime
from decimal import Decimal
from fastapi import APIRouter, Depends
from sqlmodel import Session, select
from sqlalchemy import func # Importamos 'func' para usar 'func.count' e 'func.sum'
from typing import List

from app.db.database import get_session
from app.core.runtime import API_STARTED_AT
from app.models.usuario_models import Usuario
from app.models.pedido_models import Pedido
from app.models.produto_models import Produto, EstoqueConta
from app.models.conta_mae_models import ContaMae
from app.models.suporte_models import TicketSuporte
from app.models.base import StatusEntregaPedido, TipoStatusTicket
from app.schemas.dashboard_schemas import (
    DashboardAnalitico,
    DashboardDistributionPoint,
    DashboardExpiringPedido,
    DashboardHourlyActivityPoint,
    DashboardKPIs,
    DashboardIntMetric,
    DashboardMoneyMetric,
    DashboardOperationalHealth,
    DashboardOverview,
    DashboardOverviewKPIs,
    DashboardRevenueSeriesPoint,
    DashboardSystemStatus,
    DashboardTopProduto,
    DashboardEstoqueBaixo,
    DashboardRecentPedido
)
from app.api.v1.deps import get_current_admin_user # O "Cadeado" do Admin
from app.services.pedido_expiracao_service import resolver_data_expiracao_pedido

# Roteador para o Dashboard (só admin)
router = APIRouter(dependencies=[Depends(get_current_admin_user)])

# --- ENDPOINTS DE DASHBOARD ---

def _decimal_or_zero(value) -> Decimal:
    return value or Decimal("0.0")


def _delta_percent(current: Decimal | int, previous: Decimal | int) -> float | None:
    if previous == 0:
        return None
    return round(float((Decimal(current) - Decimal(previous)) / Decimal(previous) * Decimal("100")), 1)


def _format_uptime(seconds: int) -> str:
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _get_system_status(session: Session) -> DashboardSystemStatus:
    server_time = datetime.datetime.utcnow()
    uptime_seconds = max(0, int((server_time - API_STARTED_AT).total_seconds()))
    database_status = "ok"
    try:
        session.exec(select(1)).first()
    except Exception:
        database_status = "error"

    return DashboardSystemStatus(
        status="operational" if database_status == "ok" else "degraded",
        database_status=database_status,
        server_time=server_time,
        api_started_at=API_STARTED_AT,
        uptime_seconds=uptime_seconds,
        uptime_label=_format_uptime(uptime_seconds),
    )


@router.get("/system-status", response_model=DashboardSystemStatus)
def get_dashboard_system_status(
    *,
    session: Session = Depends(get_session),
):
    """
    [ADMIN] Retorna saúde operacional real do processo da API.
    """
    return _get_system_status(session)


@router.get("/overview", response_model=DashboardOverview)
def get_dashboard_overview(
    *,
    session: Session = Depends(get_session),
    period_days: int = 7,
):
    """
    [ADMIN] Retorna agregados reais para os cards e gráficos do dashboard.
    """
    if period_days not in (7, 30, 90):
        period_days = 7

    now = datetime.datetime.utcnow()
    current_24h_start = now - datetime.timedelta(hours=24)
    previous_24h_start = now - datetime.timedelta(hours=48)

    current_revenue = _decimal_or_zero(
        session.exec(select(func.sum(Pedido.valor_pago)).where(Pedido.criado_em >= current_24h_start)).first()
    )
    previous_revenue = _decimal_or_zero(
        session.exec(
            select(func.sum(Pedido.valor_pago)).where(
                Pedido.criado_em >= previous_24h_start,
                Pedido.criado_em < current_24h_start,
            )
        ).first()
    )

    current_orders = session.exec(
        select(func.count(Pedido.id)).where(Pedido.criado_em >= current_24h_start)
    ).first() or 0
    previous_orders = session.exec(
        select(func.count(Pedido.id)).where(
            Pedido.criado_em >= previous_24h_start,
            Pedido.criado_em < current_24h_start,
        )
    ).first() or 0

    active_stock_accounts = session.exec(
        select(func.count(EstoqueConta.id)).where(EstoqueConta.is_ativo == True)
    ).first() or 0
    active_parent_accounts = session.exec(
        select(func.count(ContaMae.id)).where(ContaMae.is_ativo == True)
    ).first() or 0
    tickets_abertos = session.exec(
        select(func.count(TicketSuporte.id)).where(TicketSuporte.status == TipoStatusTicket.ABERTO)
    ).first() or 0

    today = datetime.date.today()
    delivered_orders = session.exec(
        select(Pedido).where(Pedido.status_entrega == StatusEntregaPedido.ENTREGUE)
    ).all()
    vencendo_hoje = 0
    for pedido in delivered_orders:
        data_expiracao, _ = resolver_data_expiracao_pedido(
            session=session,
            pedido_id=pedido.id,
            email_cliente=pedido.email_cliente,
            estoque_conta_id=pedido.estoque_conta_id,
            conta_mae_id=pedido.conta_mae_id,
        )
        if data_expiracao and data_expiracao == today:
            vencendo_hoje += 1

    period_start_date = today - datetime.timedelta(days=period_days - 1)
    period_start_datetime = datetime.datetime.combine(period_start_date, datetime.time.min)
    revenue_rows = session.exec(
        select(
            func.date(Pedido.criado_em).label("dia"),
            func.sum(Pedido.valor_pago).label("revenue"),
            func.count(Pedido.id).label("orders"),
        )
        .where(Pedido.criado_em >= period_start_datetime)
        .group_by(func.date(Pedido.criado_em))
        .order_by(func.date(Pedido.criado_em))
    ).all()
    revenue_by_day = {
        row.dia: {
            "revenue": _decimal_or_zero(row.revenue),
            "orders": int(row.orders or 0),
        }
        for row in revenue_rows
    }
    revenue_series: list[DashboardRevenueSeriesPoint] = []
    for offset in range(period_days):
        day = period_start_date + datetime.timedelta(days=offset)
        data = revenue_by_day.get(day, {"revenue": Decimal("0.0"), "orders": 0})
        revenue_series.append(
            DashboardRevenueSeriesPoint(
                date=day,
                label=day.strftime("%d/%m"),
                revenue=data["revenue"],
                orders=data["orders"],
            )
        )

    hourly_start = now.replace(minute=0, second=0, microsecond=0) - datetime.timedelta(hours=23)
    hourly_rows = session.exec(
        select(
            func.date_trunc("hour", Pedido.criado_em).label("hour_start"),
            func.count(Pedido.id).label("orders"),
        )
        .where(Pedido.criado_em >= hourly_start)
        .group_by(func.date_trunc("hour", Pedido.criado_em))
        .order_by(func.date_trunc("hour", Pedido.criado_em))
    ).all()
    orders_by_hour = {row.hour_start.replace(tzinfo=None): int(row.orders or 0) for row in hourly_rows}
    hourly_activity: list[DashboardHourlyActivityPoint] = []
    for offset in range(24):
        hour_start = hourly_start + datetime.timedelta(hours=offset)
        hourly_activity.append(
            DashboardHourlyActivityPoint(
                hour_start=hour_start,
                label=hour_start.strftime("%Hh"),
                orders=orders_by_hour.get(hour_start, 0),
            )
        )

    stock_distribution_rows = session.exec(
        select(Produto.nome.label("name"), func.count(EstoqueConta.id).label("value"))
        .join(Produto, EstoqueConta.produto_id == Produto.id)
        .where(EstoqueConta.is_ativo == True)
        .group_by(Produto.nome)
    ).all()
    parent_distribution_rows = session.exec(
        select(Produto.nome.label("name"), func.count(ContaMae.id).label("value"))
        .join(Produto, ContaMae.produto_id == Produto.id)
        .where(ContaMae.is_ativo == True)
        .group_by(Produto.nome)
    ).all()
    distribution_map: dict[str, int] = {}
    for row in [*stock_distribution_rows, *parent_distribution_rows]:
        distribution_map[row.name] = distribution_map.get(row.name, 0) + int(row.value or 0)
    account_distribution = [
        DashboardDistributionPoint(name=name, value=value)
        for name, value in sorted(distribution_map.items(), key=lambda item: item[1], reverse=True)[:6]
    ]

    return DashboardOverview(
        period_days=period_days,
        kpis=DashboardOverviewKPIs(
            receita_24h=DashboardMoneyMetric(
                value=current_revenue,
                delta_percent=_delta_percent(current_revenue, previous_revenue),
            ),
            vendas_24h=DashboardIntMetric(
                value=int(current_orders),
                delta_percent=_delta_percent(int(current_orders), int(previous_orders)),
            ),
            contas_ativas=DashboardIntMetric(
                value=int(active_stock_accounts + active_parent_accounts),
                delta_percent=None,
            ),
            alertas=DashboardIntMetric(
                value=int(tickets_abertos + vencendo_hoje),
                delta_percent=None,
            ),
        ),
        revenue_series=revenue_series,
        hourly_activity=hourly_activity,
        account_distribution=account_distribution,
        system_status=_get_system_status(session),
    )

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
    if limite > 500:
        limite = 500

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
            EstoqueConta.login.label("estoque_login"),
            EstoqueConta.instrucoes_especificas,
            ContaMae.login.label("conta_mae_login"),
        )
        .join(Produto, Pedido.produto_id == Produto.id)
        .join(Usuario, Pedido.usuario_id == Usuario.id)
        .join(EstoqueConta, Pedido.estoque_conta_id == EstoqueConta.id, isouter=True)
        .join(ContaMae, Pedido.conta_mae_id == ContaMae.id, isouter=True)
        .where(Pedido.status_entrega == StatusEntregaPedido.ENTREGUE)
        .order_by(Pedido.criado_em.desc())
    )

    vencendo_hoje = 0
    vencendo_7d = 0
    expirados = 0
    proximos_vencimentos: list[DashboardExpiringPedido] = []
    expirados_recentes: list[DashboardExpiringPedido] = []

    for pedido, produto_nome, usuario_nome, usuario_tid, estoque_login, instrucoes_especificas, conta_mae_login in session.exec(stmt_pedidos).all():
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
            conta_login=conta_mae_login or estoque_login,
            tipo_conta="conta_mae" if conta_mae_login else ("estoque" if estoque_login else None),
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
