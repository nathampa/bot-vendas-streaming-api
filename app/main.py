from contextlib import asynccontextmanager
import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.api import api_router as api_router_v1
from app.core.config import settings
from app.models.base import *
from app.models.conta_mae_models import ContaMae, ContaMaeConvite
from app.models.email_monitor_models import (
    AuditLog,
    EmailMonitorAccount,
    EmailMonitorAlertEvent,
    EmailMonitorFolderState,
    EmailMonitorMessage,
    EmailMonitorMessageMatch,
    EmailMonitorRule,
    EmailMonitorSyncRun,
)
from app.models.pedido_models import Pedido
from app.models.produto_models import EstoqueConta, Produto
from app.models.suporte_models import GiftCard, TicketSuporte
from app.models.usuario_models import AjusteSaldoUsuario, RecargaSaldo, SugestaoStreaming, Usuario
from app.schemas.compra_schemas import CompraCreateRequest, CompraCreateResponse
from app.schemas.conta_mae_schemas import (
    ContaMaeAdminDetails,
    ContaMaeAdminRead,
    ContaMaeConviteCreate,
    ContaMaeConviteRead,
    ContaMaeCreate,
    ContaMaeUpdate,
)
from app.schemas.email_monitor_schemas import (
    EmailMonitorAccountDetail,
    EmailMonitorAccountRead,
    EmailMonitorAlertItem,
    EmailMonitorAuditLogRead,
    EmailMonitorConnectionTestResult,
    EmailMonitorMessageDetail,
    EmailMonitorMessageListItem,
    EmailMonitorMessageMatchRead,
    EmailMonitorMessagesPage,
    EmailMonitorOverviewMessageItem,
    EmailMonitorOverviewResponse,
    EmailMonitorRuleRead,
    EmailMonitorSyncBatchResponse,
    EmailMonitorSyncFailureItem,
    EmailMonitorSyncResult,
)
from app.schemas.pedido_schemas import PedidoAdminConta, PedidoAdminDetails, PedidoAdminList, PedidoAdminContaMae
from app.schemas.produto_schemas import ProdutoAdminRead, ProdutoCreate, ProdutoRead, ProdutoUpdate
from app.services.email_monitor_service import start_scheduler

print("Reconstruindo modelos e schemas SQLModel...")
Usuario.model_rebuild()
RecargaSaldo.model_rebuild()
AjusteSaldoUsuario.model_rebuild()
SugestaoStreaming.model_rebuild()
Produto.model_rebuild()
EstoqueConta.model_rebuild()
ContaMae.model_rebuild()
ContaMaeConvite.model_rebuild()
Pedido.model_rebuild()
TicketSuporte.model_rebuild()
GiftCard.model_rebuild()
AuditLog.model_rebuild()
EmailMonitorAccount.model_rebuild()
EmailMonitorFolderState.model_rebuild()
EmailMonitorRule.model_rebuild()
EmailMonitorMessage.model_rebuild()
EmailMonitorMessageMatch.model_rebuild()
EmailMonitorAlertEvent.model_rebuild()
EmailMonitorSyncRun.model_rebuild()

ProdutoRead.model_rebuild()
ProdutoCreate.model_rebuild()
ProdutoUpdate.model_rebuild()
ProdutoAdminRead.model_rebuild()
CompraCreateRequest.model_rebuild()
CompraCreateResponse.model_rebuild()
PedidoAdminConta.model_rebuild()
PedidoAdminContaMae.model_rebuild()
PedidoAdminList.model_rebuild()
PedidoAdminDetails.model_rebuild()
ContaMaeCreate.model_rebuild()
ContaMaeUpdate.model_rebuild()
ContaMaeAdminRead.model_rebuild()
ContaMaeAdminDetails.model_rebuild()
ContaMaeConviteRead.model_rebuild()
ContaMaeConviteCreate.model_rebuild()
EmailMonitorAccountRead.model_rebuild()
EmailMonitorAccountDetail.model_rebuild()
EmailMonitorRuleRead.model_rebuild()
EmailMonitorConnectionTestResult.model_rebuild()
EmailMonitorOverviewResponse.model_rebuild()
EmailMonitorOverviewMessageItem.model_rebuild()
EmailMonitorSyncFailureItem.model_rebuild()
EmailMonitorAlertItem.model_rebuild()
EmailMonitorMessageListItem.model_rebuild()
EmailMonitorMessagesPage.model_rebuild()
EmailMonitorMessageMatchRead.model_rebuild()
EmailMonitorMessageDetail.model_rebuild()
EmailMonitorSyncResult.model_rebuild()
EmailMonitorSyncBatchResponse.model_rebuild()
EmailMonitorAuditLogRead.model_rebuild()
print("Modelos e schemas reconstruídos com sucesso.")

_scheduler_stop_event = threading.Event()
_scheduler_thread = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _scheduler_thread
    if settings.IMAP_SYNC_WORKER_ENABLED:
        _scheduler_stop_event.clear()
        _scheduler_thread = start_scheduler(_scheduler_stop_event)
    try:
        yield
    finally:
        _scheduler_stop_event.set()
        if _scheduler_thread is not None:
            _scheduler_thread.join(timeout=2)


app = FastAPI(
    title="Bot de Vendas API",
    version="0.1.0",
    description="A API para o bot de vendas de streaming no Telegram.",
    lifespan=lifespan,
)

origins = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:3000",
    "https://localhost:5173",
    "https://localhost:5174",
    "https://localhost:3000",
    "http://127.0.0.1:3001",
    "https://127.0.0.1:3001",
    "http://177.11.152.132:3001",
    "http://painel.ferreirastreamings.com.br",
    "http://api.ferreirastreamings.com.br",
    "https://painel.ferreirastreamings.com.br",
    "https://api.ferreirastreamings.com.br",
    "http://35.222.225.107:3001",
    "http://35.222.225.107",
    "http://35.199.119.89:3001",
    "http://35.199.119.89",
    "https://35.199.119.89:3001",
    "https://35.199.119.89"
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
