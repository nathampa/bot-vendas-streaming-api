import uuid
import datetime
import secrets
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from typing import List

from app.db.database import get_session
from app.models.usuario_models import Usuario
from app.models.suporte_models import GiftCard
from app.schemas.giftcard_schemas import (
    GiftCardCreateRequest,
    GiftCardCreateResponse,
    GiftCardAdminRead,
    GiftCardResgatarRequest,
    GiftCardResgatarResponse
)
from app.api.v1.deps import get_current_admin_user # O "Cadeado" do Admin
from app.api.v1.endpoints.recargas import get_or_create_usuario # Reutilizamos a função!

# Roteador para o Bot (resgate de gift cards)
router = APIRouter()
# Roteador para o Admin (criação de gift cards)
admin_router = APIRouter(dependencies=[Depends(get_current_admin_user)])

# --- ENDPOINTS DE ADMIN ---

@admin_router.post("/", response_model=GiftCardCreateResponse, status_code=status.HTTP_201_CREATED)
def create_gift_cards(
    *,
    session: Session = Depends(get_session),
    current_admin: Usuario = Depends(get_current_admin_user), # Pega o admin logado
    giftcard_in: GiftCardCreateRequest
):
    """
    [ADMIN] Cria um ou mais novos Gift Cards.
    """
    
    codigos_gerados = []
    
    if giftcard_in.codigo_personalizado:
        # 1. Caso: Código Personalizado (ex: "NATAL2025")
        if giftcard_in.quantidade > 1:
            raise HTTPException(status_code=400, detail="Não pode usar 'quantidade' com 'codigo_personalizado'.")
            
        # Verifica se o código já existe
        existing_code = session.exec(select(GiftCard).where(GiftCard.codigo == giftcard_in.codigo_personalizado)).first()
        if existing_code:
            raise HTTPException(status_code=409, detail="Este código personalizado já está em uso.")
            
        novo_giftcard = GiftCard(
            codigo=giftcard_in.codigo_personalizado,
            valor=giftcard_in.valor,
            criado_por_admin_id=current_admin.id
        )
        session.add(novo_giftcard)
        codigos_gerados.append(novo_giftcard.codigo)
        
    else:
        # 2. Caso: Gerar Múltiplos Códigos Aleatórios
        for _ in range(giftcard_in.quantidade):
            # Gera um código aleatório seguro (ex: ABC-123-XYZ)
            codigo = f"{secrets.token_hex(3).upper()}-{secrets.token_hex(3).upper()}"
            
            # (Numa app de produção, teríamos um loop while para garantir que o código é 100% único)
            novo_giftcard = GiftCard(
                codigo=codigo,
                valor=giftcard_in.valor,
                criado_por_admin_id=current_admin.id
            )
            session.add(novo_giftcard)
            codigos_gerados.append(novo_giftcard.codigo)

    session.commit()
    
    return GiftCardCreateResponse(
        codigos_gerados=codigos_gerados,
        valor=giftcard_in.valor,
        quantidade=len(codigos_gerados)
    )

@admin_router.get("/", response_model=List[GiftCardAdminRead])
def get_lista_gift_cards(
    *,
    session: Session = Depends(get_session)
):
    """
    [ADMIN] Lista todos os Gift Cards criados.
    """
    # Esta query complexa (JOIN) busca o telegram_id do usuário que resgatou
    stmt = (
        select(GiftCard, Usuario.telegram_id)
        .join(Usuario, Usuario.id == GiftCard.utilizado_por_usuario_id, isouter=True) # isouter=True é um LEFT JOIN
        .order_by(GiftCard.criado_em.desc())
    )
    
    resultados = session.exec(stmt).all()
    
    # Monta a resposta
    lista_resposta = []
    for giftcard, telegram_id in resultados:
        # Converte o model do banco (GiftCard) para o schema de resposta (GiftCardAdminRead)
        gc_read = GiftCardAdminRead.model_validate(giftcard)
        gc_read.utilizado_por_telegram_id = telegram_id
        lista_resposta.append(gc_read)
        
    return lista_resposta

