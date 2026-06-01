from typing import Any, Protocol

import httpx

from zalo_bot.lib.errors import ExternalServiceError

_TOKEN_ERROR_CODES = {-216, -124}  # expired / invalid token


class TokenProvider(Protocol):
    async def get_access_token(self, *, force_refresh: bool = False) -> str: ...


class ZaloClient:
    def __init__(self, *, send_url: str, tokens: TokenProvider, timeout: int = 30) -> None:
        self._send_url = send_url
        self._tokens = tokens
        self._timeout = timeout

    async def send_text_message(self, user_id: str, text: str) -> None:
        if await self._post(user_id, text, force_refresh=False):
            return
        # One retry after a forced token refresh.
        if await self._post(user_id, text, force_refresh=True):
            return
        raise ExternalServiceError("zalo send failed after token refresh")

    async def _post(self, user_id: str, text: str, *, force_refresh: bool) -> bool:
        token = await self._tokens.get_access_token(force_refresh=force_refresh)
        body: dict[str, Any] = {
            "recipient": {"user_id": user_id},
            "message": {"text": text},
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(self._send_url, headers={"access_token": token}, json=body)
            resp.raise_for_status()
            data = resp.json()
        return data.get("error", 0) not in _TOKEN_ERROR_CODES
