import uuid
import secrets
from decimal import Decimal
from sqlmodel import Session, select, func

from app.models.usuario_models import Usuario, RecargaSaldo
from app.models.pedido_models import Pedido
from app.models.produto_models import Produto
from app.models.suporte_models import GiftCard
from app.models.configuracao_models import Configuracao, TipoGatilhoAfiliado, TipoPremioAfiliado
from app.models.base import TipoStatusPagamento

from app.services.notification_service import send_telegram_message, escape_markdown_v2

def _get_configuracao(db: Session) -> Configuracao:
    """
    Obtém a configuração do sistema. Cria a linha de configuração
    padrão se ela não existir.
    """
    config = db.exec(select(Configuracao)).first()
    if not config:
        print("CONFIG: Nenhuma configuração encontrada, criando padrão.")
        config = Configuracao()
        db.add(config)
        db.commit()
        db.refresh(config)
    return config

def _get_preco_produto_mais_barato(db: Session) -> Decimal:
    """
    Busca o menor preço entre todos os produtos ativos.
    """
    preco_minimo = db.exec(
        select(func.min(Produto.preco))
        .where(Produto.is_ativo == True)
    ).first()
    
    return preco_minimo or Decimal("0.0")

def _gerar_premio_giftcard(db: Session, referrer: Usuario, valor_premio: Decimal) -> GiftCard:
    """
    Gera um novo gift card para o indicador.
    """
    codigo = f"REF-{secrets.token_hex(3).upper()}-{secrets.token_hex(3).upper()}"
    
    novo_giftcard = GiftCard(
        codigo=codigo,
        valor=valor_premio,
        criado_por_admin_id=referrer.id # O 'criado_por' será o próprio indicador
    )
    db.add(novo_giftcard)
    db.commit()
    db.refresh(novo_giftcard)
    print(f"AFILIADO: Giftcard de R$ {valor_premio} gerado para {referrer.telegram_id}")
    return novo_giftcard

def _notificar_indicador(referrer: Usuario, premio_tipo: TipoPremioAfiliado, valor_premio: Decimal, novo_giftcard_codigo: str | None = None):
    """
    Envia uma mensagem no Telegram para o indicador avisando do prêmio.
    """
    try:
        mensagem = "🎉 *Você ganhou um prêmio de indicação!* 🎉\n\n"
        
        if premio_tipo == TipoPremioAfiliado.cashback_pendente:
            mensagem += (
                f"Um amigo que você indicou completou a primeira recarga!\n"
                f"Você ganhou um bônus de *{int(valor_premio)}% de cashback* "
                f"na sua próxima recarga no bot."
            )
        
        elif premio_tipo == TipoPremioAfiliado.giftcard_imediato:
            mensagem += (
                f"Um amigo que você indicou completou a primeira recarga!\n"
                f"Você ganhou um Gift Card no valor de *R$ {valor_premio:.2f}*.\n\n"
                f"Use o código no bot: `{novo_giftcard_codigo}`"
            )

        mensagem_escapada = escape_markdown_v2(mensagem)
        send_telegram_message(
            telegram_id=referrer.telegram_id,
            message_text=mensagem_escapada
        )
    except Exception as e:
        print(f"AFILIADO: Erro ao notificar indicador {referrer.telegram_id}: {e}")


# --- FUNÇÃO PRINCIPAL ---
def processar_gatilho_afiliado(
    db: Session, 
    usuario_indicado: Usuario, 
    valor_evento: Decimal, 
    gatilho: TipoGatilhoAfiliado
):
    """
    Função principal chamada quando um usuário indicado
    completa uma ação (recarga ou compra).
    """
    print(f"AFILIADO: Processando gatilho '{gatilho.value}' para usuário {usuario_indicado.telegram_id}")
    
    # 1. Obter a configuração
    config = _get_configuracao(db)
    if not config.afiliado_ativo:
        print("AFILIADO: Sistema inativo. Ignorando.")
        return

    # 2. O gatilho do evento (recarga) bate com o gatilho da regra?
    if config.afiliado_gatilho != gatilho:
        print(f"AFILIADO: Gatilho do evento ({gatilho.value}) não bate com a regra ({config.afiliado_gatilho.value}). Ignorando.")
        return

    # 3. O usuário indicado tem um indicador (referrer)?
    if not usuario_indicado.referrer_id:
        print(f"AFILIADO: Usuário {usuario_indicado.telegram_id} não tem indicador. Ignorando.")
        return
        
    # 4. É a primeira vez que esse gatilho ocorre?
    if gatilho == TipoGatilhoAfiliado.primeira_recarga:
        # Conta quantas recargas PAGAS este usuário já teve
        recargas_pagas_count = db.exec(
            select(func.count(RecargaSaldo.id))
            .where(RecargaSaldo.usuario_id == usuario_indicado.id)
            .where(RecargaSaldo.status_pagamento == TipoStatusPagamento.PAGO)
        ).one()
        # Se ele já tem 1 (a que acabou de ser paga), está ok. Se tiver > 1, não é a primeira.
        if recargas_pagas_count > 1:
            print("AFILIADO: Não é a primeira recarga. Ignorando.")
            return
            
    elif gatilho == TipoGatilhoAfiliado.primeira_compra:
        # Conta quantos pedidos este usuário já teve
        pedidos_count = db.exec(
            select(func.count(Pedido.id))
            .where(Pedido.usuario_id == usuario_indicado.id)
        ).one()
        # Se ele já tem 1 (o que acabou de fazer), ok. Se > 1, não é a primeira.
        if pedidos_count > 1:
            print("AFILIADO: Não é a primeira compra. Ignorando.")
            return

    # 5. REGRA DO VALOR MÍNIMO (Sua regra)
    preco_minimo_produto = _get_preco_produto_mais_barato(db)
    if valor_evento < preco_minimo_produto:
        print(f"AFILIADO: Valor (R$ {valor_evento}) é menor que o produto mais barato (R$ {preco_minimo_produto}). Ignorando.")
        return

    # --- TODOS OS TESTES PASSARAM. HORA DE DAR O PRÊMIO ---
    
    try:
        # Obtém o objeto 'Usuario' do indicador
        referrer = db.get(Usuario, usuario_indicado.referrer_id)
        if not referrer:
            print(f"AFILIADO: Referrer UUID {usuario_indicado.referrer_id} não encontrado.")
            return

        print(f"AFILIADO: Concedendo prêmio para {referrer.telegram_id}...")
        
        premio_tipo = config.afiliado_tipo_premio
        valor_premio = config.afiliado_valor_premio
        codigo_gift_card = None

        if premio_tipo == TipoPremioAfiliado.cashback_pendente:
            referrer.pending_cashback_percent = int(valor_premio)
            db.add(referrer)
            print(f"AFILIADO: Cashback de {valor_premio}% pendente para {referrer.telegram_id}")

        elif premio_tipo == TipoPremioAfiliado.giftcard_imediato:
            novo_giftcard = _gerar_premio_giftcard(db, referrer, valor_premio)
            codigo_gift_card = novo_giftcard.codigo

        # Envia a notificação para o indicador
        _notificar_indicador(referrer, premio_tipo, valor_premio, codigo_gift_card)
        
        # Salva o prêmio (cashback)
        db.commit()

    except Exception as e:
        db.rollback()
        print(f"AFILIADO: ERRO CRÍTICO AO CONCEDER PRÊMIO: {e}")