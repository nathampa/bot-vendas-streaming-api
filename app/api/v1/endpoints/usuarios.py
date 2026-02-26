import datetime
import uuid
from decimal import Decimal, ROUND_HALF_UP
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from typing import Optional
from app.db.database import get_session
from app.models.usuario_models import Usuario, AjusteSaldoUsuario
from app.schemas.usuario_schemas import (
    UsuarioRegisterRequest,
    UsuarioRead,
    UsuarioPedidoRead,
    UsuarioExpiracaoPendenteRead,
    UsuarioExpiracaoMarcarNotificadaRequest,
    UsuarioAdminRead,
    RecargaAdminRead,
    UsuarioSaldoAjusteRequest,
    UsuarioSaldoAjusteResponse,
    UsuarioSaldoHistoricoRead,
)
from app.api.v1.deps import get_bot_api_key
from typing import List
from app.models.pedido_models import Pedido
from app.models.produto_models import Produto
from app.models.base import StatusEntregaPedido
from app.api.v1.deps import get_current_admin_user
from sqlalchemy import func, desc
from app.services.pedido_expiracao_service import resolver_data_expiracao_pedido

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
TWO_DECIMAL_PLACES = Decimal("0.01")

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


@admin_router.post("/{usuario_id}/ajuste-saldo", response_model=UsuarioSaldoAjusteResponse)
def ajustar_saldo_usuario(
    *,
    usuario_id: uuid.UUID,
    ajuste: UsuarioSaldoAjusteRequest,
    session: Session = Depends(get_session),
    current_admin: Usuario = Depends(get_current_admin_user),
):
    """
    [ADMIN] Ajusta manualmente o saldo da carteira do usuário.
    Operações:
    - ADICIONAR: soma o valor informado ao saldo atual
    - REMOVER: subtrai o valor informado do saldo atual
    - DEFINIR: define o saldo exatamente para o valor informado
    """
    usuario = session.exec(
        select(Usuario).where(Usuario.id == usuario_id, Usuario.is_admin == False)
    ).first()

    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    valor_ajuste = ajuste.valor.quantize(TWO_DECIMAL_PLACES, rounding=ROUND_HALF_UP)
    saldo_anterior = Decimal(usuario.saldo_carteira).quantize(TWO_DECIMAL_PLACES, rounding=ROUND_HALF_UP)

    if ajuste.operacao in ("ADICIONAR", "REMOVER") and valor_ajuste <= 0:
        raise HTTPException(
            status_code=400,
            detail="O valor do ajuste precisa ser maior que zero para adicionar ou remover saldo.",
        )

    if ajuste.operacao == "DEFINIR" and valor_ajuste < 0:
        raise HTTPException(
            status_code=400,
            detail="Não é permitido definir saldo negativo.",
        )

    if ajuste.operacao == "ADICIONAR":
        saldo_atual = saldo_anterior + valor_ajuste
    elif ajuste.operacao == "REMOVER":
        if valor_ajuste > saldo_anterior:
            raise HTTPException(
                status_code=400,
                detail=f"Saldo insuficiente para remoção. Saldo atual: R$ {saldo_anterior:.2f}",
            )
        saldo_atual = saldo_anterior - valor_ajuste
    else:
        saldo_atual = valor_ajuste

    saldo_atual = saldo_atual.quantize(TWO_DECIMAL_PLACES, rounding=ROUND_HALF_UP)
    usuario.saldo_carteira = saldo_atual
    motivo = ajuste.motivo.strip() if ajuste.motivo and ajuste.motivo.strip() else None

    historico = AjusteSaldoUsuario(
        operacao=ajuste.operacao,
        valor=valor_ajuste,
        saldo_anterior=saldo_anterior,
        saldo_atual=saldo_atual,
        motivo=motivo,
        usuario_id=usuario.id,
        admin_id=current_admin.id,
    )
    session.add(usuario)
    session.add(historico)
    session.commit()

    return UsuarioSaldoAjusteResponse(
        usuario_id=usuario.id,
        operacao=ajuste.operacao,
        valor=valor_ajuste,
        saldo_anterior=saldo_anterior,
        saldo_atual=saldo_atual,
        motivo=motivo,
        ajustado_em=datetime.datetime.utcnow(),
    )


