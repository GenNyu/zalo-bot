from zalo_bot.modules.opensearch.search import SearchHit
from zalo_bot.modules.rag.prompt import FALLBACK_ANSWER, build_messages


def _hit(text):
    return SearchHit(id="x", score=1.0, source={"text": text})


def test_build_messages_includes_context_and_question():
    msgs = build_messages("Giá bao nhiêu?", [_hit("Sản phẩm A giá 100k")], max_context_chars=1000)
    assert msgs[0]["role"] == "system"
    assert "Giá bao nhiêu?" in msgs[1]["content"]
    assert "Sản phẩm A giá 100k" in msgs[1]["content"]


def test_context_is_truncated_to_limit():
    long_hit = _hit("x" * 5000)
    msgs = build_messages("q", [long_hit], max_context_chars=100)
    assert len(msgs[1]["content"]) < 400  # context portion bounded


def test_fallback_constant_exists():
    assert "chưa có thông tin" in FALLBACK_ANSWER.lower()
