from zalo_bot.deps import build_rag, build_redis


def test_build_rag_returns_orchestrator():
    rag = build_rag()
    assert hasattr(rag, "answer_question")


def test_build_redis_returns_client():
    r = build_redis()
    assert r is not None
