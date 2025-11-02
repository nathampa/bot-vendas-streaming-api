import uuid
import datetime
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from app.services.ticket_services import resolver_ticket_task
from sqlmodel import Session, select
from typing import List, Optional

from app.db.database import get_session
from app.models.usuario_models import Usuario
from app.models.pedido_models import Pedido
from app.models.produto_models import EstoqueConta, Produto
from app.models.suporte_models import TicketSuporte
from app.schemas.ticket_schemas import (
    TicketCreateRequest, 
    TicketCreateResponse,
    TicketAdminRead,
    TicketAdminReadDetails,
    TicketResolveRequest
)
from app.schemas.estoque_schemas import EstoqueAdminReadDetails as SchemaEstoqueDetails
from app.models.base import TipoStatusTicket
from app.api.v1.deps import get_current_admin_user # O nosso "Cadeado"
from app.services import security # Para descriptografar
#from app.worker.celery_app import celery_app # Para chamar a tarefa

# Roteador para o Bot (criação de tickets)
router = APIRouter()
# Roteador para o Admin (gestão de tickets)
admin_router = APIRouter(dependencies=[Depends(get_current_admin_user)])


# --- ENDPOINT DO BOT (JÁ IMPLEMENTADO) ---

@router.post("/", response_model=TicketCreateResponse, status_code=status.HTTP_201_CREATED)
def create_ticket_suporte(
    *,
    session: Session = Depends(get_session),
    ticket_in: TicketCreateRequest
):
    """
    [BOT] Cria um novo ticket de suporte para um pedido.
    (O código que já implementámos e testámos)
    """
    try:
        # ... (Toda a lógica do create_ticket_suporte que já fizemos) ...
        # 1. Encontrar o usuário
        usuario = session.exec(
            select(Usuario).where(Usuario.telegram_id == ticket_in.telegram_id)
        ).first()
        if not usuario:
            raise HTTPException(status_code=404, detail="Usuário não encontrado.")
            
        # 2. Encontrar o pedido
        pedido = session.get(Pedido, ticket_in.pedido_id)
        if not pedido:
            raise HTTPException(status_code=404, detail="Pedido não encontrado.")
            
        # 3. Validação de Segurança: O usuário é o dono do pedido?
        if pedido.usuario_id != usuario.id:
            raise HTTPException(status_code=403, detail="Não autorizado a reportar este pedido.")
            
        # 4. Validação de Idempotência: Já existe um ticket?
        existing_ticket = session.exec(
            select(TicketSuporte).where(TicketSuporte.pedido_id == pedido.id)
        ).first()
        if existing_ticket:
            raise HTTPException(status_code=409, detail="Já existe um ticket de suporte para este pedido.")

        # 5. Ação Crítica: Marcar a conta como defeituosa
        conta_problematica = session.get(EstoqueConta, pedido.estoque_conta_id)
        if not conta_problematica:
            raise HTTPException(status_code=500, detail="Conta de estoque associada ao pedido não foi encontrada.")
        
        conta_problematica.requer_atencao = True
        session.add(conta_problematica)
        
        # 6. Criar o Ticket
        novo_ticket = TicketSuporte.model_validate(
            ticket_in, 
            update={
                "usuario_id": usuario.id,
                "estoque_conta_id": conta_problematica.id,
                "status": TipoStatusTicket.ABERTO
            }
        )
        session.add(novo_ticket)
        
        # 7. Commit
        session.commit()
        session.refresh(novo_ticket)
        
        return novo_ticket
        
    except HTTPException as http_exc:
        session.rollback()
        raise http_exc
    except Exception as e:
        session.rollback()
        print(f"ERRO INESPERADO AO CRIAR TICKET: {e}")
        raise HTTPException(status_code=500, detail=f"Erro interno ao criar ticket: {e}")


# --- ENDPOINTS DE ADMIN (NOVOS) ---

@admin_router.get("/", response_model=List[TicketAdminRead])
def get_lista_tickets(
    *,
    session: Session = Depends(get_session),
    status: Optional[TipoStatusTicket] = None # Filtro opcional
):
    """
    [ADMIN] Lista os tickets. Permite filtrar por status (ex: ?status=ABERTO).
    """
    query = select(TicketSuporte)
    if status:
        query = query.where(TicketSuporte.status == status)
    
    tickets = session.exec(query.order_by(TicketSuporte.criado_em.desc())).all()
    return tickets


