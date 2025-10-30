from sqlmodel import create_engine, Session
from app.core.config import settings

# 1. Criar a "Engine" do Banco de Dados
# Esta é a conexão central com o seu PostgreSQL.
# Usamos a DATABASE_URL que o 'settings' leu do .env
#
# echo=True: Faz o SQLModel logar todas as queries SQL no console.
# Isso é INCRÍVEL para debug em desenvolvimento.
engine = create_engine(settings.DATABASE_URL, echo=True)


# 2. Definir a Função de "Gerador de Sessão"
def get_session():
    """
    Esta função é um "Gerador" (yield) que será usado pelo FastAPI
    para injetar uma sessão de banco de dados em cada endpoint.
    """
    
    # O 'with' é a parte mais importante:
    # 1. Ele abre uma nova Sessão (uma "conversa" com o banco)
    # 2. O 'yield session' entrega essa sessão para o endpoint
    # 3. QUANDO o endpoint termina (com sucesso ou com erro),
    #    o 'with' automaticamente "commita" (se sucesso) ou
    #    "dá rollback" (se erro) e FECHA a sessão.
    #
    # Isso previne vazamento de conexões.
    with Session(engine) as session:
        yield session