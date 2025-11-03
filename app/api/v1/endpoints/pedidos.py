import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from typing import List

from app.db.database import get_session
from app.models.usuario_models import Usuario
from app.models.pedido_models import Pedido
from app.models.produto_models import Produto, EstoqueConta
from app.schemas.pedido_schemas import (
    PedidoAdminList,
    PedidoAdminDetails,
    PedidoAdminConta
)
from app.api.v1.deps import get_current_admin_user # O "Cadeado" do Admin
from app.services import security # Para descriptografar

# Roteador de Admin para Pedidos
router = APIRouter(dependencies=[Depends(get_current_admin_user)])

@router.get("/", response_model=List[PedidoAdminList])
def get_admin_pedidos(
    *,
    session: Session = Depends(get_session)
):
    """
    [ADMIN] Lista todos os pedidos realizados, ordenados do mais recente.
    """
    stmt = (
        select(
            Pedido.id,
            Pedido.criado_em,
            Pedido.valor_pago,
            Pedido.email_cliente,
            Produto.nome.label("produto_nome"),
            Usuario.nome_completo.label("usuario_nome_completo"),
            Usuario.telegram_id.label("usuario_telegram_id")
        )
        .join(Produto, Pedido.produto_id == Produto.id)
        .join(Usuario, Pedido.usuario_id == Usuario.id)
        .order_by(Pedido.criado_em.desc())
    )
    
    resultados = session.exec(stmt).all()
    # Pydantic/FastAPI fará o mapeamento automático para PedidoAdminList
    return resultados


@router.get("/{pedido_id}/detalhes", response_model=PedidoAdminDetails)
def get_pedido_detalhes(
    *,
    session: Session = Depends(get_session),
    pedido_id: uuid.UUID
):
    """
    [ADMIN] Busca os detalhes de um pedido, incluindo a conta 
    (login/senha) descriptografada.
    """
    
    # 1. Query principal: Pega tudo com JOINs
    stmt = (
        select(
            Pedido,
            Produto.nome.label("produto_nome"),
            Usuario.nome_completo.label("usuario_nome_completo"),
            Usuario.telegram_id.label("usuario_telegram_id"),
            EstoqueConta.login,
            EstoqueConta.senha  # Senha CRIPTOGRAFADA
        )
        .join(Produto, Pedido.produto_id == Produto.id)
        .join(Usuario, Pedido.usuario_id == Usuario.id)
        .join(EstoqueConta, Pedido.estoque_conta_id == EstoqueConta.id, isouter=True)
        .where(Pedido.id == pedido_id)
    )
    
    resultado = session.exec(stmt).first()
    
    if not resultado:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")

    # 2. Desempacota os resultados
    (
        pedido, produto_nome, usuario_nome, 
        usuario_tid, conta_login, conta_senha_cripto
    ) = resultado
    
    
    # 3. Monta a conta (se ela existir)
    conta_info = None
    if conta_login and conta_senha_cripto:
        senha_descriptografada = security.decrypt_data(conta_senha_cripto)
        if not senha_descriptografada:
            senha_descriptografada = "[ERRO AO DESCRIPTOGRAFAR]"
        
        conta_info = PedidoAdminConta(
            login=conta_login,
            senha=senha_descriptografada
        )
    
    # 4. Monta o schema de resposta
    detalhes_pedido = PedidoAdminDetails(
        id=pedido.id,
        criado_em=pedido.criado_em,
        valor_pago=pedido.valor_pago,
        email_cliente=pedido.email_cliente, # <-- ADICIONADO
        produto_nome=produto_nome,
        usuario_nome_completo=usuario_nome,
        usuario_telegram_id=usuario_tid,
        conta=conta_info # Aninha os detalhes da conta (pode ser None)
    )
    
    return detalhes_pedido