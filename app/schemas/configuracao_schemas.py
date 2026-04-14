from sqlmodel import SQLModel


class ConfiguracaoBotStatusRead(SQLModel):
    modo_manutencao: bool


class ConfiguracaoBotManutencaoUpdateRequest(SQLModel):
    telegram_id: int
    ativo: bool
