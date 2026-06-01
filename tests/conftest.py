import pytest

# Provide deterministic env so config.Settings loads in unit tests.
_TEST_ENV = {
    "ZALO_OA_SECRET": "secret",
    "ZALO_APP_ID": "appid",
    "ZALO_REFRESH_TOKEN": "refresh",
    "ZALO_APP_SECRET": "appsecret",
    "REDIS_URL": "redis://localhost:6379/0",
    "OPENSEARCH_URL": "http://localhost:9200",
    "OPENSEARCH_INDEX_PATTERN": "open_webui_file-*",
    "OPENSEARCH_TEXT_FIELD": "text",
    "OPENSEARCH_VECTOR_FIELD": "vector",
    "LLM_GATEWAY_BASE_URL": "http://gateway.local/v1",
    "LLM_GATEWAY_API_KEY": "key",
    "LLM_EMBEDDING_MODEL": "embed-model",
    "LLM_CHAT_MODEL": "chat-model",
}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k, v in _TEST_ENV.items():
        monkeypatch.setenv(k, v)
