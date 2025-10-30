from fastapi import APIRouter

# 1. Importa os DOIS roteadores do arquivo 'produtos'
from app.api.v1.endpoints import produtos, auth
from app.api.v1.endpoints import estoque

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

# -------------------------------------------------
# Rota de ADMIN (Painel)
# -------------------------------------------------
api_router.include_router(
    produtos.admin_router, # O novo roteador de admin
    prefix="/admin/produtos", # Prefixo diferente
    tags=["Admin - Produtos"]
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