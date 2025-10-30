import enum
from sqlmodel import SQLModel

# --- ENUMs (Tipos Customizados) ---
# Estes ENUMs garantem que apenas valores válidos 
# possam ser inseridos nas colunas de "status" do banco.

class TipoStatusPagamento(str, enum.Enum):
    PENDENTE = "PENDENTE"
    PAGO = "PAGO"
    FALHOU = "FALHOU"
    ESTORNADO = "ESTORNADO"

class TipoStatusTicket(str, enum.Enum):
    ABERTO = "ABERTO"
    EM_ANALISE = "EM_ANALISE"
    RESOLVIDO = "RESOLVIDO"
    FECHADO = "FECHADO"

class TipoResolucaoTicket(str, enum.Enum):
    NA = "N/A" # "N/A" não é um nome de variável válido em Python
    CONTA_TROCADA = "CONTA_TROCADA"
    REEMBOLSO_CARTEIRA = "REEMBOLSO_CARTEIRA"
    MANUAL = "MANUAL"

class TipoMotivoTicket(str, enum.Enum):
    LOGIN_INVALIDO = "LOGIN_INVALIDO"
    SEM_ASSINATURA = "SEM_ASSINATURA"
    CONTA_CAIU = "CONTA_CAIU"
    OUTRO = "OUTRO"

# --- Classe Base ---
# (Não precisamos de uma classe base customizada com SQLModel,
# podemos usar o SQLModel diretamente. Este arquivo
# servirá para guardar nossos ENUMs e tipos compartilhados.)