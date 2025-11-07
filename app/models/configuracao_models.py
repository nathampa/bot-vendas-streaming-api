import uuid
from decimal import Decimal
from enum import Enum
from sqlmodel import SQLModel, Field, Relationship

class TipoGatilhoAfiliado(str, Enum):
    primeira_recarga = "primeira_recarga"
    primeira_compra = "primeira_compra"

class TipoPremioAfiliado(str, Enum):
    cashback_pendente = "cashback_pendente"
    giftcard_imediato = "giftcard_imediato"


class Configuracao(SQLModel, table=True):
    """
    Tabela para armazenar configurações globais do sistema.
    Idealmente, esta tabela terá apenas UMA linha (singleton).
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)

    # --- Configurações de Afiliados ---
    afiliado_ativo: bool = Field(default=False)
    
    afiliado_gatilho: TipoGatilhoAfiliado = Field(
        default=TipoGatilhoAfiliado.primeira_recarga
    )
    
    afiliado_tipo_premio: TipoPremioAfiliado = Field(
        default=TipoPremioAfiliado.cashback_pendente
    )
    
    # O valor do prêmio
    # Se tipo=cashback, isso é a % (ex: 50.00 para 50%)
    # Se tipo=giftcard, isso é o valor em R$ (ex: 5.00 para R$5)
    afiliado_valor_premio: Decimal = Field(
        default=0, max_digits=10, decimal_places=2
    )