from fastapi import APIRouter

# 1. Importa os DOIS roteadores do arquivo 'produtos'
from app.api.v1.endpoints import produtos, auth, estoque,compras,recargas,tickets, giftcards, sugestoes, dashboard

# Este é o roteador principal da v1
api_router = APIRouter()

# -------------------------------------------------
# Rota PÚBLICA do Bot
# -------------------------------------------------
api_router.include_router(
    produtos.router,  # O roteador público
    prefix="/produtos", 
    tags=["Produtos (Bot)"]
)

api_router.include_router(
    recargas.router,    # O roteador de recargas
    prefix="/recargas", 
    tags=["Recargas (Bot)"]
)

api_router.include_router(
    compras.router,
    prefix="/compras", 
    tags=["Compras (Bot)"]
)

api_router.include_router(
    tickets.router,
    prefix="/tickets", 
    tags=["Tickets (Bot)"]
)

api_router.include_router(
    tickets.router,
    prefix="/tickets", 
    tags=["Tickets (Bot)"]
)

api_router.include_router(
    giftcards.router,
    prefix="/giftcards", 
    tags=["GiftCards (Bot)"]
)

api_router.include_router(
    sugestoes.router,
    prefix="/sugestoes", 
    tags=["Sugestões (Bot)"]
)

# --- Rotas de Webhook (Públicas) ---
api_router.include_router(
    recargas.webhook_router,
    prefix="/webhook",
    tags=["Webhooks (Externo)"]
)

# -------------------------------------------------
# Rota de ADMIN (Painel)
# -------------------------------------------------
api_router.include_router(
    produtos.admin_router,
    prefix="/admin/produtos",
    tags=["Admin - Produtos"]
)

api_router.include_router(
    tickets.admin_router,
    prefix="/admin/tickets", 
    tags=["Admin - Tickets"]
)

api_router.include_router(
    giftcards.admin_router,
    prefix="/admin/giftcards", 
    tags=["Admin - GiftCards"]
)

api_router.include_router(
    sugestoes.admin_router,
    prefix="/admin/sugestoes", 
    tags=["Admin - Sugestões"]
)

api_router.include_router(
    dashboard.router,
    prefix="/admin/dashboard", 
    tags=["Admin - Dashboard"]
)

# -------------------------------------------------
# Rota de Autenticação
# -------------------------------------------------
api_router.include_router(
    auth.router,
    prefix="/admin", 
    tags=["Admin - Autenticação"]
)

# -------------------------------------------------
# Inclui o roteador de Estoque
# -------------------------------------------------
api_router.include_router(
    estoque.router,
    prefix="/admin/estoque",
    tags=["Admin - Estoque"]
)