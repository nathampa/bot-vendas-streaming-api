import datetime
import uuid
from typing import Optional, Tuple

from sqlmodel import Session, select

from app.models.conta_mae_models import ContaMae, ContaMaeConvite
from app.models.produto_models import EstoqueConta


def resolver_data_expiracao_pedido(
    *,
    session: Session,
    pedido_id: uuid.UUID,
    email_cliente: Optional[str],
    estoque_conta_id: Optional[uuid.UUID],
    conta_mae_id: Optional[uuid.UUID],
) -> Tuple[Optional[datetime.date], Optional[str]]:
    """
    Resolve a data de expiração efetiva de um pedido.
    Prioridade:
    1) Conta-mãe vinculada ao convite do pedido/email.
    2) Conta-mãe do próprio pedido.
    3) Conta de estoque do pedido.
    """
    data_expiracao: Optional[datetime.date] = None
    origem_expiracao: Optional[str] = None

    stmt_convite = select(ContaMaeConvite).where(ContaMaeConvite.pedido_id == pedido_id)
    if email_cliente:
        stmt_convite = stmt_convite.where(ContaMaeConvite.email_cliente == email_cliente)

    convite = session.exec(stmt_convite.limit(1)).first()
    if convite:
        conta_mae = session.get(ContaMae, convite.conta_mae_id)
        if conta_mae and conta_mae.data_expiracao:
            return conta_mae.data_expiracao, "CONTA_MAE"

    if conta_mae_id:
        conta_mae = session.get(ContaMae, conta_mae_id)
        if conta_mae and conta_mae.data_expiracao:
            return conta_mae.data_expiracao, "CONTA_MAE"

    if estoque_conta_id:
        conta_estoque = session.get(EstoqueConta, estoque_conta_id)
        if conta_estoque and conta_estoque.data_expiracao:
            return conta_estoque.data_expiracao, "ESTOQUE"

    return data_expiracao, origem_expiracao
