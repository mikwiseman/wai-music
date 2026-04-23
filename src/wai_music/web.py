"""Minimal web UI and browser auth routes for hosted wai-music."""

from __future__ import annotations

from html import escape
from urllib.parse import parse_qs, quote

from mcp.server.auth.provider import construct_redirect_uri
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import BaseRoute, Route

from wai_music.auth.oauth import WaiOAuthProvider
from wai_music.auth.spotify import build_authorize_url, current_user_profile, exchange_code
from wai_music.auth.store import SessionRecord
from wai_music.services import ServiceContainer
from wai_music.settings import WaiMusicSettings

APP_CSS = """
body {
  margin: 0;
  font-family: Georgia, "Iowan Old Style", "Palatino Linotype", serif;
  background:
    radial-gradient(circle at top left, rgba(195, 225, 255, 0.55), transparent 32%),
    radial-gradient(circle at bottom right, rgba(255, 226, 196, 0.45), transparent 28%),
    linear-gradient(180deg, #f6f1e8 0%, #efe7d8 100%);
  color: #1c1711;
}
.shell {
  max-width: 980px;
  margin: 0 auto;
  padding: 48px 24px 72px;
}
.hero {
  background: rgba(255, 252, 247, 0.85);
  border: 1px solid rgba(28, 23, 17, 0.12);
  border-radius: 28px;
  padding: 28px 30px;
  box-shadow: 0 20px 60px rgba(67, 46, 15, 0.08);
}
.eyebrow {
  text-transform: uppercase;
  letter-spacing: 0.14em;
  font-size: 12px;
  color: #7d5b2a;
  margin: 0 0 12px;
}
h1, h2, h3, p { margin-top: 0; }
h1 { font-size: 44px; line-height: 1.05; margin-bottom: 12px; }
h2 { font-size: 28px; line-height: 1.15; margin-bottom: 12px; }
p { font-size: 18px; line-height: 1.6; color: #44372b; }
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 18px;
  margin-top: 24px;
}
.card {
  background: rgba(255, 252, 247, 0.9);
  border: 1px solid rgba(28, 23, 17, 0.12);
  border-radius: 24px;
  padding: 22px;
}
.muted { color: #6a5847; font-size: 15px; }
.mono {
  font-family: "SFMono-Regular", "Menlo", "Monaco", monospace;
  font-size: 14px;
  overflow-wrap: anywhere;
  color: #2a2016;
}
form {
  display: grid;
  gap: 14px;
}
label {
  display: grid;
  gap: 6px;
  font-size: 15px;
}
input {
  border: 1px solid rgba(28, 23, 17, 0.18);
  border-radius: 14px;
  padding: 12px 14px;
  background: rgba(255, 255, 255, 0.9);
  font: inherit;
}
button, .button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border-radius: 999px;
  padding: 12px 18px;
  border: none;
  background: #1d6f4b;
  color: #fff;
  font: inherit;
  font-weight: 700;
  text-decoration: none;
  cursor: pointer;
}
.button.secondary, button.secondary {
  background: #efe4d2;
  color: #241a11;
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.error {
  background: #fdf0ee;
  color: #962f24;
  border: 1px solid rgba(150, 47, 36, 0.18);
  border-radius: 16px;
  padding: 14px 16px;
  margin: 0 0 18px;
}
ul {
  margin: 0;
  padding-left: 18px;
  color: #44372b;
}
"""