@admin_router.get("/{ticket_id}", response_model=TicketAdminReadDetails)
def get_detalhe_ticket(
    *,
    session: Session = Depends(get_session),
    ticket_id: uuid.UUID
):
    """
    [ADMIN] Vê os detalhes completos de UM ticket.
    """
    # 1. Obter o ticket
    ticket = session.get(TicketSuporte, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket não encontrado.")

    # 2. Obter os dados relacionados (Usuário, Pedido, Produto, Conta)
    # (Usamos .one() para garantir que existem, ou falhará)
    try:
        usuario = session.exec(select(Usuario).where(Usuario.id == ticket.usuario_id)).one()
        pedido = session.exec(select(Pedido).where(Pedido.id == ticket.pedido_id)).one()
        conta = session.exec(select(EstoqueConta).where(EstoqueConta.id == ticket.estoque_conta_id)).one()
        produto = session.exec(select(Produto).where(Produto.id == pedido.produto_id)).one()
    except Exception as e:
        print(f"Erro ao buscar dados relacionados ao ticket: {e}")
        raise HTTPException(status_code=404, detail="Dados relacionados ao ticket (usuário, pedido, etc.) não encontrados.")

    # 3. Descriptografar a senha da conta problemática
    senha_descriptografada = security.decrypt_data(conta.senha)

    # 4. Construir o sub-schema da conta
    conta_details = SchemaEstoqueDetails.model_validate(conta)
    conta_details.senha = senha_descriptografada

    # 5. Construir a resposta detalhada (schema 'TicketAdminReadDetails')
    #    NÃO USAMOS model_validate(ticket)
    #    Nós construímos o objeto 'TicketAdminReadDetails' manualmente
    #    passando todos os campos que ele espera.
    response = TicketAdminReadDetails(
        # Campos do Ticket (da herança 'TicketAdminRead')
        id=ticket.id,
        status=ticket.status,
        motivo=ticket.motivo,
        criado_em=ticket.criado_em,
        usuario_id=ticket.usuario_id,
        pedido_id=ticket.pedido_id,

        # Campos do Ticket (do 'TicketAdminReadDetails')
        descricao_outros=ticket.descricao_outros,
        resolucao=ticket.resolucao,
        atualizado_em=ticket.atualizado_em,

        # Nossos campos extra (do 'TicketAdminReadDetails')
        usuario_telegram_id=usuario.telegram_id,
        produto_nome=produto.nome,
        conta_problematica=conta_details
    )

    return response

@admin_router.post("/{ticket_id}/resolver", status_code=status.HTTP_202_ACCEPTED)
def request_resolucao_ticket(
    *,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    ticket_id: uuid.UUID,
    resolve_in: TicketResolveRequest
):
    """
    [ADMIN] Solicita a resolução de um ticket (Troca Rápida ou Reembolso).
    
    Isto NÃO executa a lógica. Apenas enfileira uma tarefa
    no Celery e retorna 202 (Aceito).
    """
    ticket = session.get(TicketSuporte, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket não encontrado.")
    
    if ticket.status != TipoStatusTicket.ABERTO:
        raise HTTPException(status_code=400, detail="Este ticket não está aberto para resolução.")
        
    # 1. Validar a Ação
    acao = resolve_in.acao.upper()
    if acao not in ("TROCAR_CONTA", "REEMBOLSAR_CARTEIRA", "FECHAR_MANUALMENTE"):
        raise HTTPException(status_code=400, detail=f"Ação '{acao}' inválida.")
        
    # 2. Mudar o status para "Em Análise" (para evitar duplicação)
    ticket.status = TipoStatusTicket.EM_ANALISE
    session.add(ticket)
    session.commit()
    
    # 3. Enviar a tarefa para o Celery (o 'worker' fará o trabalho pesado)
    print(f"Enviando tarefa 'resolver_ticket' para o Celery: {ticket.id}, Ação: {acao}")
    background_tasks.add_task(
        resolver_ticket_task,
        ticket_id=str(ticket.id), 
        acao=acao
    )
    
    return {"message": "Solicitação de resolução recebida.", "ticket_id": ticket.id, "acao": acao}