from typing import cast

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam


class LlmGateway:
    """OpenAI-compatible gateway with optional per-purpose endpoints.

    Some gateways (e.g. URbox) issue per-model API keys: one key for embeddings,
    another for chat. To accommodate that, embed and chat each get their own
    underlying client. When `chat_base_url` / `chat_api_key` are omitted they
    fall back to `base_url` / `api_key` so single-key setups still work.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        embedding_model: str,
        chat_model: str,
        timeout: int = 30,
        chat_base_url: str | None = None,
        chat_api_key: str | None = None,
    ) -> None:
        self._embed_client = AsyncOpenAI(
            base_url=base_url, api_key=api_key, timeout=timeout, max_retries=2
        )
        self._chat_client = AsyncOpenAI(
            base_url=chat_base_url or base_url,
            api_key=chat_api_key or api_key,
            timeout=timeout,
            max_retries=2,
        )
        self._embedding_model = embedding_model
        self._chat_model = chat_model

    async def embed(self, text: str) -> list[float]:
        resp = await self._embed_client.embeddings.create(
            model=self._embedding_model, input=text
        )
        return list(resp.data[0].embedding)

    async def chat(self, messages: list[dict], *, temperature: float = 0.2) -> str:
        resp = await self._chat_client.chat.completions.create(
            model=self._chat_model,
            messages=cast("list[ChatCompletionMessageParam]", messages),
            temperature=temperature,
        )
        return (resp.choices[0].message.content or "").strip()
