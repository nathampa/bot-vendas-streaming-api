import datetime
from typing import Optional

from sqlmodel import Session, select

from app.models.base import TipoEntregaProduto
from app.models.conta_mae_models import ContaMae
from app.models.produto_models import EstoqueConta, Produto


def inativar_conta_estoque_se_lotada(conta: EstoqueConta) -> bool:
    """
    Inativa automaticamente a conta de estoque quando todos os slots já foram ocupados.
    """
    if conta.slots_ocupados >= conta.max_slots and conta.is_ativo:
        conta.is_ativo = False
        return True
    return False


def inativar_conta_mae_se_lotada(conta: ContaMae) -> bool:
    """
    Inativa automaticamente a conta-mãe quando todos os slots já foram ocupados.
    """
    if conta.slots_ocupados >= conta.max_slots and conta.is_ativo:
        conta.is_ativo = False
        return True
    return False


def inativar_produto_sem_contas_disponiveis(
    session: Session,
    produto: Produto,
) -> bool:
    """
    Inativa automaticamente o produto quando não há mais contas ativas com slot disponível.
    Esta função nunca reativa produto automaticamente.
    """
    if not produto.is_ativo:
        return False

    disponivel = _produto_tem_disponibilidade(session, produto)
    if not disponivel:
        produto.is_ativo = False
        session.add(produto)
        return True

    return False


def _produto_tem_disponibilidade(session: Session, produto: Produto) -> bool:
    if produto.tipo_entrega == TipoEntregaProduto.AUTOMATICA:
        conta_disponivel_id: Optional[str] = session.exec(
            select(EstoqueConta.id)
            .where(EstoqueConta.produto_id == produto.id)
            .where(EstoqueConta.is_ativo == True)
            .where(EstoqueConta.requer_atencao == False)
            .where(EstoqueConta.slots_ocupados < EstoqueConta.max_slots)
            .limit(1)
        ).first()
        return conta_disponivel_id is not None

    if produto.tipo_entrega == TipoEntregaProduto.SOLICITA_EMAIL:
        today = datetime.date.today()
        conta_disponivel_id: Optional[str] = session.exec(
            select(ContaMae.id)
            .where(ContaMae.produto_id == produto.id)
            .where(ContaMae.is_ativo == True)
            .where(ContaMae.slots_ocupados < ContaMae.max_slots)
            .where((ContaMae.data_expiracao == None) | (ContaMae.data_expiracao >= today))
            .limit(1)
        ).first()
        return conta_disponivel_id is not None

    # Produto manual não depende de estoque/slots para ficar ativo.
    return True
