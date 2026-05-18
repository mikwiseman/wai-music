from __future__ import annotations

from pathlib import Path

import pytest
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyHttpUrl

from wai_music.auth.oauth import WaiOAuthProvider
from wai_music.auth.store import SQLiteAuthStore
from wai_music.settings import WaiMusicSettings


def _client() -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id="client-1",
        client_id_issued_at=1,
        client_secret="secret-1",
        client_secret_expires_at=None,
        redirect_uris=[AnyHttpUrl("http://127.0.0.1:12345/callback")],
        token_endpoint_auth_method="client_secret_post",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        client_name="Codex",
        scope="mcp:tools",
    )


@pytest.mark.asyncio
async def test_refresh_exchange_keeps_previous_refresh_token_usable(tmp_path: Path) -> None:
    store = SQLiteAuthStore(tmp_path / "auth.sqlite", secret_key="test-secret-key")
    user = store.create_user(email="codex@example.com", password="correct horse battery staple")
    client = _client()
    settings = WaiMusicSettings(WAI_MUSIC_PUBLIC_BASE_URL="https://music.example.com")
    provider = WaiOAuthProvider(store=store, settings=settings)

    original = store.issue_oauth_token_pair(
        user_id=user.user_id,
        client_id=client.client_id or "",
        scopes=["mcp:tools"],
        access_ttl_seconds=3600,
        refresh_ttl_seconds=7200,
        resource="https://music.example.com/mcp",
    )

    loaded = await provider.load_refresh_token(client, original.refresh_token or "")
    assert loaded is not None
    refreshed = await provider.exchange_refresh_token(client, loaded, ["mcp:tools"])

    assert refreshed.refresh_token is not None
    assert refreshed.refresh_token != original.refresh_token
    assert store.get_refresh_token_payload(original.refresh_token or "") is not None

    loaded_again = await provider.load_refresh_token(client, original.refresh_token or "")
    assert loaded_again is not None
    refreshed_again = await provider.exchange_refresh_token(client, loaded_again, ["mcp:tools"])

    assert refreshed_again.refresh_token is not None
    refreshed_payload = store.get_access_token_payload(refreshed_again.access_token)
    assert refreshed_payload is not None
    assert refreshed_payload["resource"] == "https://music.example.com/mcp"
