from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.api import api_router as api_router_v1

# --- Pré-carregamento dos Models (importante, mantenha) ---
# Precisamos importar as classes explícitas para o .model_rebuild()
from app.models.base import *
from app.models.usuario_models import Usuario, RecargaSaldo, SugestaoStreaming
from app.models.produto_models import Produto, EstoqueConta
from app.models.pedido_models import Pedido
from app.models.suporte_models import TicketSuporte, GiftCard
# --- Fim do pré-carregamento ---


# --- INÍCIO DA CORREÇÃO PYDANTIC ---
# Este bloco corrige o erro: "PydanticUserError: ... not fully defined"
# Ele resolve as referências circulares (ex: "Pedido" em Usuario e "Usuario" em Pedido)
print("Reconstruindo modelos SQLModel...")
Usuario.model_rebuild()
RecargaSaldo.model_rebuild()
SugestaoStreaming.model_rebuild()
Produto.model_rebuild()
EstoqueConta.model_rebuild()
Pedido.model_rebuild()
TicketSuporte.model_rebuild()
GiftCard.model_rebuild()
print("Modelos reconstruídos com sucesso.")
# --- FIM DA CORREÇÃO PYDANTIC ---


# 2. Cria a instância da aplicação
app = FastAPI(
    title="Bot de Vendas API",
    version="0.1.0",
    description="A API para o bot de vendas de streaming no Telegram."
)

# 3. --- Bloco de CORS ---
origins = [
    "http://localhost:5173",
    "http://localhost:5174", 
    "http://localhost:3000", 
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# --- FIM DO BLOCO DE CORS ---

# 4. Endpoint "Raiz" para Health Check
@app.get("/", tags=["Health Check"])
def read_root():
    return {"status": "ok"}

# 5. Inclui todos os nossos endpoints da V1
# (Esta linha DEVE vir DEPOIS do bloco de .model_rebuild())
app.include_router(api_router_v1, prefix="/api/v1")