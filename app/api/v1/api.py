from fastapi import APIRouter, Depends

# Importa todos os nossos endpoints
from app.api.v1.endpoints import (
    produtos, auth, estoque, recargas, compras, tickets, giftcards, sugestoes, dashboard, usuarios
)
# Importa o nosso novo "cadeado"
from app.api.v1.deps import get_bot_api_key

# Este é o roteador principal da v1
api_router = APIRouter()

# --- Rotas do Bot (AGORA PROTEGIDAS) ---
bot_deps = [Depends(get_bot_api_key)]

api_router.include_router(
    produtos.router, prefix="/produtos", tags=["Produtos (Bot)"], dependencies=bot_deps
)
api_router.include_router(
    recargas.router, prefix="/recargas", tags=["Recargas (Bot)"], dependencies=bot_deps
)
api_router.include_router(
    compras.router, prefix="/compras", tags=["Compras (Bot)"], dependencies=bot_deps
)
api_router.include_router(
    tickets.router, prefix="/tickets", tags=["Tickets (Bot)"], dependencies=bot_deps
)
api_router.include_router(
    giftcards.router, prefix="/giftcards", tags=["GiftCards (Bot)"], dependencies=bot_deps
)
api_router.include_router(
    sugestoes.router, prefix="/sugestoes", tags=["Sugestões (Bot)"], dependencies=bot_deps
)

api_router.include_router(
    usuarios.router,
    prefix="/usuarios", 
    tags=["Usuários (Bot)"], 
    dependencies=bot_deps
)

# --- Rotas de Webhook (PÚBLICAS - SEM O CADEADO) ---
# (O webhook de recarga NÃO PODE ter a chave de API, 
# pois é o Mercado Pago que o chama, não o nosso bot)
api_router.include_router(
    recargas.webhook_router, prefix="/webhook", tags=["Webhooks (Externo)"]
)

# --- Rotas de Admin (PROTEGIDAS PELO LOGIN JWT) ---
# (Estas rotas usam o seu próprio cadeado JWT, por isso não mexemos)
api_router.include_router(
    produtos.admin_router, prefix="/admin/produtos", tags=["Admin - Produtos"]
)
api_router.include_router(
    auth.router, prefix="/admin", tags=["Admin - Autenticação"]
)
api_router.include_router(
    estoque.router, prefix="/admin/estoque", tags=["Admin - Estoque"]
)
api_router.include_router(
    tickets.admin_router, prefix="/admin/tickets", tags=["Admin - Tickets"]
)
api_router.include_router(
    giftcards.admin_router, prefix="/admin/giftcards", tags=["Admin - GiftCards"]
)
api_router.include_router(
    sugestoes.admin_router, prefix="/admin/sugestoes", tags=["Admin - Sugestões"]
)
api_router.include_router(
    dashboard.router, prefix="/admin/dashboard", tags=["Admin - Dashboard"]
)