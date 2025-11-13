import uuid
import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from sqlalchemy.exc import NoResultFound 

from app.db.database import get_session
from app.models.usuario_models import Usuario
from app.models.produto_models import Produto, EstoqueConta
from app.models.pedido_models import Pedido
from app.models.base import TipoEntregaProduto, StatusEntregaPedido
from app.schemas.compra_schemas import CompraCreateRequest, CompraCreateResponse
from app.api.v1.deps import get_current_admin_user 
from app.services import security 

router = APIRouter()

@router.post("/", response_model=CompraCreateResponse)
def create_compra_com_saldo(
    *,
    session: Session = Depends(get_session),
    compra_in: CompraCreateRequest
):
    """
    [BOT] Endpoint principal de compra.
    AGORA COM LÓGICA SEPARADA PARA ENTREGA MANUAL (VIA ADMIN).
    """
    
    try:
        # --- 1. Obter o Comprador e o Produto ---
        usuario = session.exec(
            select(Usuario).where(Usuario.telegram_id == compra_in.telegram_id)
        ).first()
        if not usuario:
            raise HTTPException(status_code=404, detail="Usuário não encontrado.")
            
        produto = session.get(Produto, compra_in.produto_id)
        if not produto or not produto.is_ativo:
            raise HTTPException(status_code=404, detail="Produto não encontrado ou inativo.")
            
        # --- 2. Validar Saldo ---
        if usuario.saldo_carteira < produto.preco:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED, 
                detail=f"Saldo insuficiente. Saldo atual: {usuario.saldo_carteira}, Preço: {produto.preco}"
            )

        # --- 3. EXECUTAR TRANSAÇÃO (Débito) ---
        valor_pago = produto.preco
        usuario.saldo_carteira = usuario.saldo_carteira - valor_pago
        session.add(usuario)

        # Variáveis que vamos preencher
        conta_para_alocar_id = None
        login_entrega = None
        senha_entrega = None
        mensagem_entrega = ""
        # Nova variável para o status do pedido
        status_entrega_pedido = StatusEntregaPedido.ENTREGUE # Padrão

        # --- 4. LÓGICA DE ENTREGA (IF/ELSE substituído por MATCH) ---
        
        match produto.tipo_entrega:
            
            case TipoEntregaProduto.AUTOMATICA:
                # --- FLUXO PADRÃO (Netflix, etc.) ---
                # Procura uma conta no estoque
                stmt = (
                    select(EstoqueConta)
                    .where(EstoqueConta.produto_id == produto.id)
                    .where(EstoqueConta.is_ativo == True)
                    .where(EstoqueConta.requer_atencao == False)
                    .where(EstoqueConta.slots_ocupados < EstoqueConta.max_slots)
                    .order_by(EstoqueConta.slots_ocupados) 
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                conta_alocada = session.exec(stmt).first()
                
                if not conta_alocada:
                    raise HTTPException(status_code=404, detail="Estoque esgotado para este produto.")
                
                # Aloca o slot e o ID
                conta_alocada.slots_ocupados += 1
                session.add(conta_alocada)
                conta_para_alocar_id = conta_alocada.id # Salva o ID
                
                # Prepara a entrega
                login_entrega = conta_alocada.login
                senha_descriptografada = security.decrypt_data(conta_alocada.senha)
                if not senha_descriptografada:
                    raise HTTPException(status_code=500, detail="Erro interno ao obter credenciais.")
                senha_entrega = senha_descriptografada
                mensagem_entrega = produto.instrucoes_pos_compra or "Aqui estão suas credenciais:"
                status_entrega_pedido = StatusEntregaPedido.ENTREGUE

            case TipoEntregaProduto.SOLICITA_EMAIL:
                # --- FLUXO DE PEDIR EMAIL (Youtube, Canva) ---
                
                # Validação de Email (MOVIDA PARA CÁ)
                if not compra_in.email_cliente:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Este produto requer um email de cliente para a entrega."
                    )
                
                conta_para_alocar_id = None 
                login_entrega = None
                senha_entrega = None
                instrucao_customizada = produto.instrucoes_pos_compra or "A entrega é manual e pode levar alguns minutos."
                mensagem_entrega = (
                    f"O convite será enviado para o email:\n"
                    f"`{compra_in.email_cliente}`\n\n"
                    f"**Instruções:**\n{instrucao_customizada}"
                )
                status_entrega_pedido = StatusEntregaPedido.ENTREGUE

            case TipoEntregaProduto.MANUAL_ADMIN:
                conta_para_alocar_id = None 
                login_entrega = None
                senha_entrega = None
                mensagem_entrega = (
                    "✅ Pedido recebido!\n\n"
                    "O administrador já foi notificado e está "
                    "preparando sua conta. Você receberá uma nova "
                    "mensagem aqui no bot com as credenciais "
                    "assim que estiver pronto."
                )
                # O Pedido ficará PENDENTE até o admin agir
                status_entrega_pedido = StatusEntregaPedido.PENDENTE
        
        # --- 5. Criar o "Recibo" (Pedido) ---
        novo_pedido = Pedido(
            usuario_id=usuario.id,
            produto_id=produto.id,
            estoque_conta_id=conta_para_alocar_id,
            valor_pago=valor_pago,
            email_cliente=compra_in.email_cliente,
            status_entrega=status_entrega_pedido
        )
        session.add(novo_pedido)
        
        # --- 6. Commit e Retorno ---
        session.commit()
        
        session.refresh(novo_pedido)
        session.refresh(usuario)
        
        return CompraCreateResponse(
            pedido_id=novo_pedido.id,
            data_compra=novo_pedido.criado_em,
            valor_pago=novo_pedido.valor_pago,
            novo_saldo=usuario.saldo_carteira,
            produto_nome=produto.nome,
            login=login_entrega, # Será None se for manual
            senha=senha_entrega, # Será None se for manual
            
            tipo_entrega=produto.tipo_entrega, 
            
            mensagem_entrega=mensagem_entrega
        )

    except HTTPException as http_exc:
        session.rollback()
        raise http_exc
    except Exception as e:
        session.rollback()
        print(f"ERRO INESPERADO NA COMPRA: {e}")
        raise HTTPException(status_code=500, detail=f"Erro interno: {e}")