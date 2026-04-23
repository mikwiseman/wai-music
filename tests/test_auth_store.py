from __future__ import annotations

from pathlib import Path

from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyHttpUrl

from wai_music.auth.store import SQLiteAuthStore


def test_auth_store_round_trip(tmp_path: Path) -> None:
    store = SQLiteAuthStore(tmp_path / "auth.sqlite", secret_key="test-secret-key")

    user = store.create_user(email="alice@example.com", password="correct horse battery staple")
    session_token = store.create_session(user_id=user.user_id, ttl_seconds=3600)
    session = store.get_session(session_token)

    assert store.authenticate_user(
        email="alice@example.com",
        password="correct horse battery staple",
    ) == user
    assert session is not None
    assert session.user_id == user.user_id


def test_auth_store_oauth_and_spotify_storage(tmp_path: Path) -> None:
    store = SQLiteAuthStore(tmp_path / "auth.sqlite", secret_key="test-secret-key")
    user = store.create_user(email="bob@example.com", password="correct horse battery staple")

    store.upsert_spotify_connection(
        user_id=user.user_id,
        spotify_user_id="spotify-user-1",
        token_payload={
            "access_token": "access-1",
            "refresh_token": "refresh-1",
            "scope": "user-top-read",
            "expires_at": 9999999999,
        },
    )
    spotify = store.get_spotify_connection(user.user_id)

    client = OAuthClientInformationFull(
        client_id="client-1",
        client_id_issued_at=1,
        client_secret="secret-1",
        client_secret_expires_at=None,
        redirect_uris=[AnyHttpUrl("https://claude.ai/api/mcp/auth_callback")],
        token_endpoint_auth_method="client_secret_post",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        client_name="Claude",
        scope="mcp:tools",
    )
    store.save_oauth_client(client)
    pending_id = store.create_pending_authorization(
        client_id="client-1",
        params=AuthorizationParams(
            state="state-1",
            scopes=["mcp:tools"],
            code_challenge="challenge",
            redirect_uri=AnyHttpUrl("https://claude.ai/api/mcp/auth_callback"),
            redirect_uri_provided_explicitly=True,
            resource="https://music.example.com/mcp",
        ),
        ttl_seconds=300,
    )
    pending = store.get_pending_authorization(pending_id)
    assert spotify is not None
    assert spotify.token_payload["refresh_token"] == "refresh-1"
    assert pending is not None
    assert pending.client_id == "client-1"

    code = store.create_authorization_code(user_id=user.user_id, request=pending, ttl_seconds=300)
    auth_payload = store.get_authorization_code_payload(code)
    assert auth_payload is not None
    assert auth_payload["user_id"] == user.user_id

    token_pair = store.issue_oauth_token_pair(
        user_id=user.user_id,
        client_id="client-1",
        scopes=["mcp:tools"],
        access_ttl_seconds=3600,
        refresh_ttl_seconds=7200,
        resource="https://music.example.com/mcp",
    )
    access_payload = store.get_access_token_payload(token_pair.access_token)
    refresh_payload = store.get_refresh_token_payload(token_pair.refresh_token or "")

    assert access_payload is not None
    assert access_payload["user_id"] == user.user_id
    assert refresh_payload is not None
    assert refresh_payload["client_id"] == "client-1"
