import uuid
import datetime
from sqlmodel import Session, select

# 1. REMOVEMOS a importação do 'celery_app'

from app.db.database import engine # Importamos o 'engine' do banco
from app.services import security # Para descriptografar a nova senha
from app.models.base import TipoStatusTicket, TipoResolucaoTicket
from app.models.usuario_models import Usuario
from app.models.pedido_models import Pedido
from app.models.produto_models import Produto, EstoqueConta
from app.models.suporte_models import TicketSuporte

# --- Funções Auxiliares (Exatamente como eram antes) ---

def handle_reembolso_carteira(session: Session, ticket: TicketSuporte):
    """
    Lógica para reembolsar o valor da compra para a carteira do usuário.
    """
    print(f"A processar REEMBOLSO para Ticket {ticket.id}")
    pedido = session.get(Pedido, ticket.pedido_id)
    usuario = session.get(Usuario, ticket.usuario_id)

    if not pedido or not usuario:
        raise Exception(f"Pedido ({ticket.pedido_id}) ou Usuário ({ticket.usuario_id}) não encontrado.")

    usuario.saldo_carteira += pedido.valor_pago

    ticket.status = TipoStatusTicket.RESOLVIDO
    ticket.resolucao = TipoResolucaoTicket.REEMBOLSO_CARTEIRA
    ticket.atualizado_em = datetime.datetime.utcnow()

    session.add(usuario)
    session.add(ticket)

    # TODO: Enviar notificação ao usuário sobre o reembolso
    print(f"Sucesso: Reembolsado {pedido.valor_pago} para usuário {usuario.id}")

def handle_trocar_conta(session: Session, ticket: TicketSuporte):
    """
    Lógica de "Troca Rápida" (Hot-Swap).
    """
    print(f"A processar TROCA RÁPIDA (Hot-Swap) para Ticket {ticket.id}")
    pedido = session.get(Pedido, ticket.pedido_id)
    produto = session.get(Produto, pedido.produto_id)

    if not pedido or not produto:
        raise Exception(f"Pedido ({ticket.pedido_id}) ou Produto ({pedido.produto_id}) não encontrado.")

    # 1. Encontrar uma nova conta
    stmt = (
        select(EstoqueConta)
        .where(EstoqueConta.produto_id == produto.id)
        .where(EstoqueConta.id != ticket.estoque_conta_id)
        .where(EstoqueConta.is_ativo == True)
        .where(EstoqueConta.requer_atencao == False)
        .where(EstoqueConta.slots_ocupados < EstoqueConta.max_slots)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    nova_conta = session.exec(stmt).first()

    # 2. Caso de Falha: Sem estoque
    if not nova_conta:
        print(f"FALHA na Troca Rápida do Ticket {ticket.id}: Sem estoque de reposição.")
        ticket.status = TipoStatusTicket.ABERTO 
        ticket.atualizado_em = datetime.datetime.utcnow()
        session.add(ticket)
        # TODO: Notificar admin
        return

    # 3. Caso de Sucesso
    nova_conta.slots_ocupados += 1
    session.add(nova_conta)

    pedido.estoque_conta_id = nova_conta.id
    session.add(pedido)

    ticket.status = TipoStatusTicket.RESOLVIDO
    ticket.resolucao = TipoResolucaoTicket.CONTA_TROCADA
    ticket.atualizado_em = datetime.datetime.utcnow()
    session.add(ticket)

    senha = security.decrypt_data(nova_conta.senha)

    # TODO: Enviar notificação ao usuário com as novas credenciais
    print(f"Sucesso: Ticket {ticket.id} resolvido com Hot-Swap. Nova conta: {nova_conta.login} / {senha}")

def handle_fechar_manualmente(session: Session, ticket: TicketSuporte):
    """
    Lógica para simplesmente fechar o ticket.
    """
    print(f"A fechar manualmente o Ticket {ticket.id}")
    ticket.status = TipoStatusTicket.FECHADO
    ticket.resolucao = TipoResolucaoTicket.MANUAL
    ticket.atualizado_em = datetime.datetime.utcnow()
    session.add(ticket)

# --- A Tarefa Principal (Agora é uma função normal) ---

# 2. REMOVEMOS o decorador '@celery_app.task'
def resolver_ticket_task(ticket_id: str, acao: str): # Renomeamos para 'resolver_ticket_task'
    """
    Tarefa (agora em background) para processar a resolução de um ticket.
    Cria a sua própria sessão de banco de dados.
    """
    print("="*50)
    print(f"BACKGROUND TASK: Tarefa 'resolver_ticket' INICIADA!")
    print(f"  -> Ticket ID: {ticket_id}")
    print(f"  -> Ação: {acao}")

    # A lógica de criar uma sessão nova continua a mesma,
    # pois a tarefa roda *depois* da sessão da API fechar.
    with Session(engine) as session:
        try:
            ticket_uuid = uuid.UUID(ticket_id)
            ticket = session.get(TicketSuporte, ticket_uuid, with_for_update=True)

            if not ticket:
                raise Exception(f"Ticket {ticket_id} não encontrado.")

            # 3. Validamos o status 'EM_ANALISE' (que a API define)
            if ticket.status != TipoStatusTicket.EM_ANALISE:
                raise Exception(f"Ticket {ticket_id} não está 'EM_ANALISE'. Status: {ticket.status}")

            # --- Delega a lógica de negócio ---
            if acao == "REEMBOLSAR_CARTEIRA":
                handle_reembolso_carteira(session, ticket)
            elif acao == "TROCAR_CONTA":
                handle_trocar_conta(session, ticket)
            elif acao == "FECHAR_MANUALMENTE":
                handle_fechar_manualmente(session, ticket)
            else:
                raise Exception(f"Ação desconhecida: {acao}")

            session.commit()
            print(f"BACKGROUND TASK: Tarefa {ticket_id} concluída com sucesso.")

        except Exception as e:
            print(f"ERRO CRÍTICO na tarefa 'resolver_ticket' (ID: {ticket_id}): {e}")
            session.rollback()

            # Tenta reabrir o ticket
            try:
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