from typing import Any

import httpx

_TOKEN_KEY = "zalo:access_token"
_REFRESH_KEY = "zalo:refresh_token"
_LOCK_KEY = "zalo:token:lock"
# Refresh a bit before the ~25h expiry; subtract a 1h safety margin from expires_in.
_SAFETY_MARGIN_SECONDS = 3600


class TokenManager:
    def __init__(
        self, *, redis: Any, token_url: str, app_id: str, app_secret: str, refresh_token: str
    ) -> None:
        self._redis = redis
        self._token_url = token_url
        self._app_id = app_id
        self._app_secret = app_secret
        self._fallback_refresh_token = refresh_token

    async def get_access_token(self, *, force_refresh: bool = False) -> str:
        if not force_refresh:
            cached = await self._redis.get(_TOKEN_KEY)
            if cached:
                return cached.decode() if isinstance(cached, bytes) else cached
        return await self._refresh(skip_cache=force_refresh)

    async def _refresh(self, *, skip_cache: bool = False) -> str:
        async with self._redis.lock(_LOCK_KEY, timeout=30):
            if not skip_cache:
                cached = await self._redis.get(_TOKEN_KEY)
                if cached:
                    return cached.decode() if isinstance(cached, bytes) else cached
            stored_refresh = await self._redis.get(_REFRESH_KEY)
            refresh_token = (
                stored_refresh.decode() if isinstance(stored_refresh, bytes) else stored_refresh
            ) or self._fallback_refresh_token

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    self._token_url,
                    headers={"secret_key": self._app_secret},
                    data={
                        "app_id": self._app_id,
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                    },
                )
                resp.raise_for_status()
                payload = resp.json()

            access_token = payload["access_token"]
            ttl = max(int(payload.get("expires_in", "90000")) - _SAFETY_MARGIN_SECONDS, 60)
            await self._redis.set(_TOKEN_KEY, access_token, ex=ttl)
            if payload.get("refresh_token"):
                await self._redis.set(_REFRESH_KEY, payload["refresh_token"])
            return access_token
