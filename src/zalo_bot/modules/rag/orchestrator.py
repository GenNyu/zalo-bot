from typing import Any

from zalo_bot.modules.rag.prompt import FALLBACK_ANSWER, build_messages


class RagOrchestrator:
    def __init__(
        self, *, gateway: Any, retriever: Any, top_k: int, max_context_chars: int
    ) -> None:
        self._gateway = gateway
        self._retriever = retriever
        self._top_k = top_k
        self._max_context_chars = max_context_chars

    async def answer_question(self, question: str) -> str:
        vector = await self._gateway.embed(question)
        hits = await self._retriever.hybrid_search(question, vector, top_k=self._top_k)
        if not hits:
            return FALLBACK_ANSWER
        messages = build_messages(question, hits, max_context_chars=self._max_context_chars)
        answer = await self._gateway.chat(messages)
        return answer or FALLBACK_ANSWER