def build_web_routes(
    services: ServiceContainer,
    settings: WaiMusicSettings,
    oauth_provider: WaiOAuthProvider | None,
) -> list[BaseRoute]:
    async def landing(request: Request) -> Response:
        session = _session_from_request(request, services=services, settings=settings)
        if session is not None:
            return RedirectResponse("/dashboard", status_code=303)
        body = """
        <section class="hero">
          <p class="eyebrow">Hosted wai-music</p>
          <h1>Your music graph, your Spotify, your MCP account.</h1>
          <p>
            This server gives each user a separate authenticated music workspace:
            Spotify integration, protected MCP access, playlist history, and notes.
          </p>
          <div class="actions">
            <a class="button" href="/sign-up">Create account</a>
            <a class="button secondary" href="/sign-in">Sign in</a>
          </div>
        </section>
        """
        return HTMLResponse(_page("wai-music", body))

    async def sign_up(request: Request) -> Response:
        if request.method == "GET":
            return HTMLResponse(_auth_form("Create account", "/sign-up", next_path=_safe_next(request)))
        form = await _parse_form(request)
        next_path = _safe_next(request, form.get("next"))
        try:
            user = services.auth_store.create_user(
                email=form.get("email", ""),
                password=form.get("password", ""),
            )
        except ValueError as exc:
            return HTMLResponse(
                _auth_form(
                    "Create account",
                    "/sign-up",
                    error=str(exc),
                    next_path=next_path,
                    email=form.get("email", ""),
                ),
                status_code=400,
            )
        return _session_redirect(
            user.user_id,
            next_path,
            services=services,
            settings=settings,
        )

    async def sign_in(request: Request) -> Response:
        if request.method == "GET":
            return HTMLResponse(_auth_form("Sign in", "/sign-in", next_path=_safe_next(request)))
        form = await _parse_form(request)
        next_path = _safe_next(request, form.get("next"))
        user = services.auth_store.authenticate_user(
            email=form.get("email", ""),
            password=form.get("password", ""),
        )
        if user is None:
            return HTMLResponse(
                _auth_form(
                    "Sign in",
                    "/sign-in",
                    error="Invalid email or password.",
                    next_path=next_path,
                    email=form.get("email", ""),
                ),
                status_code=401,
            )
        return _session_redirect(
            user.user_id,
            next_path,
            services=services,
            settings=settings,
        )

    async def logout(request: Request) -> Response:
        session_token = request.cookies.get(settings.session_cookie_name)
        if session_token:
            services.auth_store.delete_session(session_token)
        response = RedirectResponse("/", status_code=303)
        response.delete_cookie(settings.session_cookie_name)
        return response

    async def dashboard(request: Request) -> Response:
        session = _require_session(request, services=services, settings=settings)
        if isinstance(session, Response):
            return session
        spotify = services.auth_store.get_spotify_connection(session.user_id)
        recent_playlists = services.cache.list_playlists(user_id=session.user_id)[-5:]
        spotify_markup = (
            f"""
            <p>Connected as <strong>{escape(spotify.spotify_user_id)}</strong>.</p>
            <p class="muted">Last updated: {escape(spotify.updated_at)}</p>
            <div class="actions">
              <a class="button" href="/spotify/connect">Reconnect Spotify</a>
            </div>
            """
            if spotify is not None
            else """
            <p>Spotify is not connected yet.</p>
            <div class="actions">
              <a class="button" href="/spotify/connect">Connect Spotify</a>
            </div>
            """
        )
        playlists_markup = (
            "<ul>"
            + "".join(
                f"<li><strong>{escape(item['slug'])}</strong> "
                f"<span class=\"muted\">{escape(item['playlist_id'])}</span></li>"
                for item in recent_playlists
            )
            + "</ul>"
            if recent_playlists
            else "<p class=\"muted\">No playlist history recorded yet.</p>"
        )
        mcp_url = _mcp_url(settings)
        body = f"""
        <section class="hero">
          <p class="eyebrow">Dashboard</p>
          <h1>{escape(session.email)}</h1>
          <p>
            This account owns a separate Spotify integration and receives user-scoped MCP access
            through OAuth. The MCP endpoint below is the URL you add in Claude.
          </p>
          <div class="actions">
            <a class="button secondary" href="/spotify/connect">Spotify settings</a>
            <form method="post" action="/logout"><button class="secondary" type="submit">Sign out</button></form>
          </div>
        </section>
        <section class="grid">
          <article class="card">
            <h2>Spotify</h2>
            {spotify_markup}
          </article>
          <article class="card">
            <h2>MCP Endpoint</h2>
            <p class="mono">{escape(mcp_url)}</p>
            <p class="muted">
              Claude will discover OAuth metadata automatically from this service.
            </p>
          </article>
          <article class="card">
            <h2>Recent Playlists</h2>
            {playlists_markup}
          </article>
        </section>
        """
        return HTMLResponse(_page("Dashboard", body))

    async def spotify_connect(request: Request) -> Response:
        session = _require_session(request, services=services, settings=settings)
        if isinstance(session, Response):
            return session
        if not settings.spotify_client_id or not settings.spotify_client_secret:
            return HTMLResponse(
                _page(
                    "Spotify configuration error",
                    '<section class="hero"><div class="error">Spotify credentials are not configured on the server.</div></section>',
                ),
                status_code=500,
            )
        return_to = _safe_next(request)
        state = services.auth_store.create_spotify_oauth_state(
            user_id=session.user_id,
            ttl_seconds=settings.spotify_oauth_state_ttl_seconds,
            return_to=return_to,
        )
        return RedirectResponse(build_authorize_url(settings, state=state), status_code=303)

    async def spotify_callback(request: Request) -> Response:
        state = request.query_params.get("state")
        code = request.query_params.get("code")
        error = request.query_params.get("error")
        if error is not None:
            return HTMLResponse(
                _page(
                    "Spotify authorization failed",
                    f'<section class="hero"><div class="error">{escape(error)}</div></section>',
                ),
                status_code=400,
            )
        if state is None or code is None:
            return HTMLResponse(
                _page(
                    "Spotify authorization failed",
                    '<section class="hero"><div class="error">Missing code or state.</div></section>',
                ),
                status_code=400,
            )
        consumed = services.auth_store.consume_spotify_oauth_state(state)
        if consumed is None:
            return HTMLResponse(
                _page(
                    "Spotify authorization failed",
                    '<section class="hero"><div class="error">Spotify OAuth state is missing or expired.</div></section>',
                ),
                status_code=400,
            )
        user_id, return_to = consumed
        token_payload = await exchange_code(settings, code=code)
        refresh_token = token_payload.get("refresh_token")
        access_token = token_payload.get("access_token")
        if not isinstance(refresh_token, str) or not isinstance(access_token, str):
            return HTMLResponse(
                _page(
                    "Spotify authorization failed",
                    '<section class="hero"><div class="error">Spotify did not return a refresh token.</div></section>',
                ),
                status_code=400,
            )
        profile = await current_user_profile(
            access_token,
            request_timeout=settings.http_timeout_seconds,
        )
        spotify_user_id = profile.get("id")
        if not isinstance(spotify_user_id, str):
            return HTMLResponse(
                _page(
                    "Spotify authorization failed",
                    '<section class="hero"><div class="error">Spotify profile did not include a user id.</div></section>',
                ),
                status_code=400,
            )
        services.auth_store.upsert_spotify_connection(
            user_id=user_id,
            spotify_user_id=spotify_user_id,
            token_payload=token_payload,
        )
        return RedirectResponse(return_to, status_code=303)

    async def oauth_approval(request: Request) -> Response:
        if oauth_provider is None:
            return Response(status_code=404)
        session = _require_session(request, services=services, settings=settings)
        if isinstance(session, Response):
            return session
        if request.method == "GET":
            request_id = request.query_params.get("request_id")
        else:
            form = await _parse_form(request)
            request_id = form.get("request_id")
        if request_id is None:
            return HTMLResponse(
                _page(
                    "Authorization request not found",
                    '<section class="hero"><div class="error">Missing request id.</div></section>',
                ),
                status_code=400,
            )
        pending = oauth_provider.get_pending_request(request_id)
        if pending is None:
            return HTMLResponse(
                _page(
                    "Authorization request expired",
                    '<section class="hero"><div class="error">Authorization request is missing or expired.</div></section>',
                ),
                status_code=400,
            )
        client = services.auth_store.get_oauth_client(pending.client_id)
        client_name = client.client_name if client and client.client_name else pending.client_id
        scopes = ", ".join(pending.params.scopes or settings.oauth_required_scopes)
        if request.method == "GET":
            body = f"""
            <section class="hero">
              <p class="eyebrow">MCP OAuth</p>
              <h1>Authorize {escape(client_name)}</h1>
              <p>
                This will let the MCP client access your user-scoped wai-music tools and,
                through them, your connected Spotify account.
              </p>
            </section>
            <section class="grid">
              <article class="card">
                <h2>Client</h2>
                <p>{escape(client_name)}</p>
                <p class="muted mono">{escape(pending.client_id)}</p>
              </article>
              <article class="card">
                <h2>Scopes</h2>
                <p class="mono">{escape(scopes)}</p>
              </article>
            </section>
            <section class="card" style="margin-top: 18px;">
              <form method="post" action="/oauth/approval">
                <input type="hidden" name="request_id" value="{escape(request_id)}" />
                <div class="actions">
                  <button type="submit">Approve access</button>
                  <a class="button secondary" href="/dashboard">Cancel</a>
                </div>
              </form>
            </section>
            """
            return HTMLResponse(_page("Approve MCP access", body))
        code = oauth_provider.approve_request(request_id=request_id, user_id=session.user_id)
        return RedirectResponse(
            construct_redirect_uri(
                str(pending.params.redirect_uri),
                code=code,
                state=pending.params.state,
            ),
            status_code=303,
        )

    async def healthz(_request: Request) -> Response:
        return JSONResponse(
            {
                "ok": True,
                "oauth_enabled": settings.oauth_enabled,
                "spotify_configured": bool(
                    settings.spotify_client_id and settings.spotify_client_secret
                ),
            }
        )

    return [
        Route("/", endpoint=landing, methods=["GET"]),
        Route("/sign-up", endpoint=sign_up, methods=["GET", "POST"]),
        Route("/sign-in", endpoint=sign_in, methods=["GET", "POST"]),
        Route("/logout", endpoint=logout, methods=["POST"]),
        Route("/dashboard", endpoint=dashboard, methods=["GET"]),
        Route("/spotify/connect", endpoint=spotify_connect, methods=["GET"]),
        Route("/auth/spotify/callback", endpoint=spotify_callback, methods=["GET"]),
        Route("/oauth/approval", endpoint=oauth_approval, methods=["GET", "POST"]),
        Route("/healthz", endpoint=healthz, methods=["GET"]),
    ]


