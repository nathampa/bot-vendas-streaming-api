from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Carrega e valida as variáveis de ambiente do arquivo .env
    """

    DATABASE_URL: str
    JWT_SECRET_KEY: str
    AES_ENCRYPTION_KEY: str
    CELERY_BROKER_URL: str | None = None

    BOT_API_KEY: str
    MERCADOPAGO_ACCESS_TOKEN: str
    TELEGRAM_BOT_TOKEN: str
    ADMIN_TELEGRAM_ID: int | None = 1792589341

    IMAP_SYNC_WORKER_ENABLED: bool = True
    IMAP_SYNC_INTERVAL_SECONDS: int = 300
    EMAIL_MONITOR_IMAP_TIMEOUT_SECONDS: int = 20
    EMAIL_MONITOR_MAX_BODY_CHARS: int = 20000
    EMAIL_MONITOR_SYNC_BATCH_SIZE: int = 100
    EMAIL_MONITOR_WEBHOOK_TIMEOUT_SECONDS: int = 5
    OPENAI_INVITE_AUTOMATION_ENABLED: bool = True
    OPENAI_INVITE_BASE_URL: str = "https://chatgpt.com"
    OPENAI_INVITE_MEMBERS_URL: str = "https://chatgpt.com/admin"
    OPENAI_INVITE_SESSION_ROOT: str = "/opt/bot-vendas/runtime/openai-invite-sessions"
    OPENAI_INVITE_EVIDENCE_ROOT: str = "/opt/bot-vendas/runtime/openai-invite-evidence"
    OPENAI_INVITE_HOST_RUNNER_ENABLED: bool = True
    OPENAI_INVITE_HOST_RUNNER_ROOT: str = "/opt/bot-vendas/runtime/openai-invite-host-runner"
    OPENAI_INVITE_HOST_RUNNER_TIMEOUT_SECONDS: int = 180
    OPENAI_INVITE_VIRTUAL_DISPLAY_ENABLED: bool = True
    OPENAI_INVITE_VIRTUAL_DISPLAY_WIDTH: int = 1440
    OPENAI_INVITE_VIRTUAL_DISPLAY_HEIGHT: int = 960
    OPENAI_INVITE_VIRTUAL_DISPLAY_COLOR_DEPTH: int = 24
    OPENAI_INVITE_XVFB_START_TIMEOUT_SECONDS: int = 5
    OPENAI_INVITE_HEADLESS: bool = True
    OPENAI_INVITE_PAGE_TIMEOUT_MS: int = 30000
    OPENAI_INVITE_OTP_TIMEOUT_SECONDS: int = 120
    OPENAI_INVITE_OTP_POLL_INTERVAL_SECONDS: int = 5
    OPENAI_INVITE_IMAP_FETCH_LIMIT: int = 20
    OPENAI_INVITE_RETRY_WINDOW_SECONDS: int = 14400
    OPENAI_INVITE_RETRY_COOLDOWNS_SECONDS: str = "300,600,900,1200,1800"
    OPENAI_INVITE_SESSION_RETENTION_DAYS: int = 30
    OPENAI_ACCOUNT_CREATION_ENABLED: bool = True
    OPENAI_ACCOUNT_CREATION_SIGNUP_URL: str = "https://chatgpt.com/auth/login"
    OPENAI_ACCOUNT_CREATION_SESSION_ROOT: str = "/opt/bot-vendas/runtime/openai-account-creation-sessions"
    OPENAI_ACCOUNT_CREATION_EVIDENCE_ROOT: str = "/opt/bot-vendas/runtime/openai-account-creation-evidence"
    OPENAI_ACCOUNT_CREATION_OUTLOOK_PROFILE_ROOT: str = "/opt/bot-vendas/runtime/outlook-otp-profiles"
    OPENAI_ACCOUNT_CREATION_RETRY_WINDOW_SECONDS: int = 14400
    OPENAI_ACCOUNT_CREATION_RETRY_COOLDOWNS_SECONDS: str = "300,600,900,1200,1800"
    OPENAI_ACCOUNT_CREATION_SEQUENCE_RETRY_SECONDS: int = 60
    OPENAI_WORKSPACE_MEMBER_WARNING_DAYS: int = 30
    OPENAI_WORKSPACE_MEMBER_GRACE_DAYS: int = 5

    RECARGA_EXPIRACAO_MINUTOS: int = 30

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
