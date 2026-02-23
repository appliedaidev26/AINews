from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://ainews:ainews@localhost:5432/ainews"
    database_url_sync: str = "postgresql://ainews:ainews@localhost:5432/ainews"

    # Firebase Auth
    firebase_project_id: str = ""
    google_application_credentials: str = ""  # path to service account JSON

    # Anthropic
    anthropic_api_key: str = ""

    # OpenAI
    openai_api_key: str = ""

    # Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_pro_model: str = "gemini-2.5-pro"

    # Reddit API
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "ainews/1.0"

    # HN
    hn_min_score: int = 50

    # Arxiv
    arxiv_max_results: int = 30
    arxiv_min_relevance: float = 0.6

    # Dedup
    dedup_similarity_threshold: float = 0.85

    # Enrichment
    enrichment_batch_size: int = 10
    enrichment_rate_rpm: int = 150   # 2.5 req/s

    # Pipeline
    pipeline_concurrency: int = 2    # max dates processed in parallel

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]
    cors_extra_origins: str = ""  # comma-separated extra origins, e.g. "https://app.web.app"

    # Admin
    admin_api_key: str = ""  # set ADMIN_API_KEY env var; empty = endpoint disabled

    # Env
    environment: str = "development"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