@admin_router.get("/{usuario_id}/historico-saldo", response_model=List[UsuarioSaldoHistoricoRead])
def get_historico_ajustes_saldo_usuario(
    *,
    usuario_id: uuid.UUID,
    limite: int = 20,
    session: Session = Depends(get_session),
):
    """
    [ADMIN] Retorna histórico de ajustes manuais de saldo de um usuário.
    """
    if limite < 1:
        raise HTTPException(status_code=400, detail="O limite precisa ser maior ou igual a 1.")
    if limite > 200:
        raise HTTPException(status_code=400, detail="O limite máximo permitido é 200.")

    usuario = session.exec(
        select(Usuario).where(Usuario.id == usuario_id, Usuario.is_admin == False)
    ).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    stmt = (
        select(
            AjusteSaldoUsuario.id,
            AjusteSaldoUsuario.operacao,
            AjusteSaldoUsuario.valor,
            AjusteSaldoUsuario.saldo_anterior,
            AjusteSaldoUsuario.saldo_atual,
            AjusteSaldoUsuario.motivo,
            AjusteSaldoUsuario.criado_em,
            AjusteSaldoUsuario.admin_id,
            Usuario.nome_completo.label("admin_nome_completo"),
            Usuario.telegram_id.label("admin_telegram_id"),
        )
        .join(Usuario, Usuario.id == AjusteSaldoUsuario.admin_id)
        .where(AjusteSaldoUsuario.usuario_id == usuario_id)
        .order_by(desc(AjusteSaldoUsuario.criado_em))
        .limit(limite)
    )

    resultados = session.exec(stmt).all()
    return [
        UsuarioSaldoHistoricoRead(
            id=item.id,
            operacao=item.operacao,
            valor=item.valor,
            saldo_anterior=item.saldo_anterior,
            saldo_atual=item.saldo_atual,
            motivo=item.motivo,
            criado_em=item.criado_em,
            admin_id=item.admin_id,
            admin_nome_completo=item.admin_nome_completo,
            admin_telegram_id=item.admin_telegram_id,
        )
        for item in resultados
    ]

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
            Pedido.criado_em,
            Pedido.email_cliente,
            Pedido.estoque_conta_id,
            Pedido.conta_mae_id,
        )
        .join(Produto, Produto.id == Pedido.produto_id)
        .where(Pedido.usuario_id == usuario.id)
        .order_by(Pedido.criado_em.desc())
        .limit(5)
    )

    resultados = session.exec(stmt).all()

    # 3. Formata a resposta no schema
    today = datetime.date.today()
    lista_pedidos: List[UsuarioPedidoRead] = []

    for (
        pid,
        pnome,
        vpago,
        data,
        email_cliente,
        estoque_conta_id,
        conta_mae_id,
    ) in resultados:
        data_expiracao, origem_expiracao = resolver_data_expiracao_pedido(
            session=session,
            pedido_id=pid,
            email_cliente=email_cliente,
            estoque_conta_id=estoque_conta_id,
            conta_mae_id=conta_mae_id,
        )

        dias_restantes = None
        conta_expirada = False
        if data_expiracao:
            dias_restantes = (data_expiracao - today).days
            conta_expirada = dias_restantes < 0

        lista_pedidos.append(
            UsuarioPedidoRead(
                pedido_id=pid,
                produto_nome=pnome,
                valor_pago=vpago,
                data_compra=data,
                data_expiracao=data_expiracao,
                dias_restantes=dias_restantes,
                conta_expirada=conta_expirada,
                origem_expiracao=origem_expiracao,
            )
        )

    return lista_pedidos


@router.get("/expiracoes-pendentes", response_model=List[UsuarioExpiracaoPendenteRead])
def get_expiracoes_pendentes(
    *,
    session: Session = Depends(get_session),
    limite: int = 200,
):
    """
    [BOT] Lista pedidos cuja conta expira hoje e ainda não tiveram notificação enviada.
    """
    if limite < 1:
        raise HTTPException(status_code=400, detail="O limite precisa ser maior ou igual a 1.")
    if limite > 1000:
        raise HTTPException(status_code=400, detail="O limite máximo permitido é 1000.")

    hoje = datetime.date.today()

    stmt = (
        select(
            Pedido.id,
            Usuario.telegram_id,
            Produto.nome,
            Pedido.email_cliente,
            Pedido.estoque_conta_id,
            Pedido.conta_mae_id,
            Pedido.ultima_data_expiracao_notificada,
        )
        .join(Usuario, Usuario.id == Pedido.usuario_id)
        .join(Produto, Produto.id == Pedido.produto_id)
        .where(Pedido.status_entrega == StatusEntregaPedido.ENTREGUE)
        .order_by(Pedido.criado_em.desc())
        .limit(2000)
    )

    resultados = session.exec(stmt).all()

    pendentes: List[UsuarioExpiracaoPendenteRead] = []
    for (
        pedido_id,
        telegram_id,
        produto_nome,
        email_cliente,
        estoque_conta_id,
        conta_mae_id,
        ultima_data_notificada,
    ) in resultados:
        data_expiracao, origem_expiracao = resolver_data_expiracao_pedido(
            session=session,
            pedido_id=pedido_id,
            email_cliente=email_cliente,
            estoque_conta_id=estoque_conta_id,
            conta_mae_id=conta_mae_id,
        )

        if not data_expiracao or not origem_expiracao:
            continue
        if data_expiracao != hoje:
            continue
        if ultima_data_notificada == data_expiracao:
            continue

        pendentes.append(
            UsuarioExpiracaoPendenteRead(
                pedido_id=pedido_id,
                telegram_id=telegram_id,
                produto_nome=produto_nome,
                data_expiracao=data_expiracao,
                origem_expiracao=origem_expiracao,
            )
        )

        if len(pendentes) >= limite:
            break

    return pendentes


@router.post("/expiracoes-pendentes/marcar-notificada")
def marcar_expiracao_notificada(
    *,
    session: Session = Depends(get_session),
    payload: UsuarioExpiracaoMarcarNotificadaRequest,
):
    """
    [BOT] Marca que a notificação de expiração de um pedido foi enviada para uma data específica.
    """
    pedido = session.get(Pedido, payload.pedido_id)
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido não encontrado.")

    data_expiracao_atual, _ = resolver_data_expiracao_pedido(
        session=session,
        pedido_id=pedido.id,
        email_cliente=pedido.email_cliente,
        estoque_conta_id=pedido.estoque_conta_id,
        conta_mae_id=pedido.conta_mae_id,
    )

    if data_expiracao_atual != payload.data_expiracao:
        raise HTTPException(
            status_code=409,
            detail="Data de expiração atual do pedido não corresponde à data informada.",
        )

    pedido.ultima_data_expiracao_notificada = payload.data_expiracao
    session.add(pedido)
    session.commit()

    return {"status": "ok", "pedido_id": pedido.id, "data_expiracao": payload.data_expiracao}

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
