import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from typing import List

from app.db.database import get_session
from app.models.usuario_models import Usuario
from app.models.produto_models import Produto
from app.schemas.produto_schemas import (
    ProdutoRead, 
    ProdutoCreate, 
    ProdutoUpdate, 
    ProdutoAdminRead
)
from app.api.v1.deps import get_current_admin_user # <-- 1. IMPORTA O "CADEADO"

# ===============================================================
# Roteador PÚBLICO (para o Bot)
# ===============================================================
# (Este é o roteador que já tínhamos)
router = APIRouter()

@router.get(
    "/",
    response_model=List[ProdutoRead]
)
def get_produtos_ativos(session: Session = Depends(get_session)):
    """
    Endpoint para o bot listar todos os produtos ATIVOS.
    """
    produtos = session.exec(select(Produto).where(Produto.is_ativo == True)).all()
    return produtos

# ===============================================================
# Roteador de ADMIN (para o Painel React)
# ===============================================================
# Criamos um roteador separado para os endpoints de admin
admin_router = APIRouter()

# 2. APLICA O "CADEADO"
# Todos os endpoints abaixo exigirão um token de admin válido.
# O 'Depends(get_current_admin_user)' é o nosso cadeado.
# A variável 'current_admin' será preenchida com o objeto Usuario do admin
# (embora não precisemos usá-la em todos os endpoints, ela força a validação)
@admin_router.post(
    "/",
    response_model=ProdutoAdminRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_current_admin_user)] # Protege a rota
)
def create_produto(
    *, 
    session: Session = Depends(get_session), 
    produto_in: ProdutoCreate
):
    """
    [ADMIN] Cria um novo produto no catálogo.
    """
    # Cria o objeto do model a partir do schema
    produto = Produto.model_validate(produto_in)
    session.add(produto)
    session.commit()
    session.refresh(produto)
    return produto

@admin_router.get(
    "/",
    response_model=List[ProdutoAdminRead],
    dependencies=[Depends(get_current_admin_user)] # Protege a rota
)
def get_todos_os_produtos(session: Session = Depends(get_session)):
    """
    [ADMIN] Lista TODOS os produtos (ativos e inativos).
    """
    produtos = session.exec(select(Produto)).all()
    return produtos

@admin_router.put(
    "/{produto_id}",
    response_model=ProdutoAdminRead,
    dependencies=[Depends(get_current_admin_user)] # Protege a rota
)
def update_produto(
    *,
    session: Session = Depends(get_session),
    produto_id: uuid.UUID,
    produto_in: ProdutoUpdate
):
    """
    [ADMIN] Atualiza um produto (muda preço, nome, ou desativa).
    """
    produto = session.get(Produto, produto_id)
    if not produto:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
        
    # Pega os dados do schema de update e os aplica no model
    # 'exclude_unset=True' é crucial: ele só atualiza os campos que
    # o admin realmente enviou no JSON.
    update_data = produto_in.model_dump(exclude_unset=True)
    
    # Atualiza o objeto do model
    produto.sqlmodel_update(update_data)
    
    session.add(produto)
    session.commit()
    session.refresh(produto)
    return produto