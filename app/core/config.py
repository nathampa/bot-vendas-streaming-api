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
    MERCADOPAGO_ACCESS_TOKEN: str
    TELEGRAM_BOT_TOKEN: str

    IMAP_SYNC_WORKER_ENABLED: bool = True
    IMAP_SYNC_INTERVAL_SECONDS: int = 300
    EMAIL_MONITOR_IMAP_TIMEOUT_SECONDS: int = 20
    EMAIL_MONITOR_MAX_BODY_CHARS: int = 20000
    EMAIL_MONITOR_SYNC_BATCH_SIZE: int = 100
    EMAIL_MONITOR_WEBHOOK_TIMEOUT_SECONDS: int = 5

    RECARGA_EXPIRACAO_MINUTOS: int = 30

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
