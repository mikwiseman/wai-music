from __future__ import annotations

from pathlib import Path

from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyHttpUrl
from starlette.testclient import TestClient

from wai_music.server import build_web_app
from wai_music.services import create_services
from wai_music.settings import WaiMusicSettings


def _hosted_settings(tmp_path: Path) -> WaiMusicSettings:
    return WaiMusicSettings.model_validate(
        {
            "WAI_MUSIC_DB_PATH": str(tmp_path / "cache.sqlite"),
            "SPOTIFY_CACHE_PATH": str(tmp_path / "spotify.json"),
            "WAI_MUSIC_PLAYLISTS_DIR": str(tmp_path / "playlists"),
            "WAI_MUSIC_PUBLIC_BASE_URL": "http://localhost:8765",
            "WAI_MUSIC_SECRET_KEY": "integration-test-secret",
        }
    )


def test_hosted_web_dashboard_and_healthz(tmp_path: Path) -> None:
    settings = _hosted_settings(tmp_path)
    services = create_services(settings)
    app = build_web_app(services, settings=settings)

    with TestClient(app) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["oauth_enabled"] is True

        sign_up = client.post(
            "/sign-up",
            data={"email": "user@example.com", "password": "correct horse battery staple"},
            follow_redirects=False,
        )
        assert sign_up.status_code == 303
        dashboard = client.get("/dashboard")
        assert dashboard.status_code == 200
        assert "user@example.com" in dashboard.text
        assert "http://localhost:8765/mcp" in dashboard.text
        assert "No API key or manual token is required" in dashboard.text


def test_oauth_approval_page_round_trip(tmp_path: Path) -> None:
    settings = _hosted_settings(tmp_path)
    services = create_services(settings)
    app = build_web_app(services, settings=settings)

    user = services.auth_store.create_user(
        email="user@example.com",
        password="correct horse battery staple",
    )
    session_token = services.auth_store.create_session(
        user_id=user.user_id,
        ttl_seconds=settings.session_ttl_seconds,
    )

    services.auth_store.save_oauth_client(
        OAuthClientInformationFull(
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
    )
    request_id = services.auth_store.create_pending_authorization(
        client_id="client-1",
        params=AuthorizationParams(
            state="state-1",
            scopes=["mcp:tools"],
            code_challenge="challenge",
            redirect_uri=AnyHttpUrl("https://claude.ai/api/mcp/auth_callback"),
            redirect_uri_provided_explicitly=True,
            resource="http://localhost:8765/mcp",
        ),
        ttl_seconds=settings.oauth_auth_request_ttl_seconds,
    )

    with TestClient(app) as client:
        client.cookies.set(settings.session_cookie_name, session_token)
        response = client.get(f"/oauth/approval?request_id={request_id}")
        assert response.status_code == 200
        assert "Authorize Claude" in response.text

        approved = client.post(
            "/oauth/approval",
            data={"request_id": request_id},
            follow_redirects=False,
        )
        assert approved.status_code == 303
        location = approved.headers["location"]
        assert location.startswith("https://claude.ai/api/mcp/auth_callback?code=")
        code = location.split("code=", maxsplit=1)[1].split("&", maxsplit=1)[0]
        auth_code = services.auth_store.get_authorization_code_payload(code)
        assert auth_code is not None
        assert auth_code["user_id"] == user.user_id
