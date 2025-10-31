import uuid
import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from sqlalchemy.exc import NoResultFound # Vamos usar para controlo

from app.db.database import get_session
from app.models.usuario_models import Usuario
from app.models.produto_models import Produto, EstoqueConta
from app.models.pedido_models import Pedido
from app.schemas.compra_schemas import CompraCreateRequest, CompraCreateResponse
from app.api.v1.deps import get_current_admin_user # (Vamos precisar disto? Não, é rota de bot)
from app.services import security # Para descriptografar a senha

# Roteador para Compras
router = APIRouter()

# TODO: Proteger esta rota com uma X-API-Key (a fazer depois)
# Por enquanto, fica aberta para testes.

@router.post("/", response_model=CompraCreateResponse)
def create_compra_com_saldo(
    *,
    session: Session = Depends(get_session),
    compra_in: CompraCreateRequest
):
    """
    [BOT] Endpoint principal de compra.
    
    Executa uma transação atómica para:
    1. Validar e debitar o saldo do usuário.
    2. Encontrar e alocar um slot de estoque (com bloqueio 'FOR UPDATE').
    3. Criar um registro de pedido.
    4. Retornar a conta descriptografada.
    
    Se qualquer passo falhar, a transação inteira é revertida (rollback).
    """
    
    # Usamos try/except para garantir o rollback em caso de falha de lógica
    try:
        # --- 1. Obter o Comprador e o Produto ---
        
        # Encontra o usuário
        usuario = session.exec(
            select(Usuario).where(Usuario.telegram_id == compra_in.telegram_id)
        ).first()
        if not usuario:
            raise HTTPException(status_code=404, detail="Usuário não encontrado.")
            
        # Encontra o produto
        produto = session.get(Produto, compra_in.produto_id)
        if not produto or not produto.is_ativo:
            raise HTTPException(status_code=404, detail="Produto não encontrado ou inativo.")
            
        # --- 2. Validar Saldo ---
        
        if usuario.saldo_carteira < produto.preco:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED, 
                detail=f"Saldo insuficiente. Saldo atual: {usuario.saldo_carteira}, Preço: {produto.preco}"
            )
            
        # --- 3. Encontrar e Alocar Estoque (A parte crítica) ---
        
        # Esta query é especial:
        # 1. Encontra uma conta para este produto
        # 2. Que esteja ativa (is_ativo) e não marcada (requer_atencao)
        # 3. Que tenha slots livres (slots_ocupados < max_slots)
        # 4. with_for_update(skip_locked=True): BLOQUEIA a linha encontrada.
        #    Se outro processo já a bloqueou, o 'skip_locked' faz
        #    a query saltar para a próxima conta, evitando que o user espere.
        stmt = (
            select(EstoqueConta)
            .where(EstoqueConta.produto_id == produto.id)
            .where(EstoqueConta.is_ativo == True)
            .where(EstoqueConta.requer_atencao == False)
            .where(EstoqueConta.slots_ocupados < EstoqueConta.max_slots)
            .order_by(EstoqueConta.slots_ocupados) # Prioriza as mais vazias
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        
        conta_para_alocar = session.exec(stmt).first()
        
        if not conta_para_alocar:
            # Se não encontrou nenhuma conta, o estoque acabou.
            # A exceção fará o 'get_session' dar rollback no saldo.
            raise HTTPException(status_code=404, detail="Estoque esgotado para este produto.")
            
        # --- 4. Executar a Transação (Débito e Alocação) ---
        
        # a. Debitar o saldo do usuário
        valor_pago = produto.preco
        usuario.saldo_carteira = usuario.saldo_carteira - valor_pago
        session.add(usuario)
        
        # b. Alocar o slot na conta
        conta_para_alocar.slots_ocupados += 1
        session.add(conta_para_alocar)
        
        # c. Criar o "Recibo" (Pedido)
        novo_pedido = Pedido(
            usuario_id=usuario.id,
            produto_id=produto.id,
            estoque_conta_id=conta_para_alocar.id,
            valor_pago=valor_pago
        )
        session.add(novo_pedido)
        
        # d. Salvar tudo no banco
        # A dependência 'get_session' (com 'with Session...')
        # fará o commit aqui se tudo correu bem
        session.commit()
        
        # Precisamos "refrescar" os objetos para pegar os dados do banco (IDs, etc.)
        session.refresh(novo_pedido)
        session.refresh(usuario)
        
        # --- 5. Descriptografar e Retornar ---
        
        senha_descriptografada = security.decrypt_data(conta_para_alocar.senha)
        if not senha_descriptografada:
            # Isso é grave! Significa que nossa chave AES mudou ou os dados
            # estão corrompidos. O usuário pagou mas não podemos entregar.
            print(f"ERRO CRÍTICO: Falha ao descriptografar senha do estoque_id {conta_para_alocar.id}")
            raise HTTPException(status_code=500, detail="Erro interno ao obter credenciais.")

        return CompraCreateResponse(
            pedido_id=novo_pedido.id,
            data_compra=novo_pedido.criado_em,
            valor_pago=novo_pedido.valor_pago,
            novo_saldo=usuario.saldo_carteira,
            produto_nome=produto.nome,
            login=conta_para_alocar.login,
            senha=senha_descriptografada
        )

    except HTTPException as http_exc:
        # Se nós mesmos lançámos a exceção (ex: 404 Estoque esgotado),
        # o 'get_session' dará rollback, e nós apenas re-lançamos a exceção.
        session.rollback()
        raise http_exc
    except Exception as e:
        # Se um erro inesperado do banco (ex: falha de constraint)
        # acontecer, damos rollback e lançamos um 500.
        session.rollback()
        print(f"ERRO INESPERADO NA COMPRA: {e}")
        raise HTTPException(status_code=500, detail=f"Erro interno: {e}")