@admin_router.delete("/{gift_card_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_gift_card(
    *,
    session: Session = Depends(get_session),
    gift_card_id: uuid.UUID
):
    """
    [ADMIN] Deleta um Gift Card específico pelo seu ID.
    
    Nota: Esta é uma operação destrutiva. O card será removido
    permanentemente, independentemente de ter sido usado ou não.
    """
    
    # 1. Encontra o Gift Card pelo ID (chave primária)
    # session.get() é a forma mais eficiente de buscar por PK
    db_gift_card = session.get(GiftCard, gift_card_id)
    
    # 2. Verifica se ele existe
    if not db_gift_card:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Gift Card não encontrado."
        )
        
    # 3. Se existe, deleta
    try:
        session.delete(db_gift_card)
        session.commit()
    except Exception as e:
        # Em caso de erro de banco de dados (ex: restrições de FK)
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao deletar o Gift Card: {e}"
        )

    # 4. Retorna 204 No Content (definido no decorator)
    # Nenhum conteúdo é retornado no sucesso
    return

# --- ENDPOINT DO BOT ---

@router.post("/resgatar", response_model=GiftCardResgatarResponse)
def resgatar_gift_card(
    *,
    session: Session = Depends(get_session),
    resgate_in: GiftCardResgatarRequest
):
    """
    [BOT] Resgata um código de Gift Card e adiciona o saldo à carteira.
    
    (Nota: telegram_id e nome_completo do usuário são necessários
     no body para o 'get_or_create_usuario' funcionar,
     vamos ajustar o schema...)
    """
    # Correção: O schema 'GiftCardResgatarRequest' precisa do nome.
    # Vamos assumir que o 'get_or_create' não é necessário aqui,
    # o usuário já deve existir (pois tentou /start no bot).
    # Vamos simplificar e exigir que o usuário exista.
    
    # 1. Encontra o usuário
    usuario = session.exec(
        select(Usuario).where(Usuario.telegram_id == resgate_in.telegram_id)
    ).first()
    
    if not usuario:
        # Se o usuário não existe, ele não pode resgatar.
        # (O bot deve sempre criar o usuário primeiro com a rota de recarga ou /start)
        raise HTTPException(status_code=404, detail="Usuário não encontrado. Inicie o bot primeiro.")
        
    # 2. Encontra o Gift Card (COM BLOQUEIO)
    # Usamos 'with_for_update=True' para bloquear esta linha.
    # Isso impede que o mesmo usuário clique "Resgatar" duas vezes
    # muito rápido e resgate o código duas vezes (race condition).
    
    codigo_normalizado = resgate_in.codigo.upper().strip()
    
    gift_card = session.exec(
        select(GiftCard)
        .where(GiftCard.codigo == codigo_normalizado)
        .with_for_update()
    ).first()
    
    # 3. Validações
    if not gift_card:
        raise HTTPException(status_code=404, detail="Código de Gift Card não encontrado.")
        
    if gift_card.is_utilizado:
        raise HTTPException(status_code=410, detail="Este código já foi utilizado.")
        
    # 4. Transação: Resgata o código e credita o saldo
    try:
        # a. Marca o gift card como usado
        gift_card.is_utilizado = True
        gift_card.utilizado_em = datetime.datetime.utcnow()
        gift_card.utilizado_por_usuario_id = usuario.id
        session.add(gift_card)
        
        # b. Adiciona o saldo à carteira do usuário
        usuario.saldo_carteira += gift_card.valor
        session.add(usuario)
        
        # c. Salva tudo
        session.commit()
        session.refresh(usuario) # Pega o novo saldo
        
        return GiftCardResgatarResponse(
            valor_resgatado=gift_card.valor,
            novo_saldo_total=usuario.saldo_carteira
        )

    except Exception as e:
        session.rollback()
        print(f"ERRO CRÍTICO no resgate de Gift Card: {e}")
        raise HTTPException(status_code=500, detail="Erro interno ao processar o resgate.")
    
