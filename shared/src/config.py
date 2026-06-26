"""GrindVacPro — Application configuration via Pydantic Settings v2."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated application settings loaded from environment / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    database_url: str
    redis_url: str
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model_name: str = "gpt-4o-mini"
    resume_path: str = "./shared/resume.txt"
    telegram_bot_token: str = ""
    telegram_user_id: int = 0
    ai_score_threshold: int = 50
    similarity_threshold: float = 0.70


def load_resume(path: str | None = None) -> str:
    """Load resume text from an external file.

    Args:
        path: Absolute path to the resume file. Defaults to ``resume_path``
            from the application settings.

    Returns:
        The resume text content.

    Raises:
        FileNotFoundError: If the resume file does not exist.
    """
    file_path = Path(path) if path else Path(settings.resume_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Resume file not found: {file_path}")
    return file_path.read_text(encoding="utf-8")


settings = Settings()
