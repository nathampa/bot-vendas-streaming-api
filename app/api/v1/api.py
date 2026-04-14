from fastapi import APIRouter, Depends

from app.api.v1.deps import get_bot_api_key
from app.api.v1.endpoints import (
    auth,
    compras,
    configuracoes,
    contas_mae,
    dashboard,
    email_monitor,
    estoque,
    giftcards,
    pedidos,
    produtos,
    recargas,
    sugestoes,
    tickets,
    usuarios,
)

api_router = APIRouter()
bot_deps = [Depends(get_bot_api_key)]

api_router.include_router(produtos.router, prefix="/produtos", tags=["Produtos (Bot)"], dependencies=bot_deps)
api_router.include_router(recargas.router, prefix="/recargas", tags=["Recargas (Bot)"], dependencies=bot_deps)
api_router.include_router(compras.router, prefix="/compras", tags=["Compras (Bot)"], dependencies=bot_deps)
api_router.include_router(tickets.router, prefix="/tickets", tags=["Tickets (Bot)"], dependencies=bot_deps)
api_router.include_router(giftcards.router, prefix="/giftcards", tags=["GiftCards (Bot)"], dependencies=bot_deps)
api_router.include_router(sugestoes.router, prefix="/sugestoes", tags=["Sugestões (Bot)"], dependencies=bot_deps)
api_router.include_router(usuarios.router, prefix="/usuarios", tags=["Usuários (Bot)"], dependencies=bot_deps)
api_router.include_router(configuracoes.bot_router, prefix="/configuracoes", tags=["Configurações (Bot)"], dependencies=bot_deps)
api_router.include_router(recargas.webhook_router, prefix="/webhook", tags=["Webhooks (Externo)"])

api_router.include_router(produtos.admin_router, prefix="/admin/produtos", tags=["Admin - Produtos"])
api_router.include_router(auth.router, prefix="/admin", tags=["Admin - Autenticação"])
api_router.include_router(estoque.router, prefix="/admin/estoque", tags=["Admin - Estoque"])
api_router.include_router(tickets.admin_router, prefix="/admin/tickets", tags=["Admin - Tickets"])
api_router.include_router(giftcards.admin_router, prefix="/admin/giftcards", tags=["Admin - GiftCards"])
api_router.include_router(sugestoes.admin_router, prefix="/admin/sugestoes", tags=["Admin - Sugestões"])
api_router.include_router(dashboard.router, prefix="/admin/dashboard", tags=["Admin - Dashboard"])
api_router.include_router(pedidos.router, prefix="/admin/pedidos", tags=["Admin - Pedidos"])
api_router.include_router(usuarios.admin_router, prefix="/admin/usuarios", tags=["Admin - Usuários"])
api_router.include_router(recargas.admin_router, prefix="/admin/recargas", tags=["Admin - Recargas"])
api_router.include_router(configuracoes.router, prefix="/admin/configuracoes", tags=["Admin - Configurações"])
api_router.include_router(contas_mae.router, prefix="/admin/contas-mae", tags=["Admin - Contas Mãe"])
api_router.include_router(email_monitor.router, prefix="/admin/email-monitor", tags=["Admin - Email Monitor"])
