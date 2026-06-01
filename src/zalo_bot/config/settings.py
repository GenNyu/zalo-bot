from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    zalo_oa_secret: str
    zalo_app_id: str
    zalo_refresh_token: str
    zalo_app_secret: str
    zalo_send_api_url: str = "https://openapi.zalo.me/v3.0/oa/message"
    zalo_token_api_url: str = "https://oauth.zaloapp.com/v4/oa/access_token"

    redis_url: str = "redis://localhost:6379/0"

    opensearch_url: str
    opensearch_user: str = ""
    opensearch_password: str = ""
    opensearch_index_pattern: str = "open_webui_file-*"
    opensearch_search_pipeline: str = ""
    opensearch_text_field: str = "text"
    opensearch_vector_field: str = "vector"
    opensearch_top_k: int = 5
    opensearch_min_score: float = 0.0

    llm_gateway_base_url: str
    llm_gateway_api_key: str
    llm_embedding_model: str
    llm_chat_model: str
    # Optional: separate endpoint/key for chat when the provider issues
    # per-model keys (e.g. URbox). Fall back to llm_gateway_* if unset.
    llm_chat_base_url: str = ""
    llm_chat_api_key: str = ""

    rag_max_context_chars: int = 6000
    external_call_timeout_seconds: int = 30
    log_level: str = "INFO"
    log_question_text: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
