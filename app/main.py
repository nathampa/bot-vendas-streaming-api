from fastapi import FastAPI
# 1. Importe o Middleware de CORS
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.api import api_router as api_router_v1

# --- Pré-carregamento dos Models (importante, mantenha) ---
from app.models.base import *
from app.models.usuario_models import *
from app.models.produto_models import *
from app.models.pedido_models import *
from app.models.suporte_models import *
# --- Fim do pré-carregamento ---

# 2. Cria a instância da aplicação
app = FastAPI(
    title="Bot de Vendas API",
    version="0.1.0",
    description="A API para o bot de vendas de streaming no Telegram."
)

# 3. --- INÍCIO DA CORREÇÃO DE CORS ---
# Define de quais "origens" (sites) o navegador pode aceitar pedidos.
# No nosso caso, o seu app React rodando em localhost:5173.
origins = [
    "http://localhost:5173",
    "http://localhost:5174", # (Um backup comum do Vite)
    "http://localhost:3000", # (O padrão antigo do create-react-app)
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,       # Quais origens são permitidas
    allow_credentials=True,    # Permite cookies (não usamos, mas é bom ter)
    allow_methods=["*"],         # Permite todos os métodos (GET, POST, PUT, etc.)
    allow_headers=["*"],         # Permite todos os cabeçalhos
)
# --- FIM DA CORREÇÃO DE CORS ---

# 4. Endpoint "Raiz" para Health Check
@app.get("/", tags=["Health Check"])
def read_root():
    return {"status": "ok"}

# 5. Inclui todos os nossos endpoints da V1
app.include_router(api_router_v1, prefix="/api/v1")