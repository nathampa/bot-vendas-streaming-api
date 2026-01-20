import uuid
import datetime
from typing import Optional
from sqlmodel import Session, select

from app.worker.celery_app import celery_app
from app.db.database import engine # Importamos o 'engine' do banco
from app.services import security # Para descriptografar a nova senha
from app.services.notification_service import send_telegram_message, escape_markdown_v2
from app.models.base import TipoStatusTicket, TipoResolucaoTicket
from app.models.usuario_models import Usuario
from app.models.pedido_models import Pedido
from app.models.produto_models import Produto, EstoqueConta
from app.models.suporte_models import TicketSuporte

# --- Funções Auxiliares (Tarefas Reais) ---

def handle_reembolso_carteira(session: Session, ticket: TicketSuporte):
    """
    Lógica para reembolsar o valor da compra para a carteira do usuário.
    """
    print(f"A processar REEMBOLSO para Ticket {ticket.id}")
    pedido = session.get(Pedido, ticket.pedido_id)
    usuario = session.get(Usuario, ticket.usuario_id)
    
    if not pedido or not usuario:
        raise Exception(f"Pedido ({ticket.pedido_id}) ou Usuário ({ticket.usuario_id}) não encontrado.")
        
    # Adiciona o saldo de volta à carteira
    usuario.saldo_carteira += pedido.valor_pago
    
    # Atualiza o ticket
    ticket.status = TipoStatusTicket.RESOLVIDO
    ticket.resolucao = TipoResolucaoTicket.REEMBOLSO_CARTEIRA
    ticket.atualizado_em = datetime.datetime.utcnow()
    
    session.add(usuario)
    session.add(ticket)
    
    # TODO: Enviar notificação ao usuário sobre o reembolso
    print(f"Sucesso: Reembolsado {pedido.valor_pago} para usuário {usuario.id}")

