from fastapi import APIRouter

# 1. Importa os DOIS roteadores do arquivo 'produtos'
from app.api.v1.endpoints import produtos, auth, estoque,compras,recargas,tickets

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

# --- Rotas de Webhook (Públicas) ---
api_router.include_router(
    recargas.webhook_router, # <-- 1. ADICIONE O NOVO ROTEADOR
    prefix="/webhook", # <-- 2. PREFIXO DIFERENTE
    tags=["Webhooks (Externo)"]
)

# -------------------------------------------------
# Rota de ADMIN (Painel)
# -------------------------------------------------
api_router.include_router(
    produtos.admin_router, # O novo roteador de admin
    prefix="/admin/produtos", # Prefixo diferente
    tags=["Admin - Produtos"]
)

api_router.include_router(
    tickets.admin_router,
    prefix="/admin/tickets", 
    tags=["Admin - Tickets"]
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
    prefix="/admin/estoque", # Ficará em /api/v1/admin/estoque
    tags=["Admin - Estoque"] # Agrupa na documentação
)