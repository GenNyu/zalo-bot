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


@pytest.mark.asyncio
@respx.mock
async def test_chat_uses_separate_base_url_and_key_when_provided():
    """URbox gives per-model keys: embed key can't call chat model and vice versa.
    LlmGateway must route embed -> (base_url, api_key) and chat ->
    (chat_base_url, chat_api_key) independently."""
    embed_route = respx.post("http://embed.local/v1/embeddings").mock(
        return_value=httpx.Response(200, json={"data": [{"embedding": [0.5]}]})
    )
    chat_route = respx.post("http://chat.local/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": "hi"}}]}
        )
    )
    gw = LlmGateway(
        base_url="http://embed.local/v1", api_key="embed-key",
        chat_base_url="http://chat.local/v1", chat_api_key="chat-key",
        embedding_model="e", chat_model="c", timeout=5,
    )

    assert await gw.embed("x") == [0.5]
    assert await gw.chat([{"role": "user", "content": "x"}]) == "hi"

    # Each route was hit exactly once with the right authorization header.
    assert embed_route.call_count == 1
    assert chat_route.call_count == 1
    assert embed_route.calls.last.request.headers["authorization"] == "Bearer embed-key"
    assert chat_route.calls.last.request.headers["authorization"] == "Bearer chat-key"


@pytest.mark.asyncio
@respx.mock
async def test_chat_falls_back_to_base_url_when_chat_url_not_provided():
    """Backward compat: existing single-key setups still work."""
    respx.post("http://gw.local/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}}]}
        )
    )
    gw = LlmGateway(
        base_url="http://gw.local/v1", api_key="k",
        embedding_model="e", chat_model="c", timeout=5,
    )
    assert await gw.chat([{"role": "user", "content": "x"}]) == "ok"