def _safe_next(request: Request, candidate: str | None = None) -> str:
    raw_value = candidate if candidate is not None else request.query_params.get("next")
    if raw_value is None:
        return "/dashboard"
    if raw_value.startswith("/") and not raw_value.startswith("//"):
        return raw_value
    return "/dashboard"


def _mcp_url(settings: WaiMusicSettings) -> str:
    if settings.public_base_url:
        return f"{settings.public_base_url.rstrip('/')}/mcp"
    return f"http://{settings.host}:{settings.port}/mcp"


async def _parse_form(request: Request) -> dict[str, str]:
    body = (await request.body()).decode("utf-8")
    return {key: values[-1] for key, values in parse_qs(body, keep_blank_values=True).items()}


def _session_from_request(
    request: Request,
    *,
    services: ServiceContainer,
    settings: WaiMusicSettings,
) -> SessionRecord | None:
    session_token = request.cookies.get(settings.session_cookie_name)
    if session_token is None:
        return None
    return services.auth_store.get_session(session_token)


def _require_session(
    request: Request,
    *,
    services: ServiceContainer,
    settings: WaiMusicSettings,
) -> SessionRecord | Response:
    session = _session_from_request(request, services=services, settings=settings)
    if session is not None:
        return session
    current = request.url.path
    if request.url.query:
        current = f"{current}?{request.url.query}"
    return RedirectResponse(f"/sign-in?next={quote(current, safe='/?=&')}", status_code=303)


