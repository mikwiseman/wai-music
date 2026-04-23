"""Spotify OAuth helpers for hosted multi-user flows."""

from __future__ import annotations

import base64
import time
from urllib.parse import urlencode

import httpx

from wai_music.settings import WaiMusicSettings

SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE_URL = "https://api.spotify.com/v1"


def build_authorize_url(settings: WaiMusicSettings, *, state: str) -> str:
    query = urlencode(
        {
            "client_id": settings.spotify_client_id,
            "response_type": "code",
            "redirect_uri": settings.effective_spotify_redirect_uri,
            "scope": " ".join(settings.spotify_scopes),
            "state": state,
        }
    )
    return f"{SPOTIFY_AUTH_URL}?{query}"


async def exchange_code(settings: WaiMusicSettings, *, code: str) -> dict[str, object]:
    return await _token_request(
        settings,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.effective_spotify_redirect_uri,
        },
    )


async def refresh_access_token(
    settings: WaiMusicSettings,
    *,
    refresh_token: str,
) -> dict[str, object]:
    return await _token_request(
        settings,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
    )


async def current_user_profile(access_token: str, *, request_timeout: float) -> dict[str, object]:
    async with httpx.AsyncClient(
        base_url=SPOTIFY_API_BASE_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=request_timeout,
    ) as client:
        response = await client.get("/me")
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Spotify profile response must be a JSON object")
        return payload


async def _token_request(
    settings: WaiMusicSettings,
    *,
    data: dict[str, str],
) -> dict[str, object]:
    if not settings.spotify_client_id or not settings.spotify_client_secret:
        raise RuntimeError("Spotify credentials are not configured")
    basic = base64.b64encode(
        f"{settings.spotify_client_id}:{settings.spotify_client_secret}".encode()
    ).decode("ascii")
    async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
        response = await client.post(
            SPOTIFY_TOKEN_URL,
            data=data,
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Spotify token response must be a JSON object")
    expires_in = payload.get("expires_in")
    if isinstance(expires_in, int):
        payload["expires_at"] = int(time.time()) + expires_in
    return payload
