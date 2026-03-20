"""Application settings loaded from environment variables via Pydantic."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Anthropic ---
    # Empty by default so the module can be imported without a .env file.
    # Scorer and CoverLetterGenerator will raise ConfigurationError at init
    # time if this is not set when AI features are actually needed.
    anthropic_api_key: str = Field("", description="Anthropic API key — required for AI features")
    anthropic_model: str = Field("claude-opus-4-6", description="Claude model for scoring and generation")

    # --- Gmail ---
    gmail_client_id: str = Field("", description="OAuth2 client ID")
    gmail_client_secret: str = Field("", description="OAuth2 client secret")
    gmail_refresh_token: str = Field("", description="OAuth2 refresh token")
    gmail_user_email: str = Field("", description="Gmail address used for sending/reading")

    # --- Telegram ---
    telegram_bot_token: str = Field("", description="Telegram bot token from @BotFather")
    telegram_chat_id: str = Field("", description="Your personal Telegram chat ID")

    # --- LinkedIn ---
    linkedin_email: str = Field("", description="LinkedIn account email for Playwright scraping")
    linkedin_password: str = Field("", description="LinkedIn account password")

    # --- Database ---
    database_url: str = Field("sqlite:///./jobhunter.db", description="SQLAlchemy database URL")

    # --- App behaviour ---
    log_level: str = Field("INFO", description="Logging level: DEBUG, INFO, WARNING, ERROR")
    dry_run: bool = Field(True, description="If true, never actually submit applications")
    max_applications_per_day: int = Field(10, ge=1, le=50, description="Daily application cap")
    min_match_score: int = Field(80, ge=0, le=100, description="Minimum AI match score to consider")

    @property
    def is_ai_configured(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def is_gmail_configured(self) -> bool:
        return bool(self.gmail_client_id and self.gmail_client_secret and self.gmail_refresh_token)

    @property
    def is_telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)


class ConfigurationError(RuntimeError):
    """Raised when a required credential or setting is missing at feature init time."""


settings = Settings()
