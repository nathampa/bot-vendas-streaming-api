from fastapi import FastAPI
from app.api.v1.api import api_router as api_router_v1 # Importa o agregador

# Pré-carrega todos os models para o SQLAlchemy/SQLModel
# Isso resolve os erros de "failed to locate a name" (ex: 'Pedido')
# ao garantir que todas as classes de tabela estejam na memória
# antes que qualquer endpoint as utilize.
from app.models.base import *
from app.models.usuario_models import *
from app.models.produto_models import *
from app.models.pedido_models import *
from app.models.suporte_models import *

# 1. Cria a instância da aplicação FastAPI
app = FastAPI(
    title="Bot de Vendas API",
    version="0.1.0",
    description="A API para o bot de vendas de streaming no Telegram."
)

# 2. Endpoint "Raiz" para Health Check
# (Para sabermos se a API está online)
@app.get("/", tags=["Health Check"])
def read_root():
    return {"status": "ok"}

# 3. Inclui todos os nossos endpoints da V1
# Todos eles ficarão sob o prefixo /api/v1
app.include_router(api_router_v1, prefix="/api/v1")