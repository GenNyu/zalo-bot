import httpx
import pytest
import respx

from zalo_bot.modules.llm_gateway.client import LlmGateway


@pytest.mark.asyncio
@respx.mock
async def test_embed_returns_vector():
    respx.post("http://gw.local/v1/embeddings").mock(
        return_value=httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2, 0.3]}]})
    )
    gw = LlmGateway(
        base_url="http://gw.local/v1", api_key="k",
        embedding_model="e", chat_model="c", timeout=5,
    )
    assert await gw.embed("hello") == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
@respx.mock
async def test_chat_returns_text():
    respx.post("http://gw.local/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": "câu trả lời"}}]}
        )
    )
    gw = LlmGateway(
        base_url="http://gw.local/v1", api_key="k",
        embedding_model="e", chat_model="c", timeout=5,
    )
    out = await gw.chat([{"role": "user", "content": "hi"}])
    assert out == "câu trả lời"
