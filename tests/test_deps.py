from unittest.mock import MagicMock, patch

from zalo_bot.deps import build_rag, build_redis


def test_build_redis_returns_client():
    r = build_redis()
    assert r is not None


@patch("zalo_bot.deps.build_gateway")
@patch("zalo_bot.deps.build_retriever")
def test_build_rag_returns_orchestrator(mock_retriever, mock_gateway):
    # Mock the dependencies
    mock_gateway.return_value = MagicMock()
    mock_retriever.return_value = MagicMock()

    rag = build_rag()
    assert hasattr(rag, "answer_question")
