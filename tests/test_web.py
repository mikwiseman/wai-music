from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyHttpUrl
from starlette.testclient import TestClient

from wai_music.server import build_web_app
from wai_music.services import create_services
from wai_music.settings import WaiMusicSettings


class FakeMagicLinkEmailSender:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    def send_magic_link(
        self,
        *,
        recipient_email: str,
        magic_link: str,
        expires_in_minutes: int,
    ) -> None:
        self.sent.append(
            {
                "recipient_email": recipient_email,
                "magic_link": magic_link,
                "expires_in_minutes": expires_in_minutes,
            }
        )


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


def _hosted_settings_with_pats(tmp_path: Path) -> WaiMusicSettings:
    settings = _hosted_settings(tmp_path)
    return settings.model_copy(update={"enable_personal_access_tokens": True})


def _sign_in_with_magic_link(
    client: TestClient,
    sender: FakeMagicLinkEmailSender,
    *,
    email: str = "user@example.com",
    next_path: str = "/dashboard",
) -> None:
    sent_count = len(sender.sent)
    request_link = client.post(
        "/sign-in",
        data={"email": email, "next": next_path},
    )
    assert request_link.status_code == 200
    assert "Check your email" in request_link.text
    assert len(sender.sent) == sent_count + 1

    magic_link = str(sender.sent[-1]["magic_link"])
    parsed = urlparse(magic_link)
    preview = client.get(f"{parsed.path}?{parsed.query}")
    assert preview.status_code == 200
    assert "Continue sign-in" in preview.text
    token = parse_qs(parsed.query)["token"][0]

    callback = client.post(
        parsed.path,
        data={"token": token},
        follow_redirects=False,
    )
    assert callback.status_code == 303
    assert callback.headers["location"] == next_path


def test_hosted_web_dashboard_and_healthz(tmp_path: Path) -> None:
    settings = _hosted_settings(tmp_path)
    services = create_services(settings)
    fake_sender = FakeMagicLinkEmailSender()
    services.magic_link_email_sender = fake_sender
    app = build_web_app(services, settings=settings)

    with TestClient(app) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["oauth_enabled"] is True

        _sign_in_with_magic_link(client, fake_sender)
        dashboard = client.get("/dashboard")
        assert dashboard.status_code == 200
        assert "user@example.com" in dashboard.text
        assert "http://localhost:8765/mcp" in dashboard.text
        assert "No API key or manual token is required" in dashboard.text
        assert "Find music" in dashboard.text
        assert "Generate token" not in dashboard.text


def test_sign_in_sends_magic_link_and_callback_sets_session(tmp_path: Path) -> None:
    settings = _hosted_settings(tmp_path)
    services = create_services(settings)
    fake_sender = FakeMagicLinkEmailSender()
    services.magic_link_email_sender = fake_sender
    app = build_web_app(services, settings=settings)

    with TestClient(app) as client:
        request_link = client.post(
            "/sign-in",
            data={"email": " User@Example.COM ", "next": "/find"},
        )
        assert request_link.status_code == 200
        assert "Check your email" in request_link.text
        assert len(fake_sender.sent) == 1
        assert fake_sender.sent[0]["recipient_email"] == "user@example.com"

        magic_link = str(fake_sender.sent[0]["magic_link"])
        parsed = urlparse(magic_link)
        preview = client.get(f"{parsed.path}?{parsed.query}")
        assert preview.status_code == 200
        assert "Continue sign-in" in preview.text
        token = parse_qs(parsed.query)["token"][0]
        callback = client.post(
            parsed.path,
            data={"token": token},
            follow_redirects=False,
        )
        assert callback.status_code == 303
        assert callback.headers["location"] == "/find"

        dashboard = client.get("/dashboard")
        assert dashboard.status_code == 200
        assert "user@example.com" in dashboard.text


def test_magic_link_callback_rejects_reuse(tmp_path: Path) -> None:
    settings = _hosted_settings(tmp_path)
    services = create_services(settings)
    fake_sender = FakeMagicLinkEmailSender()
    services.magic_link_email_sender = fake_sender
    app = build_web_app(services, settings=settings)

    with TestClient(app) as client:
        request_link = client.post("/sign-in", data={"email": "user@example.com"})
        assert request_link.status_code == 200

        magic_link = str(fake_sender.sent[0]["magic_link"])
        parsed = urlparse(magic_link)
        callback_path = f"{parsed.path}?{parsed.query}"
        token = parse_qs(parsed.query)["token"][0]
        assert client.get(callback_path).status_code == 200
        assert (
            client.post(parsed.path, data={"token": token}, follow_redirects=False).status_code
            == 303
        )
        reused = client.get(callback_path)

    assert reused.status_code == 400
    assert "expired or has already been used" in reused.text


