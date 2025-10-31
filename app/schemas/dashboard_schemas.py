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