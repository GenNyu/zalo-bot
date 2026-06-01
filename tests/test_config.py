import pytest
from pydantic import ValidationError

from zalo_bot.config.settings import Settings, get_settings


def test_settings_load_from_env():
    s = get_settings()
    assert s.opensearch_index_pattern == "open_webui_file-*"
    assert s.opensearch_top_k == 5
    assert s.llm_embedding_model == "embed-model"
    assert s.external_call_timeout_seconds == 30


def test_missing_required_field_raises(monkeypatch):
    monkeypatch.delenv("ZALO_OA_SECRET", raising=False)
    with pytest.raises(ValidationError):
        Settings()
