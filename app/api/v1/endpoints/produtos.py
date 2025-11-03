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
from app.api.v1.deps import get_current_admin_user

# ===============================================================
# Roteador PÚBLICO (para o Bot)
# ===============================================================
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
admin_router = APIRouter()

@admin_router.post(
    "/",
    response_model=ProdutoAdminRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_current_admin_user)]
)
def create_produto(
    *, 
    session: Session = Depends(get_session), 
    produto_in: ProdutoCreate
):
    """
    [ADMIN] Cria um novo produto no catálogo.
    """
    produto = Produto.model_validate(produto_in)
    session.add(produto)
    session.commit()
    session.refresh(produto)
    return produto

@admin_router.get(
    "/",
    response_model=List[ProdutoAdminRead],
    dependencies=[Depends(get_current_admin_user)]
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
    dependencies=[Depends(get_current_admin_user)]
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
        
    update_data = produto_in.model_dump(exclude_unset=True)
    produto.sqlmodel_update(update_data)
    
    session.add(produto)
    session.commit()
    session.refresh(produto)
    return produto

# ==================== NOVO ENDPOINT ====================
@admin_router.delete(
    "/{produto_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(get_current_admin_user)]
)
def delete_produto(
    *,
    session: Session = Depends(get_session),
    produto_id: uuid.UUID
):
    """
    [ADMIN] Exclui um produto do catálogo.
    
    ATENÇÃO: Isso NÃO exclui os pedidos ou estoque relacionados.
    Recomenda-se apenas desativar o produto (is_ativo=False) em vez de excluir.
    """
    produto = session.get(Produto, produto_id)
    if not produto:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    
    # Verifica se há estoque vinculado (segurança extra)
    from app.models.produto_models import EstoqueConta
    contas_vinculadas = session.exec(
        select(EstoqueConta).where(EstoqueConta.produto_id == produto_id).limit(1)
    ).first()
    
    if contas_vinculadas:
        raise HTTPException(
            status_code=400, 
            detail="Não é possível excluir um produto com contas em estoque. Desative-o em vez disso."
        )
    
    session.delete(produto)
    session.commit()
    return None