def _session_redirect(
    user_id: str,
    next_path: str,
    *,
    services: ServiceContainer,
    settings: WaiMusicSettings,
) -> RedirectResponse:
    session_token = services.auth_store.create_session(
        user_id=user_id,
        ttl_seconds=settings.session_ttl_seconds,
    )
    response = RedirectResponse(next_path, status_code=303)
    response.set_cookie(
        settings.session_cookie_name,
        session_token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
    return response


def _auth_form(
    title: str,
    action: str,
    *,
    error: str | None = None,
    next_path: str,
    email: str = "",
) -> str:
    error_markup = f'<div class="error">{escape(error)}</div>' if error else ""
    body = f"""
    <section class="hero">
      <p class="eyebrow">Account</p>
      <h1>{escape(title)}</h1>
      <p>
        Hosted wai-music uses a separate account layer so Spotify tokens, playlists, and notes stay
        scoped to the person who authorized them.
      </p>
    </section>
    <section class="card" style="margin-top: 18px;">
      {error_markup}
      <form method="post" action="{escape(action)}">
        <input type="hidden" name="next" value="{escape(next_path)}" />
        <label>Email
          <input type="email" name="email" value="{escape(email)}" autocomplete="email" required />
        </label>
        <label>Password
          <input type="password" name="password" autocomplete="new-password" required />
        </label>
        <div class="actions">
          <button type="submit">{escape(title)}</button>
          <a class="button secondary" href="/">Back</a>
        </div>
      </form>
    </section>
    """
    return _page(title, body)


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{escape(title)} | wai-music</title>
    <style>{APP_CSS}</style>
  </head>
  <body>
    <main class="shell">
      {body}
    </main>
  </body>
</html>
"""
