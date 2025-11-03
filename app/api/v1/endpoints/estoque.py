import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from typing import List

from app.db.database import get_session
from app.models.usuario_models import Usuario
from app.models.produto_models import EstoqueConta, Produto
from app.schemas.estoque_schemas import (
    EstoqueCreate,
    EstoqueUpdate,
    EstoqueAdminRead,
    EstoqueAdminReadDetails,
)
from app.api.v1.deps import get_current_admin_user # Nosso "Cadeado"
from app.services import security # Nosso service de Criptografia

# Roteador de Admin para o Estoque
# Todos os endpoints aqui serão protegidos
router = APIRouter(dependencies=[Depends(get_current_admin_user)])


@router.post(
    "/",
    response_model=EstoqueAdminRead,
    status_code=status.HTTP_201_CREATED
)
def create_conta_estoque(
    *, 
    session: Session = Depends(get_session), 
    estoque_in: EstoqueCreate
):
    """
    [ADMIN] Adiciona uma nova conta (login/senha) ao estoque.
    A senha é criptografada antes de ser salva.
    """
    
    # 1. Validação: O Produto existe?
    produto = session.get(Produto, estoque_in.produto_id)
    if not produto:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
        
    # 2. Criptografia da Senha
    # Usamos o service que criamos para criptografar
    senha_criptografada = security.encrypt_data(estoque_in.senha)
    
    # 3. Cria o objeto do banco (Model)
    # Note que usamos 'estoque_in.model_dump()' mas sobrescrevemos a 'senha'
    estoque_data = estoque_in.model_dump(exclude={"senha"})
    estoque = EstoqueConta(
        **estoque_data,
        senha=senha_criptografada # Salva a senha criptografada
    )
    
    session.add(estoque)
    session.commit()
    session.refresh(estoque)
    return estoque


@router.get("/", response_model=List[EstoqueAdminRead])
def get_lista_estoque(session: Session = Depends(get_session)):
    """
    [ADMIN] Lista todas as contas em estoque.
    (Não retorna as senhas).
    """
    contas = session.exec(select(EstoqueConta)).all()
    return contas


@router.get(
    "/{estoque_id}", 
    response_model=EstoqueAdminReadDetails
)
def get_detalhe_conta_estoque(
    *,
    session: Session = Depends(get_session),
    estoque_id: uuid.UUID
):
    """
    [ADMIN] Vê os detalhes de UMA conta, incluindo a senha descriptografada.
    """
    conta = session.get(EstoqueConta, estoque_id)
    if not conta:
        raise HTTPException(status_code=404, detail="Conta de estoque não encontrada")
        
    # 1. Descriptografa a senha para exibição
    senha_descriptografada = security.decrypt_data(conta.senha)
    
    # 2. Cria o objeto de resposta
    # Usamos o model EstoqueAdminReadDetails
    response_data = EstoqueAdminReadDetails.model_validate(conta)
    response_data.senha = senha_descriptografada
    
    return response_data


@router.put(
    "/{estoque_id}", 
    response_model=EstoqueAdminRead
)
def update_conta_estoque(
    *,
    session: Session = Depends(get_session),
    estoque_id: uuid.UUID,
    estoque_in: EstoqueUpdate
):
    """
    [ADMIN] Atualiza uma conta de estoque.
    Se uma nova senha for enviada, ela será criptografada.
    """
    conta = session.get(EstoqueConta, estoque_id)
    if not conta:
        raise HTTPException(status_code=404, detail="Conta de estoque não encontrada")
        
    # Pega os dados do schema (apenas os que foram enviados)
    update_data = estoque_in.model_dump(exclude_unset=True)
    
    # 3. Lógica de Criptografia (se a senha foi alterada)
    if "senha" in update_data:
        nova_senha = update_data["senha"]
        update_data["senha"] = security.encrypt_data(nova_senha)
        
    # Atualiza o objeto do model
    conta.sqlmodel_update(update_data)
    
    session.add(conta)
    session.commit()
    session.refresh(conta)
    return conta

@router.delete("/{estoque_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conta_estoque(
    *,
    session: Session = Depends(get_session),
    estoque_id: uuid.UUID
):
    """
    [ADMIN] Deleta permanentemente uma conta do estoque.
    
    Esta ação não pode ser desfeita.
    """
    
    # 1. Encontra a conta pelo seu ID (Chave Primária)
    # session.get() é a forma mais eficiente de buscar por PK
    conta = session.get(EstoqueConta, estoque_id)
    
    # 2. Verifica se a conta foi encontrada
    if not conta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conta de estoque não encontrada"
        )
        
    # 3. Se encontrada, deleta a conta
    try:
        session.delete(conta)
        session.commit()
    except Exception as e:
        # Caso ocorra um erro de banco (ex: restrição de chave estrangeira)
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro de banco de dados ao deletar a conta: {e}"
        )

    # 4. Retorna 204 No Content (sucesso, sem corpo de resposta)
    # Isso é feito automaticamente pelo decorator
    return