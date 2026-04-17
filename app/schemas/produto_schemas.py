import uuid
from decimal import Decimal
from typing import Optional
from sqlmodel import SQLModel
from app.models.base import InviteProviderProduto, TipoEntregaProduto
import datetime

# SQLModel pode ser usado como um 'schema' Pydantic puro
# (sem o 'table=True')

# -----------------------------------------------------------------
# Schema para LEITURA (o que o bot/usuário vê)
# -----------------------------------------------------------------
class ProdutoRead(SQLModel):
    id: uuid.UUID
    nome: str
    descricao: Optional[str]
    preco: Decimal
    tipo_entrega: TipoEntregaProduto
    invite_provider: InviteProviderProduto

# -----------------------------------------------------------------
# Schema para CRIAÇÃO (o que o Admin usa no painel)
# -----------------------------------------------------------------
class ProdutoCreate(SQLModel):
    nome: str
    descricao: Optional[str]
    instrucoes_pos_compra: Optional[str] = None
    preco: Decimal
    is_ativo: bool = True
    tipo_entrega: TipoEntregaProduto = TipoEntregaProduto.AUTOMATICA
    invite_provider: InviteProviderProduto = InviteProviderProduto.NONE

# -----------------------------------------------------------------
# Schema para ATUALIZAÇÃO (o que o Admin usa no painel)
# -----------------------------------------------------------------
class ProdutoUpdate(SQLModel):
    nome: Optional[str] = None
    descricao: Optional[str] = None
    instrucoes_pos_compra: Optional[str] = None
    preco: Optional[Decimal] = None
    is_ativo: Optional[bool] = None
    tipo_entrega: Optional[TipoEntregaProduto] = None
    invite_provider: Optional[InviteProviderProduto] = None

class ProdutoAdminRead(ProdutoRead):
    is_ativo: bool
    criado_em: datetime.datetime
    instrucoes_pos_compra: Optional[str] = None
