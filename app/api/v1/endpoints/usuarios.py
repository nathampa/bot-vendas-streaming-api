from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from typing import Optional
from app.db.database import get_session
from app.models.usuario_models import Usuario
from app.schemas.usuario_schemas import (UsuarioRegisterRequest, UsuarioRead, UsuarioPedidoRead,UsuarioAdminRead, RecargaAdminRead)
from app.api.v1.deps import get_bot_api_key
from typing import List
from app.models.pedido_models import Pedido
from app.models.produto_models import Produto
from app.api.v1.deps import get_current_admin_user
from sqlalchemy import func

# Roteador para o Bot (protegido pela API Key)
router = APIRouter(dependencies=[Depends(get_bot_api_key)])

# --- Função Auxiliar (Colada do recargas.py) ---
def get_or_create_usuario(session: Session, telegram_id: int, nome_completo: str, referrer_id_telegram: Optional[int] = None) -> Usuario:
    """
    Tenta encontrar um usuário pelo telegram_id.
    Se não encontrar, cria um novo usuário, processando o referrer_id.
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
        return usuario # Retorna o usuário existente

    # 2. Se não encontrou (Novo Usuário), processa o indicador (referrer)
    print(f"Usuário com telegram_id {telegram_id} não encontrado. Criando novo usuário.")
    
    db_referrer: Optional[Usuario] = None
    if referrer_id_telegram:
        # Busca o usuário que indicou pelo ID do Telegram
        stmt_referrer = select(Usuario).where(Usuario.telegram_id == referrer_id_telegram)
        db_referrer = session.exec(stmt_referrer).first()
        if db_referrer:
            print(f"Usuário {telegram_id} foi indicado por {db_referrer.telegram_id} (UUID: {db_referrer.id})")
        else:
            print(f"Referrer com ID {referrer_id_telegram} não encontrado no banco.")

    # Cria o novo usuário
    novo_usuario = Usuario(
        telegram_id=telegram_id,
        nome_completo=nome_completo,
        # Seta o ID do BD (UUID) do indicador, se ele foi encontrado
        referrer_id=db_referrer.id if db_referrer else None
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
        nome_completo=user_in.nome_completo,
        referrer_id_telegram=user_in.referrer_id
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