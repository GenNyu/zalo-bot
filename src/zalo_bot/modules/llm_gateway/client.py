from typing import cast

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam


class LlmGateway:
    def __init__(
        self, *, base_url: str, api_key: str, embedding_model: str, chat_model: str,
        timeout: int = 30,
    ) -> None:
        self._client = AsyncOpenAI(
            base_url=base_url, api_key=api_key, timeout=timeout, max_retries=2
        )
        self._embedding_model = embedding_model
        self._chat_model = chat_model

    async def embed(self, text: str) -> list[float]:
        resp = await self._client.embeddings.create(model=self._embedding_model, input=text)
        return list(resp.data[0].embedding)

    async def chat(self, messages: list[dict], *, temperature: float = 0.2) -> str:
        resp = await self._client.chat.completions.create(
            model=self._chat_model,
            messages=cast("list[ChatCompletionMessageParam]", messages),
            temperature=temperature,
        )
        return (resp.choices[0].message.content or "").strip()