def handle_trocar_conta(session: Session, ticket: TicketSuporte):
    """
    Lógica de "Troca Rápida" (Hot-Swap). Encontra uma nova conta
    e reatribui o pedido a ela.
    """
    print(f"A processar TROCA RÁPIDA (Hot-Swap) para Ticket {ticket.id}")
    pedido = session.get(Pedido, ticket.pedido_id)
    produto = session.get(Produto, pedido.produto_id)

    if not pedido or not produto:
        raise Exception(f"Pedido ({ticket.pedido_id}) ou Produto ({pedido.produto_id}) não encontrado.")

    # 1. Encontrar uma nova conta (A query 'FOR UPDATE' de 'compras.py')
    stmt = (
        select(EstoqueConta)
        .where(EstoqueConta.produto_id == produto.id)
        .where(EstoqueConta.id != ticket.estoque_conta_id) # NÃO pode ser a conta quebrada
        .where(EstoqueConta.is_ativo == True)
        .where(EstoqueConta.requer_atencao == False)
        .where(EstoqueConta.slots_ocupados < EstoqueConta.max_slots)
        .order_by(
            EstoqueConta.data_expiracao.asc().nulls_last(),
            EstoqueConta.slots_ocupados,
        )
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    nova_conta = session.exec(stmt).first()
    
    # 2. Caso de Falha: Sem estoque para troca
    if not nova_conta:
        print(f"FALHA na Troca Rápida do Ticket {ticket.id}: Sem estoque de reposição.")
        ticket.status = TipoStatusTicket.ABERTO # Devolve o ticket para a fila
        ticket.atualizado_em = datetime.datetime.utcnow()
        session.add(ticket)
        # TODO: Notificar admin que a troca falhou
        return # Termina a tarefa

    # 3. Caso de Sucesso: Encontrámos uma nova conta
    # a. Alocar o slot na nova conta
    nova_conta.slots_ocupados += 1
    session.add(nova_conta)
    
    # b. Reatribuir o pedido original à nova conta
    pedido.estoque_conta_id = nova_conta.id
    session.add(pedido)
    
    # c. Fechar o ticket
    ticket.status = TipoStatusTicket.RESOLVIDO
    ticket.resolucao = TipoResolucaoTicket.CONTA_TROCADA
    ticket.atualizado_em = datetime.datetime.utcnow()
    session.add(ticket)
    
    # d. Descriptografar a nova senha para notificar o usuário
    senha = security.decrypt_data(nova_conta.senha)
    
    # TODO: Enviar notificação ao usuário com as novas credenciais
    print(f"Sucesso: Ticket {ticket.id} resolvido com Hot-Swap. Nova conta: {nova_conta.login} / {senha}")

def handle_fechar_manualmente(session: Session, ticket: TicketSuporte, mensagem: Optional[str] = None):
    """
    Lógica para simplesmente fechar o ticket.
    (Assume que o admin resolveu por fora ou era um ticket falso).
    """
    print(f"A fechar manualmente o Ticket {ticket.id}")
    ticket.status = TipoStatusTicket.FECHADO
    ticket.resolucao = TipoResolucaoTicket.MANUAL
    ticket.atualizado_em = datetime.datetime.utcnow()
    session.add(ticket)
    # Nota: A conta 'requer_atencao' continua 'true'
    # O Admin deve reativá-la manualmente se desejar.
    
    try:
        usuario = session.get(Usuario, ticket.usuario_id)
        pedido = session.get(Pedido, ticket.pedido_id)
        produto = session.get(Produto, pedido.produto_id) if pedido else None
        produto_nome = escape_markdown_v2(produto.nome) if produto else "produto"

        mensagem_extra = ""
        if mensagem and mensagem.strip():
            mensagem_limpa = escape_markdown_v2(mensagem.strip())
            mensagem_extra = f"\n\nMensagem do suporte:\n{mensagem_limpa}"

        message = (
            f"✅ *Ticket Fechado Manualmente*\n\n"
            f"O seu ticket para *{produto_nome}* foi fechado manualmente\\."
            f"{mensagem_extra}"
        )
        send_telegram_message(telegram_id=usuario.telegram_id, message_text=message)
    except Exception as e_notify:
        print(f"ERRO: Falha ao enviar notificação de fechamento para {ticket.usuario_id}: {e_notify}")

# --- A Tarefa Principal do Celery ---

@celery_app.task(name="resolver_ticket")
def resolver_ticket(ticket_id: str, acao: str, mensagem: Optional[str] = None):
    """
    Tarefa Celery (real) para processar a resolução de um ticket.
    Cria a sua própria sessão de banco de dados.
    """
    print("="*50)
    print(f"CELERY WORKER: Tarefa 'resolver_ticket' INICIADA!")
    print(f"  -> Ticket ID: {ticket_id}")
    print(f"  -> Ação: {acao}")
    
    # O Worker cria a sua própria sessão 'with' para garantir que fecha
    with Session(engine) as session:
        try:
            ticket_uuid = uuid.UUID(ticket_id)
            # Bloqueia a linha do ticket para evitar que outra tarefa
            # o processe ao mesmo tempo
            ticket = session.get(TicketSuporte, ticket_uuid, with_for_update=True)

            if not ticket:
                raise Exception(f"Ticket {ticket_id} não encontrado.")
            
            if ticket.status != TipoStatusTicket.EM_ANALISE:
                raise Exception(f"Ticket {ticket_id} não está 'EM_ANALISE'. Status: {ticket.status}")

            # --- Delega a lógica de negócio ---
            if acao == "REEMBOLSAR_CARTEIRA":
                handle_reembolso_carteira(session, ticket)
            elif acao == "TROCAR_CONTA":
                handle_trocar_conta(session, ticket)
            elif acao == "FECHAR_MANUALMENTE":
                handle_fechar_manualmente(session, ticket, mensagem)
            else:
                raise Exception(f"Ação desconhecida: {acao}")

            # Se tudo correu bem, commita a transação
            session.commit()
            print(f"CELERY WORKER: Tarefa {ticket_id} concluída com sucesso.")

        except Exception as e:
            # Se algo falhar, dá rollback em tudo
            print(f"ERRO CRÍTICO na tarefa 'resolver_ticket' (ID: {ticket_id}): {e}")
            session.rollback()
            
            # Tenta reabrir o ticket para não o perder
            try:
                # Precisa de uma nova sessão (a anterior está "morta")
                with Session(engine) as session_fail:
                    ticket_fail = session_fail.get(TicketSuporte, ticket_uuid)
                    if ticket_fail and ticket_fail.status == TipoStatusTicket.EM_ANALISE:
                        ticket_fail.status = TipoStatusTicket.ABERTO
                        session_fail.add(ticket_fail)
                        session_fail.commit()
                        print(f"Ticket {ticket_id} foi reaberto devido a erro na tarefa.")
            except Exception as e_inner:
                print(f"ERRO CRÍTICO AO TENTAR REABRIR TICKET {ticket_id}: {e_inner}")

    print("="*50)
    return f"Tarefa {ticket_id} processada."