def test_magic_link_rejects_external_next_path(tmp_path: Path) -> None:
    settings = _hosted_settings(tmp_path)
    services = create_services(settings)
    fake_sender = FakeMagicLinkEmailSender()
    services.magic_link_email_sender = fake_sender
    app = build_web_app(services, settings=settings)

    with TestClient(app) as client:
        request_link = client.post(
            "/sign-in",
            data={"email": "user@example.com", "next": "https://evil.example/path"},
        )
        assert request_link.status_code == 200

        magic_link = str(fake_sender.sent[0]["magic_link"])
        parsed = urlparse(magic_link)
        token = parse_qs(parsed.query)["token"][0]
        callback = client.post(
            parsed.path,
            data={"token": token},
            follow_redirects=False,
        )

    assert callback.status_code == 303
    assert callback.headers["location"] == "/dashboard"


def test_find_route_requires_session(tmp_path: Path) -> None:
    settings = _hosted_settings(tmp_path)
    services = create_services(settings)
    app = build_web_app(services, settings=settings)

    with TestClient(app) as client:
        response = client.get("/find", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/sign-in?next=/find"


def test_find_page_disconnected_state_and_generated_prompt(tmp_path: Path) -> None:
    settings = _hosted_settings(tmp_path)
    services = create_services(settings)
    fake_sender = FakeMagicLinkEmailSender()
    services.magic_link_email_sender = fake_sender
    app = build_web_app(services, settings=settings)

    with TestClient(app) as client:
        _sign_in_with_magic_link(client, fake_sender)

        page = client.get("/find")
        assert page.status_code == 200
        assert "Connect Spotify to use your listening profile" in page.text
        assert "Use this with Claude after connecting wai-music" in page.text

        generated = client.post(
            "/find",
            data={
                "intent": "playlist",
                "source": "curated",
                "mood": "reflective",
                "energy": "45",
                "depth": "balanced",
                "era": "90s",
                "format": "album",
                "seed": "late night jazz",
            },
        )

    assert generated.status_code == 200
    assert "late night jazz" in generated.text
    assert "intent: playlist" in generated.text
    assert "data-copy=" in generated.text
    assert "Use as seed" in generated.text


def test_find_page_connected_state_mentions_spotify_profile(tmp_path: Path) -> None:
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
    services.auth_store.upsert_spotify_connection(
        user_id=user.user_id,
        spotify_user_id="spotify-user-1",
        token_payload={"access_token": "access", "refresh_token": "refresh"},
    )

    with TestClient(app) as client:
        client.cookies.set(settings.session_cookie_name, session_token)
        response = client.get("/find")

    assert response.status_code == 200
    assert "Spotify profile" in response.text
    assert "spotify-user-1" in response.text


def test_personal_access_token_can_be_created_from_dashboard(tmp_path: Path) -> None:
    settings = _hosted_settings_with_pats(tmp_path)
    services = create_services(settings)
    fake_sender = FakeMagicLinkEmailSender()
    services.magic_link_email_sender = fake_sender
    app = build_web_app(services, settings=settings)

    with TestClient(app) as client:
        _sign_in_with_magic_link(client, fake_sender)

        created = client.post("/tokens/create", data={"label": "curl"})
        assert created.status_code == 200
        assert "Copy this token now" in created.text
        assert "curl" in created.text


def test_personal_access_token_route_is_hidden_when_disabled(tmp_path: Path) -> None:
    settings = _hosted_settings(tmp_path)
    services = create_services(settings)
    fake_sender = FakeMagicLinkEmailSender()
    services.magic_link_email_sender = fake_sender
    app = build_web_app(services, settings=settings)

    with TestClient(app) as client:
        _sign_in_with_magic_link(client, fake_sender)
        response = client.post("/tokens/create", data={"label": "curl"})
        assert response.status_code == 404


def test_sign_in_is_rate_limited(tmp_path: Path) -> None:
    settings = _hosted_settings(tmp_path).model_copy(
        update={
            "signin_rate_limit_max_attempts": 1,
            "signin_rate_limit_window_seconds": 3600,
        }
    )
    services = create_services(settings)
    fake_sender = FakeMagicLinkEmailSender()
    services.magic_link_email_sender = fake_sender
    app = build_web_app(services, settings=settings)

    with TestClient(app) as client:
        first = client.post(
            "/sign-in",
            data={"email": "missing@example.com"},
        )
        assert first.status_code == 200

        second = client.post(
            "/sign-in",
            data={"email": "missing@example.com"},
        )
        assert second.status_code == 429


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
