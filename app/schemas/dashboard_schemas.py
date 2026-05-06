import uuid
import datetime
from decimal import Decimal
from sqlmodel import SQLModel

# -----------------------------------------------------------------
# Schema para os KPIs (Indicadores Principais)
# -----------------------------------------------------------------
class DashboardKPIs(SQLModel):
    faturamento_24h: Decimal
    vendas_24h: int
    novos_usuarios_24h: int
    tickets_abertos: int


class DashboardMoneyMetric(SQLModel):
    value: Decimal
    delta_percent: float | None = None


class DashboardIntMetric(SQLModel):
    value: int
    delta_percent: float | None = None


class DashboardOverviewKPIs(SQLModel):
    receita_24h: DashboardMoneyMetric
    vendas_24h: DashboardIntMetric
    contas_ativas: DashboardIntMetric
    alertas: DashboardIntMetric


class DashboardRevenueSeriesPoint(SQLModel):
    date: datetime.date
    label: str
    revenue: Decimal
    orders: int


class DashboardHourlyActivityPoint(SQLModel):
    hour_start: datetime.datetime
    label: str
    orders: int


class DashboardDistributionPoint(SQLModel):
    name: str
    value: int


class DashboardSystemStatus(SQLModel):
    status: str
    database_status: str
    server_time: datetime.datetime
    api_started_at: datetime.datetime
    uptime_seconds: int
    uptime_label: str


class DashboardOverview(SQLModel):
    period_days: int
    kpis: DashboardOverviewKPIs
    revenue_series: list[DashboardRevenueSeriesPoint]
    hourly_activity: list[DashboardHourlyActivityPoint]
    account_distribution: list[DashboardDistributionPoint]
    system_status: DashboardSystemStatus

# -----------------------------------------------------------------
# Schema para a lista de "Top Produtos"
# -----------------------------------------------------------------
class DashboardTopProduto(SQLModel):
    produto_nome: str
    total_vendas: int
    faturamento_total: Decimal

# -----------------------------------------------------------------
# Schema para a lista de "Estoque Baixo"
# -----------------------------------------------------------------
class DashboardEstoqueBaixo(SQLModel):
    produto_nome: str
    contas_disponiveis: int # Contas com pelo menos 1 slot livre


class DashboardRecentPedido(SQLModel):
    id: uuid.UUID
    produto_nome: str
    valor_pago: Decimal
    criado_em: datetime.datetime
    usuario_telegram_id: int
    nome_completo: str


class DashboardOperationalHealth(SQLModel):
    produtos_ativos: int
    produtos_inativos: int
    estoque_ativo: int
    estoque_inativo: int
    estoque_requer_atencao: int
    estoque_slots_livres: int
    estoque_slots_ocupados: int
    contas_mae_ativas: int
    contas_mae_inativas: int
    contas_mae_slots_livres: int
    contas_mae_slots_ocupados: int
    pedidos_pendentes: int
    pedidos_com_ticket_aberto: int


class DashboardExpiringPedido(SQLModel):
    pedido_id: uuid.UUID
    produto_nome: str
    usuario_nome_completo: str
    usuario_telegram_id: int
    email_cliente: str | None = None
    entrega_info: str | None = None
    data_expiracao: datetime.date
    dias_restantes: int
    origem_expiracao: str | None = None


class DashboardAnalitico(SQLModel):
    vencendo_hoje: int
    vencendo_7d: int
    expirados: int
    pedidos_pendentes: int
    pedidos_com_ticket_aberto: int
    health: DashboardOperationalHealth
    proximos_vencimentos: list[DashboardExpiringPedido]
    expirados_recentes: list[DashboardExpiringPedido]
