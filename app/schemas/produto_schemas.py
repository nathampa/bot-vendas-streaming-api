import uuid
from decimal import Decimal
from typing import Optional
from sqlmodel import SQLModel
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

# -----------------------------------------------------------------
# Schema para CRIAÇÃO (o que o Admin usa no painel)
# -----------------------------------------------------------------
class ProdutoCreate(SQLModel):
    nome: str
    descricao: Optional[str]
    preco: Decimal
    is_ativo: bool = True

# -----------------------------------------------------------------
# Schema para ATUALIZAÇÃO (o que o Admin usa no painel)
# -----------------------------------------------------------------
class ProdutoUpdate(SQLModel):
    nome: Optional[str] = None
    descricao: Optional[str] = None
    preco: Optional[Decimal] = None
    is_ativo: Optional[bool] = None

class ProdutoAdminRead(ProdutoRead):
    is_ativo: bool
    criado_em: datetime.datetime