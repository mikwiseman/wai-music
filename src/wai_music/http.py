"""Shared async HTTP helpers."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx


class JsonHttpClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client = client or httpx.AsyncClient(
            base_url=base_url or "",
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
        )
        self._owns_client = client is None

    @property
    def base_url(self) -> str:
        return str(self._client.base_url)

    async def request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        retries: int = 3,
    ) -> dict[str, Any]:
        for attempt in range(retries + 1):
            response = await self._client.request(method, url, params=params, headers=headers)
            if response.status_code not in {429, 503}:
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("expected JSON object response")
                return payload
            if attempt == retries:
                response.raise_for_status()
            await asyncio.sleep(0.5 * (2**attempt))
        raise RuntimeError("unreachable")

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
