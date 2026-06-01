import httpx
import pytest
import respx

from zalo_bot.modules.zalo.client import ZaloClient


class _Tokens:
    def __init__(self):
        self.calls = []

    async def get_access_token(self, *, force_refresh: bool = False):
        self.calls.append(force_refresh)
        return "tok-refreshed" if force_refresh else "tok"


@pytest.mark.asyncio
@respx.mock
async def test_send_text_ok():
    route = respx.post("https://send.local/msg").mock(
        return_value=httpx.Response(200, json={"error": 0, "message": "Success"})
    )
    client = ZaloClient(send_url="https://send.local/msg", tokens=_Tokens(), timeout=5)
    await client.send_text_message("u1", "hello")
    assert route.called
    sent = route.calls[0].request
    assert sent.headers["access_token"] == "tok"


@pytest.mark.asyncio
@respx.mock
async def test_send_text_refreshes_on_token_error():
    respx.post("https://send.local/msg").mock(
        side_effect=[
            httpx.Response(200, json={"error": -216, "message": "access token expired"}),
            httpx.Response(200, json={"error": 0, "message": "Success"}),
        ]
    )
    tokens = _Tokens()
    client = ZaloClient(send_url="https://send.local/msg", tokens=tokens, timeout=5)
    await client.send_text_message("u1", "hi")
    assert tokens.calls == [False, True]  # second attempt forced a refresh
