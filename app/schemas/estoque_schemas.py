import uuid
from decimal import Decimal
from typing import Optional
from sqlmodel import SQLModel

# -----------------------------------------------------------------
# Schema para CRIAÇÃO (o que o Admin envia para abastecer)
# -----------------------------------------------------------------
class EstoqueCreate(SQLModel):
    produto_id: uuid.UUID  # O ID do Produto (ex: "Netflix") ao qual esta conta pertence
    login: str
    senha: str  # A API receberá em texto plano e irá criptografar
    max_slots: int = 2

# -----------------------------------------------------------------
# Schema para LEITURA (o que o Admin vê na lista do painel)
# -----------------------------------------------------------------
# Nota: NÃO incluímos a senha aqui por segurança.
# A senha só é mostrada ao clicar em "Ver Detalhes".
class EstoqueAdminRead(SQLModel):
    id: uuid.UUID
    produto_id: uuid.UUID
    login: str
    max_slots: int
    slots_ocupados: int
    is_ativo: bool
    requer_atencao: bool

# -----------------------------------------------------------------
# Schema para LEITURA DE DETALHES (o que o Admin vê em UMA conta)
# -----------------------------------------------------------------
# Este schema SIM, inclui a senha (descriptografada)
class EstoqueAdminReadDetails(EstoqueAdminRead):
    senha: Optional[str] # Será preenchido com a senha descriptografada

# -----------------------------------------------------------------
# Schema para ATUALIZAÇÃO (o que o Admin usa para editar)
# -----------------------------------------------------------------
class EstoqueUpdate(SQLModel):
    login: Optional[str] = None
    senha: Optional[str] = None # Se uma nova senha for enviada, a API irá criptografá-la
    max_slots: Optional[int] = None
    slots_ocupados: Optional[int] = None
    is_ativo: Optional[bool] = None
    requer_atencao: Optional[bool] = None