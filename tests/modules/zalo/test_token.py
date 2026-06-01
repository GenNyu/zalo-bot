import httpx
import pytest
import respx

from zalo_bot.modules.zalo.token import TokenManager


class FakeRedis:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value

    def lock(self, *_a, **_k):
        class _L:
            async def __aenter__(self_):
                return self_
            async def __aexit__(self_, *exc):
                return False
        return _L()


@pytest.mark.asyncio
@respx.mock
async def test_returns_cached_token_without_refresh():
    redis = FakeRedis()
    redis.store["zalo:access_token"] = "cached-token"
    tm = TokenManager(
        redis=redis, token_url="https://oauth.local/token",
        app_id="app", app_secret="sec", refresh_token="ref",
    )
    assert await tm.get_access_token() == "cached-token"


@pytest.mark.asyncio
@respx.mock
async def test_refreshes_when_missing():
    redis = FakeRedis()
    route = respx.post("https://oauth.local/token").mock(
        return_value=httpx.Response(
            200, json={"access_token": "new-token", "refresh_token": "r2", "expires_in": "90000"}
        )
    )
    tm = TokenManager(
        redis=redis, token_url="https://oauth.local/token",
        app_id="app", app_secret="sec", refresh_token="ref",
    )
    token = await tm.get_access_token()
    assert token == "new-token"
    assert route.called
    assert redis.store["zalo:access_token"] == "new-token"


@pytest.mark.asyncio
@respx.mock
async def test_force_refresh_ignores_cache():
    redis = FakeRedis()
    redis.store["zalo:access_token"] = "old"
    respx.post("https://oauth.local/token").mock(
        return_value=httpx.Response(
            200, json={"access_token": "fresh", "refresh_token": "r2", "expires_in": "90000"}
        )
    )
    tm = TokenManager(
        redis=redis, token_url="https://oauth.local/token",
        app_id="app", app_secret="sec", refresh_token="ref",
    )
    assert await tm.get_access_token(force_refresh=True) == "fresh"
