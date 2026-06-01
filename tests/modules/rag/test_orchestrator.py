import pytest

from zalo_bot.modules.opensearch.search import SearchHit
from zalo_bot.modules.rag.orchestrator import RagOrchestrator
from zalo_bot.modules.rag.prompt import FALLBACK_ANSWER


class _Gateway:
    def __init__(self, answer="đáp án"):
        self.answer = answer
        self.chat_called = False

    async def embed(self, text):
        return [0.1, 0.2]

    async def chat(self, messages, **kwargs):
        self.chat_called = True
        return self.answer


class _Retriever:
    def __init__(self, hits):
        self._hits = hits

    async def hybrid_search(self, text, vector, *, top_k):
        return self._hits


@pytest.mark.asyncio
async def test_answer_returns_llm_output_when_hits_exist():
    gw = _Gateway("đáp án từ context")
    rag = RagOrchestrator(
        gateway=gw, retriever=_Retriever([SearchHit("a", 0.9, "ctx")]),
        top_k=5, max_context_chars=1000,
    )
    out = await rag.answer_question("hỏi gì")
    assert out == "đáp án từ context"
    assert gw.chat_called is True


@pytest.mark.asyncio
async def test_answer_returns_fallback_without_calling_llm_when_no_hits():
    gw = _Gateway()
    rag = RagOrchestrator(
        gateway=gw, retriever=_Retriever([]), top_k=5, max_context_chars=1000
    )
    out = await rag.answer_question("hỏi gì")
    assert out == FALLBACK_ANSWER
    assert gw.chat_called is False
