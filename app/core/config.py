from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Carrega e valida as variáveis de ambiente do arquivo .env
    """

    DATABASE_URL: str
    JWT_SECRET_KEY: str
    AES_ENCRYPTION_KEY: str

    # CELERY_BROKER_URL: str

    BOT_API_KEY: str
    TELEGRAM_BOT_TOKEN: str

    PAYMENT_PROVIDER: str = "MERCADOPAGO"
    MERCADOPAGO_ACCESS_TOKEN: Optional[str] = None

    ASAAS_ACCESS_TOKEN: Optional[str] = None
    ASAAS_API_BASE_URL: str = "https://api.asaas.com/v3"
    ASAAS_WEBHOOK_AUTH_TOKEN: Optional[str] = None
    ASAAS_WEBHOOK_BASE_URL: str = "http://api.ferreirastreamings.com.br"
    ASAAS_WEBHOOK_PATH: str = "/api/v1/webhook/recarga"
    ASAAS_REQUEST_TIMEOUT_SECONDS: int = 30
    ASAAS_USER_AGENT: str = "FerreiraStreamings/1.0"

    IMAP_SYNC_WORKER_ENABLED: bool = True
    IMAP_SYNC_INTERVAL_SECONDS: int = 300
    EMAIL_MONITOR_IMAP_TIMEOUT_SECONDS: int = 20
    EMAIL_MONITOR_MAX_BODY_CHARS: int = 20000
    EMAIL_MONITOR_SYNC_BATCH_SIZE: int = 100
    EMAIL_MONITOR_WEBHOOK_TIMEOUT_SECONDS: int = 5

    RECARGA_EXPIRACAO_MINUTOS: int = 30

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
