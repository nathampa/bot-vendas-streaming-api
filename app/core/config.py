from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """
    Carrega e valida as variáveis de ambiente do arquivo .env
    """
    
    # URL de conexão com o banco de dados (lida do .env)
    DATABASE_URL: str
    
    # Chave secreta para assinar os tokens JWT (lida do .env)
    JWT_SECRET_KEY: str
    
    # Chave para criptografar as senhas (lida do .env)
    AES_ENCRYPTION_KEY: str

    CELERY_BROKER_URL: str

    BOT_API_KEY: str

    # Configuração para dizer ao Pydantic para ler do arquivo .env
    model_config = SettingsConfigDict(env_file=".env")


# Criamos uma instância única que será importada em todo o projeto
settings = Settings()

# Se alguma variável (ex: DATABASE_URL) não for encontrada no .env,
# o programa vai falhar AQUI na inicialização, o que é ótimo.
# Isso nos avisa que o .env está configurado errado, antes de dar erro na API.