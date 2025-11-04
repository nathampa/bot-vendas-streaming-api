from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, List, TYPE_CHECKING

from app.models.base import *
from app.models.usuario_models import Usuario, RecargaSaldo, SugestaoStreaming
from app.models.produto_models import Produto, EstoqueConta
from app.models.pedido_models import Pedido
from app.models.suporte_models import TicketSuporte, GiftCard

from app.schemas.pedido_schemas import PedidoAdminConta, PedidoAdminList, PedidoAdminDetails
from app.schemas.produto_schemas import ProdutoRead, ProdutoCreate, ProdutoUpdate, ProdutoAdminRead
from app.schemas.compra_schemas import CompraCreateRequest, CompraCreateResponse

print("Reconstruindo modelos e schemas SQLModel...")
Usuario.model_rebuild()
RecargaSaldo.model_rebuild()
SugestaoStreaming.model_rebuild()
Produto.model_rebuild()
EstoqueConta.model_rebuild()
Pedido.model_rebuild()
TicketSuporte.model_rebuild()
GiftCard.model_rebuild()

ProdutoRead.model_rebuild()
ProdutoCreate.model_rebuild()
ProdutoUpdate.model_rebuild()
ProdutoAdminRead.model_rebuild()
CompraCreateRequest.model_rebuild()
CompraCreateResponse.model_rebuild()
PedidoAdminConta.model_rebuild()
PedidoAdminList.model_rebuild()
PedidoAdminDetails.model_rebuild()

print("Modelos e schemas reconstruídos com sucesso.")

from app.api.v1.api import api_router as api_router_v1

app = FastAPI(
    title="Bot de Vendas API",
    version="0.1.0",
    description="A API para o bot de vendas de streaming no Telegram."
)

origins = [
    "http://localhost:5173",
    "http://localhost:5174", 
    "http://localhost:3000", 
    "http://127.0.0.1:3001", 
    "http://177.11.152.132:3001"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", tags=["Health Check"])
def read_root():
    return {"status": "ok"}

app.include_router(api_router_v1, prefix="/api/v1")