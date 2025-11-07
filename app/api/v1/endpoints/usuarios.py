from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.db.database import get_session
from app.models.usuario_models import Usuario
from app.schemas.usuario_schemas import UsuarioRegisterRequest, UsuarioRead
from app.api.v1.deps import get_bot_api_key
from typing import List
from app.models.pedido_models import Pedido
from app.models.produto_models import Produto
from app.schemas.usuario_schemas import UsuarioPedidoRead
from app.api.v1.deps import get_current_admin_user
from app.schemas.usuario_schemas import UsuarioAdminRead
from sqlalchemy import func # Para usar o COUNT

# Roteador para o Bot (protegido pela API Key)
router = APIRouter(dependencies=[Depends(get_bot_api_key)])

# --- Função Auxiliar (Colada do recargas.py) ---
def get_or_create_usuario(session: Session, telegram_id: int, nome_completo: str) -> Usuario:
    """
    Tenta encontrar um usuário pelo telegram_id.
    Se não encontrar, cria um novo usuário.
    """

    # 1. Tenta encontrar o usuário
    usuario = session.exec(
        select(Usuario).where(Usuario.telegram_id == telegram_id)
    ).first()

    if usuario:
        # Se encontrou, atualiza o nome (caso o user tenha mudado no Telegram)
        if usuario.nome_completo != nome_completo:
            usuario.nome_completo = nome_completo
            session.add(usuario)
            session.commit()
            session.refresh(usuario)
        return usuario

    # 2. Se não encontrou, cria um novo
    print(f"Usuário com telegram_id {telegram_id} não encontrado. Criando novo usuário.")
    novo_usuario = Usuario(
        telegram_id=telegram_id,
        nome_completo=nome_completo
    )
    session.add(novo_usuario)
    session.commit()
    session.refresh(novo_usuario)
    return novo_usuario
# --- Fim da Função Auxiliar ---

admin_router = APIRouter(dependencies=[Depends(get_current_admin_user)])

@admin_router.get("/", response_model=List[UsuarioAdminRead])
def get_admin_usuarios(
    *,
    session: Session = Depends(get_session)
):
    """
    [ADMIN] Lista todos os usuários clientes com contagem de pedidos.
    """
    stmt = (
        select(
            Usuario.id,
            Usuario.telegram_id,
            Usuario.nome_completo,
            Usuario.saldo_carteira,
            Usuario.criado_em,
            func.count(Pedido.id).label("total_pedidos")
        )
        .join(Pedido, Pedido.usuario_id == Usuario.id, isouter=True) # isouter=True é um LEFT JOIN
        .where(Usuario.is_admin == False) # Ignora o admin
        .group_by(Usuario.id)
        .order_by(Usuario.criado_em.desc())
    )
    
    resultados = session.exec(stmt).all()
    
    # Mapeia os resultados para o schema
    lista_usuarios = [
        UsuarioAdminRead(
            id=u.id,
            telegram_id=u.telegram_id,
            nome_completo=u.nome_completo,
            saldo_carteira=u.saldo_carteira,
            criado_em=u.criado_em,
            total_pedidos=u.total_pedidos
        ) for u in resultados
    ]
    
    return lista_usuarios

# --- Endpoint Novo (/start vai chamar este) ---
@router.post("/register", response_model=UsuarioRead)
def register_user(
    *,
    session: Session = Depends(get_session),
    user_in: UsuarioRegisterRequest
):
    """
    [BOT] Encontra ou cria um usuário no banco de dados.
    Este é o "ponto de entrada" principal do bot (ex: /start).
    """

    usuario = get_or_create_usuario(
        session=session,
        telegram_id=user_in.telegram_id,
        nome_completo=user_in.nome_completo
    )
    return usuario

@router.get("/meus-pedidos", response_model=List[UsuarioPedidoRead])
def get_meus_pedidos(
    *,
    session: Session = Depends(get_session),
    telegram_id: int # Recebemos o ID como parâmetro de query (?telegram_id=...)
):
    """
    [BOT] Retorna os 5 últimos pedidos de um usuário.
    """

    # 1. Encontra o usuário
    usuario = session.exec(
        select(Usuario).where(Usuario.telegram_id == telegram_id)
    ).first()

    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    # 2. Query com JOIN para buscar Pedidos e nome do Produto
    stmt = (
        select(
            Pedido.id,
            Produto.nome,
            Pedido.valor_pago,
            Pedido.criado_em
        )
        .join(Produto, Produto.id == Pedido.produto_id)
        .where(Pedido.usuario_id == usuario.id)
        .order_by(Pedido.criado_em.desc())
        .limit(5)
    )

    resultados = session.exec(stmt).all()

    # 3. Formata a resposta no schema
    lista_pedidos = [
        UsuarioPedidoRead(
            pedido_id=pid,
            produto_nome=pnome,
            valor_pago=vpago,
            data_compra=data
        ) for pid, pnome, vpago, data in resultados
    ]

    return lista_pedidos

# Endpoint buscar id de todo os usuarios
@router.get(
    "/all-ids",
    response_model=List[int],
    include_in_schema=False # Esconde esta rota do /docs público
)
def get_all_user_ids(
    *,
    session: Session = Depends(get_session)
):
    """
    [BOT-ADMIN] Retorna uma lista de todos os Telegram IDs
    dos usuários que NÃO são administradores.
    Usado para o broadcast de mensagens.
    """
    
    # Seleciona apenas os telegram_id de usuários normais
    stmt = (
        select(Usuario.telegram_id)
        .where(Usuario.is_admin == False)
    )
    
    user_ids = session.exec(stmt).all()
    
    return user_ids