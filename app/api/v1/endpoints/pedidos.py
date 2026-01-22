import uuid
import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from typing import List

from app.db.database import get_session
from app.models.usuario_models import Usuario
from app.models.pedido_models import Pedido
from app.models.produto_models import Produto, EstoqueConta
from app.models.conta_mae_models import ContaMae
from app.models.base import StatusEntregaPedido
from app.schemas.pedido_schemas import (
    PedidoAdminList,
    PedidoAdminDetails,
    PedidoAdminConta,
    PedidoAdminContaMae,
    PedidoAdminEntregaRequest
)
from app.api.v1.deps import get_current_admin_user
from app.services import security
from app.services.notification_service import send_telegram_message, escape_markdown_v2

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
            Pedido.status_entrega,
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
    # (Pois já atualizamos o schema PedidoAdminList no Passo 2)
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
            Pedido, # Selecionamos o objeto Pedido inteiro
            Produto.nome.label("produto_nome"),
            Usuario.nome_completo.label("usuario_nome_completo"),
            Usuario.telegram_id.label("usuario_telegram_id"),
            EstoqueConta.login,
            EstoqueConta.senha,  # Senha CRIPTOGRAFADA
            ContaMae.id,
            ContaMae.login,
            ContaMae.data_expiracao,
        )
        .join(Produto, Pedido.produto_id == Produto.id)
        .join(Usuario, Pedido.usuario_id == Usuario.id)
        .join(EstoqueConta, Pedido.estoque_conta_id == EstoqueConta.id, isouter=True)
        .join(ContaMae, Pedido.conta_mae_id == ContaMae.id, isouter=True)
        .where(Pedido.id == pedido_id)
    )
    
    resultado = session.exec(stmt).first()
    
    if not resultado:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")

    # 2. Desempacota os resultados
    (
        pedido, produto_nome, usuario_nome, 
        usuario_tid, conta_login, conta_senha_cripto,
        conta_mae_id, conta_mae_login, conta_mae_expiracao,
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

    conta_mae_info = None
    if conta_mae_id and conta_mae_login:
        dias_restantes = None
        if conta_mae_expiracao:
            delta = conta_mae_expiracao - datetime.date.today()
            dias_restantes = delta.days

        conta_mae_info = PedidoAdminContaMae(
            id=conta_mae_id,
            login=conta_mae_login,
            data_expiracao=conta_mae_expiracao,
            dias_restantes=dias_restantes,
        )
    
    # 4. Monta o schema de resposta
    detalhes_pedido = PedidoAdminDetails(
        id=pedido.id,
        criado_em=pedido.criado_em,
        valor_pago=pedido.valor_pago,
        email_cliente=pedido.email_cliente,
        status_entrega=pedido.status_entrega,
        produto_nome=produto_nome,
        usuario_nome_completo=usuario_nome,
        usuario_telegram_id=usuario_tid,
        conta=conta_info, # Aninha os detalhes da conta (pode ser None)
        conta_mae=conta_mae_info,
    )
    
    return detalhes_pedido

# Entrega pedido manual
@router.post("/{pedido_id}/entregar", response_model=PedidoAdminDetails)
def entregar_pedido_manual(
    *,
    session: Session = Depends(get_session),
    pedido_id: uuid.UUID,
    entrega_in: PedidoAdminEntregaRequest # Recebe { "login": "...", "senha": "..." }
):
    """
    [ADMIN] Realiza a entrega manual de um pedido pendente.
    Cria uma nova conta no estoque, vincula ao pedido e notifica o cliente.
    """
    
    # 1. Busca o Pedido e o Usuário
    pedido = session.get(Pedido, pedido_id)
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido não encontrado.")
        
    usuario = session.get(Usuario, pedido.usuario_id)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário do pedido não encontrado.")
        
    produto = session.get(Produto, pedido.produto_id)
    if not produto:
        raise HTTPException(status_code=404, detail="Produto do pedido não encontrado.")

    # 2. Validação
    if pedido.status_entrega != StatusEntregaPedido.PENDENTE:
        raise HTTPException(status_code=400, detail="Este pedido não está pendente de entrega.")
    
    if pedido.estoque_conta_id:
        raise HTTPException(status_code=400, detail="Este pedido já possui uma conta vinculada.")

    try:
        # 3. Criptografa a senha
        senha_criptografada = security.encrypt_data(entrega_in.senha)

        # 4. Cria a nova conta no Estoque
        # Esta conta é "dedicada" a este usuário.
        nova_conta = EstoqueConta(
            produto_id=pedido.produto_id,
            login=entrega_in.login,
            senha=senha_criptografada,
            max_slots=1,
            slots_ocupados=1,
            is_ativo=True,
            requer_atencao=False 
        )
        session.add(nova_conta)
        session.flush() # Força o DB a gerar o ID da nova_conta

        # 5. Atualiza o Pedido
        pedido.estoque_conta_id = nova_conta.id
        pedido.status_entrega = StatusEntregaPedido.ENTREGUE
        session.add(pedido)

        # 6. Salva as mudanças no banco
        session.commit()
        
        # 7. Notifica o Cliente
        try:
            # 7a. Escapamos APENAS as variáveis que vêm do banco/input
            produto_nome_f = escape_markdown_v2(produto.nome)
            login_f = escape_markdown_v2(entrega_in.login)
            senha_f = escape_markdown_v2(entrega_in.senha)
            instrucoes_f = escape_markdown_v2(produto.instrucoes_pos_compra or "Siga as instruções do produto.")
            
            # 7b. Montamos a mensagem com nosso markdown VÁLIDO
            #     Note que os '\' SÃO necessários para os caracteres
            #     que NÓS estamos adicionando (como '!', '.', '-')
            message = (
                f"✅ *Entrega Concluída\\!*\n\n"
                f"O seu pedido do produto *{produto_nome_f}* está pronto\\!\n\n"
                f"Login: `{login_f}`\n"
                f"Senha: `{senha_f}`\n\n"
                f"**Instruções Importantes:**\n{instrucoes_f}\n\n"
                f"⚠️ *Por favor, não altere a senha\\! Apenas 1 utilizador por conta\\. RISCO DE PERDER O SEU ACESSO\\!*"
            )
            
            # 7c. Enviamos a mensagem
            send_telegram_message(telegram_id=usuario.telegram_id, message_text=message)
            
        except Exception as e_notify:
            print(f"ERRO CRÍTICO (Não-fatal): Falha ao notificar usuário {usuario.telegram_id} sobre entrega: {e_notify}")
            # Não falha a transação, mas o admin precisa saber disso.
            # No futuro, podemos adicionar um log de "falha na notificação" no painel.

        # 8. Retorna os detalhes atualizados do pedido
        session.refresh(pedido)
        
        # Reutiliza a função de detalhes para retornar o pedido atualizado
        # (Isso é um truque para não reescrever a lógica de 'get_pedido_detalhes')
        return get_pedido_detalhes(session=session, pedido_id=pedido.id)

    except Exception as e:
        session.rollback()
        print(f"ERRO CRÍTICO ao entregar pedido manual: {e}")
        raise HTTPException(status_code=500, detail=f"Erro interno: {e}")
