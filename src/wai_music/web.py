"""Minimal web UI and browser auth routes for hosted wai-music."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from datetime import UTC, datetime
from html import escape
from threading import Lock
from typing import cast
from urllib.parse import parse_qs, quote

from mcp.server.auth.provider import construct_redirect_uri
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import BaseRoute, Route

from wai_music.auth.oauth import WaiOAuthProvider
from wai_music.auth.spotify import build_authorize_url, current_user_profile, exchange_code
from wai_music.auth.store import SessionRecord
from wai_music.models import (
    DiscoveryDepth,
    MusicFinderChoices,
    MusicFinderIntent,
    MusicFinderResult,
    MusicFinderSource,
)
from wai_music.services import ServiceContainer
from wai_music.settings import WaiMusicSettings
from wai_music.tools.finder import find_music_for_choices

APP_CSS = """
* {
  box-sizing: border-box;
}
:root {
  --paper: #fbfaf5;
  --surface: #fffdf8;
  --surface-strong: #ffffff;
  --nav: #14120f;
  --nav-muted: #c7bfb2;
  --ink: #17130f;
  --muted: #5c554c;
  --faint: #8b8276;
  --line: #ddd5c8;
  --line-strong: #c9bda9;
  --teal: #006b63;
  --teal-dark: #064b47;
  --amber: #a66a10;
  --green: #1a8f4d;
  --danger-bg: #fdf0ee;
  --danger: #962f24;
  --radius: 8px;
}
body {
  margin: 0;
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background:
    linear-gradient(90deg, rgba(6, 75, 71, 0.035) 1px, transparent 1px),
    linear-gradient(180deg, rgba(166, 106, 16, 0.035) 1px, transparent 1px),
    var(--paper);
  background-size: 28px 28px;
  color: var(--ink);
}
a {
  color: inherit;
}
.topbar {
  min-height: 68px;
  border-bottom: 1px solid rgba(255, 253, 248, 0.12);
  background:
    linear-gradient(180deg, rgba(255, 253, 248, 0.045), transparent),
    var(--nav);
  backdrop-filter: blur(16px);
  display: grid;
  grid-template-columns: minmax(180px, 1fr) auto minmax(180px, 1fr);
  align-items: center;
  gap: 24px;
  padding: 0 32px;
  position: sticky;
  top: 0;
  z-index: 3;
}
.brand {
  font-family: Georgia, "Iowan Old Style", "Palatino Linotype", serif;
  font-size: clamp(28px, 3vw, 40px);
  line-height: 1;
  text-decoration: none;
  letter-spacing: 0;
  color: #fffaf0;
}
.nav {
  display: flex;
  align-items: center;
  gap: 26px;
  color: var(--nav-muted);
  font-size: 15px;
}
.nav a {
  text-decoration: none;
  padding: 23px 0 20px;
  border-bottom: 3px solid transparent;
}
.nav a[aria-current="page"],
.nav a:hover {
  color: #fffaf0;
  border-color: var(--teal);
}
.top-actions {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 10px;
}
.shell {
  width: min(1440px, 100%);
  margin: 0 auto;
  padding: 24px 32px 64px;
}
.hero {
  display: grid;
  gap: 18px;
  padding: 48px 0 32px;
  max-width: 920px;
}
h1, h2, h3, p { margin-top: 0; }
h1 {
  font-family: Georgia, "Iowan Old Style", "Palatino Linotype", serif;
  font-size: clamp(42px, 6vw, 82px);
  line-height: 0.98;
  letter-spacing: 0;
  margin-bottom: 0;
  max-width: 860px;
}
h2 {
  font-family: Georgia, "Iowan Old Style", "Palatino Linotype", serif;
  font-size: 26px;
  line-height: 1.12;
  margin-bottom: 10px;
  letter-spacing: 0;
}
h3 {
  font-size: 16px;
  line-height: 1.25;
  margin-bottom: 8px;
}
p {
  font-size: 17px;
  line-height: 1.55;
  color: var(--muted);
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 14px;
  margin-top: 24px;
}
.card {
  background: rgba(255, 253, 248, 0.88);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 20px;
}
.muted { color: var(--muted); font-size: 14px; }
.mono {
  font-family: "SFMono-Regular", "Menlo", "Monaco", monospace;
  font-size: 13px;
  overflow-wrap: anywhere;
  color: var(--ink);
}
form {
  display: grid;
  gap: 14px;
}
label {
  display: grid;
  gap: 6px;
  font-size: 14px;
  color: var(--ink);
}
input,
select,
textarea {
  width: 100%;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius);
  padding: 11px 12px;
  background: rgba(255, 255, 255, 0.78);
  color: var(--ink);
  font: 14px/1.35 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
input[type="range"] {
  accent-color: var(--teal);
  padding: 0;
}
fieldset {
  border: 0;
  padding: 0;
  margin: 0;
}
legend {
  font-weight: 760;
  margin-bottom: 8px;
}
button, .button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 42px;
  border-radius: var(--radius);
  padding: 11px 16px;
  border: 1px solid transparent;
  background: var(--teal-dark);
  color: #fff;
  font: 760 14px/1 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  text-decoration: none;
  cursor: pointer;
}
.button.secondary, button.secondary {
  background: var(--surface-strong);
  border-color: var(--line);
  color: var(--ink);
}
.topbar .button.secondary {
  background: rgba(255, 253, 248, 0.08);
  border-color: rgba(255, 253, 248, 0.18);
  color: #fffaf0;
}
.button.ghost, button.ghost {
  background: transparent;
  border-color: var(--line);
  color: var(--ink);
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.error {
  background: var(--danger-bg);
  color: var(--danger);
  border: 1px solid rgba(150, 47, 36, 0.18);
  border-radius: var(--radius);
  padding: 14px 16px;
  margin: 0 0 18px;
}
ul {
  margin: 0;
  padding-left: 18px;
  color: #44372b;
}
ol {
  margin: 0;
  padding-left: 20px;
  color: var(--muted);
}
:focus-visible {
  outline: 3px solid rgba(0, 107, 99, 0.28);
  outline-offset: 2px;
}
.finder-layout {
  display: grid;
  grid-template-columns: minmax(300px, 390px) minmax(0, 1fr);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: rgba(255, 253, 248, 0.74);
  overflow: auto;
  box-shadow: 0 18px 60px rgba(35, 28, 18, 0.08);
}
.choice-panel {
  border-right: 1px solid var(--line);
  padding: 24px 28px;
  background: rgba(255, 253, 248, 0.72);
  min-width: 0;
}
.results-panel h2 {
  font-size: 32px;
}
.choice-panel h2 {
  font-size: 24px;
  line-height: 1.08;
}
.choice-panel form {
  margin-top: 14px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  column-gap: 12px;
  row-gap: 0;
}
.control-group {
  display: grid;
  gap: 7px;
  padding: 10px 0;
  border-top: 1px solid var(--line);
}
.choice-panel .control-group:nth-child(1),
.choice-panel .control-group:nth-child(5),
.choice-panel button[type="submit"] {
  grid-column: 1 / -1;
}
.control-group:first-of-type {
  border-top: 0;
  padding-top: 0;
}
.range-meta {
  display: flex;
  justify-content: space-between;
  color: var(--muted);
  font-size: 12px;
}
.results-panel {
  padding: 24px 32px;
  min-width: 0;
}
.results-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 20px;
  margin-bottom: 14px;
}
.recommendation {
  display: grid;
  grid-template-columns: 128px minmax(0, 1fr) 150px 210px;
  gap: 24px;
  align-items: center;
  border-top: 1px solid var(--line);
  padding: 14px 0;
}
.cover-tile {
  aspect-ratio: 1;
  border-radius: var(--radius);
  border: 1px solid rgba(23, 19, 15, 0.08);
  background:
    linear-gradient(135deg, rgba(6, 75, 71, 0.8), transparent 52%),
    linear-gradient(45deg, rgba(166, 106, 16, 0.38), transparent 55%),
    linear-gradient(180deg, #29302b, #ede0ca);
}
.cover-tile.alt-1 {
  background:
    linear-gradient(150deg, rgba(21, 35, 42, 0.92), transparent 55%),
    linear-gradient(70deg, rgba(255, 253, 248, 0.72), transparent 48%),
    #778982;
}
.cover-tile.alt-2 {
  background:
    linear-gradient(130deg, rgba(25, 77, 55, 0.92), transparent 50%),
    linear-gradient(20deg, rgba(166, 106, 16, 0.42), transparent 56%),
    #d7c7ad;
}
.rank {
  font-family: Georgia, "Iowan Old Style", "Palatino Linotype", serif;
  color: var(--amber);
  font-size: 32px;
  margin-right: 12px;
}
.rec-title {
  display: flex;
  align-items: baseline;
  gap: 4px;
  font-family: Georgia, "Iowan Old Style", "Palatino Linotype", serif;
  font-size: 24px;
  line-height: 1.05;
  margin-bottom: 8px;
}
.rec-detail p {
  margin-bottom: 8px;
  font-size: 14px;
}
.rec-detail strong {
  color: var(--amber);
}
.tag-list {
  display: grid;
  gap: 6px;
  color: var(--teal-dark);
  font-size: 14px;
}
.tag-title {
  color: var(--ink);
  font-size: 11px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}
.rec-actions {
  display: grid;
  gap: 8px;
}
.action-form {
  margin: 0;
  display: block;
}
.rec-actions .button,
.rec-actions button {
  justify-content: flex-start;
  min-height: 34px;
  padding: 7px 10px;
  font-weight: 650;
}
.status-strip {
  display: grid;
  grid-template-columns: 1.1fr 1fr 1fr;
  gap: 28px;
  border: 1px solid var(--line);
  border-top: 0;
  border-radius: 0 0 var(--radius) var(--radius);
  padding: 18px 28px;
  background: rgba(255, 253, 248, 0.86);
}
.status-dot {
  display: inline-flex;
  width: 9px;
  height: 9px;
  border-radius: 999px;
  background: var(--green);
  margin-right: 7px;
}
.prompt-box {
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 14px;
  background: #fff;
  white-space: pre-wrap;
  margin-top: 10px;
  max-height: 76px;
  overflow: auto;
}
.dashboard-title {
  margin: 26px 0 0;
}
@media (max-width: 980px) {
  .topbar {
    grid-template-columns: 1fr;
    gap: 10px;
    padding: 18px 20px;
    position: static;
  }
  .nav,
  .top-actions {
    justify-content: flex-start;
    overflow-x: auto;
  }
  .shell {
    padding: 22px 18px 56px;
  }
  .finder-layout,
  .status-strip {
    grid-template-columns: 1fr;
  }
  .choice-panel form {
    grid-template-columns: 1fr;
  }
  .choice-panel .control-group,
  .choice-panel button[type="submit"] {
    grid-column: auto;
  }
  .choice-panel {
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }
  .choice-panel h2 {
    font-size: 21px;
    overflow-wrap: break-word;
    overflow-wrap: anywhere;
  }
  .recommendation {
    grid-template-columns: 82px minmax(0, 1fr);
  }
  .tag-list,
  .rec-actions {
    grid-column: 1 / -1;
  }
  .actions .button,
  .actions button {
    width: 100%;
  }
}
"""


def build_web_routes(
    services: ServiceContainer,
    settings: WaiMusicSettings,
    oauth_provider: WaiOAuthProvider | None,
) -> list[BaseRoute]:
    rate_limiter = InMemoryRateLimiter()

    async def landing(request: Request) -> Response:
        session = _session_from_request(request, services=services, settings=settings)
        if session is not None:
            return RedirectResponse("/dashboard", status_code=303)
        body = """
        <section class="hero">
          <h1>Find music with an AI that understands your taste.</h1>
          <p>
            Connect Spotify, choose what you want to hear, and let Claude use wai-music
            to search, explain, and build playlists from real music metadata.
          </p>
          <div class="actions">
            <a class="button" href="/sign-up">Start finding music</a>
            <a class="button secondary" href="/sign-in">Sign in</a>
          </div>
        </section>
        <section class="grid">
          <article class="card">
            <h2>Choice-first discovery</h2>
            <p>Shape recommendations with mood, era, energy, context, and depth.</p>
          </article>
          <article class="card">
            <h2>MCP-native</h2>
            <p>Claude connects through OAuth and calls typed tools with user-scoped Spotify access.</p>
          </article>
          <article class="card">
            <h2>Grounded music data</h2>
            <p>MusicBrainz, curated scenes, stories, and playlist tools stay separate and inspectable.</p>
          </article>
        </section>
        """
        return HTMLResponse(_page("wai-music", body))

    async def sign_up(request: Request) -> Response:
        if request.method == "GET":
            return HTMLResponse(
                _auth_form("Create account", "/sign-up", next_path=_safe_next(request))
            )
        sign_up_limited = _rate_limit_response(
            request=request,
            limiter=rate_limiter,
            bucket=f"signup:{_request_identity(request)}",
            window_seconds=settings.signup_rate_limit_window_seconds,
            max_attempts=settings.signup_rate_limit_max_attempts,
        )
        if sign_up_limited is not None:
            return sign_up_limited
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
        sign_in_limited = _rate_limit_response(
            request=request,
            limiter=rate_limiter,
            bucket=f"signin:{_request_identity(request)}",
            window_seconds=settings.signin_rate_limit_window_seconds,
            max_attempts=settings.signin_rate_limit_max_attempts,
        )
        if sign_in_limited is not None:
            return sign_in_limited
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
        return HTMLResponse(
            _dashboard_page(
                session,
                services=services,
                settings=settings,
            )
        )

    async def music_finder(request: Request) -> Response:
        session = _require_session(request, services=services, settings=settings)
        if isinstance(session, Response):
            return session
        spotify = services.auth_store.get_spotify_connection(session.user_id)
        error: str | None = None
        submitted = request.method == "POST"
        if submitted:
            form = await _parse_form(request)
            try:
                choices = _finder_choices_from_form(form, spotify_connected=spotify is not None)
            except ValueError as exc:
                choices = _default_finder_choices()
                error = str(exc)
        else:
            choices = _default_finder_choices()
        result = await find_music_for_choices(
            choices,
            services=services,
            limit=3,
            language=settings.default_language,
        )
        return HTMLResponse(
            _finder_page(
                session,
                result,
                services=services,
                settings=settings,
                error=error,
                submitted=submitted,
            )
        )

    async def create_personal_token(request: Request) -> Response:
        if not settings.enable_personal_access_tokens:
            return Response(status_code=404)
        session = _require_session(request, services=services, settings=settings)
        if isinstance(session, Response):
            return session
        token_limited = _rate_limit_response(
            request=request,
            limiter=rate_limiter,
            bucket=f"personal-token:{session.user_id}",
            window_seconds=settings.personal_access_token_rate_limit_window_seconds,
            max_attempts=settings.personal_access_token_rate_limit_max_attempts,
        )
        if token_limited is not None:
            return token_limited
        form = await _parse_form(request)
        try:
            _record, raw_token = services.auth_store.create_personal_access_token(
                user_id=session.user_id,
                label=form.get("label", ""),
                ttl_seconds=settings.personal_access_token_ttl_seconds,
                scopes=settings.oauth_required_scopes,
                resource=settings.oauth_resource_server_url,
            )
        except ValueError as exc:
            return HTMLResponse(
                _dashboard_page(
                    session,
                    services=services,
                    settings=settings,
                    token_error=str(exc),
                ),
                status_code=400,
            )
        return HTMLResponse(
            _dashboard_page(
                session,
                services=services,
                settings=settings,
                created_token=raw_token,
            )
        )

    async def revoke_personal_token(request: Request) -> Response:
        if not settings.enable_personal_access_tokens:
            return Response(status_code=404)
        session = _require_session(request, services=services, settings=settings)
        if isinstance(session, Response):
            return session
        form = await _parse_form(request)
        token_fingerprint_value = form.get("token_fingerprint", "").strip()
        if token_fingerprint_value:
            services.auth_store.revoke_personal_access_token(
                user_id=session.user_id,
                token_fingerprint_value=token_fingerprint_value,
            )
        return RedirectResponse("/dashboard", status_code=303)

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
        Route("/find", endpoint=music_finder, methods=["GET", "POST"]),
        Route("/tokens/create", endpoint=create_personal_token, methods=["POST"]),
        Route("/tokens/revoke", endpoint=revoke_personal_token, methods=["POST"]),
        Route("/spotify/connect", endpoint=spotify_connect, methods=["GET"]),
        Route("/auth/spotify/callback", endpoint=spotify_callback, methods=["GET"]),
        Route("/oauth/approval", endpoint=oauth_approval, methods=["GET", "POST"]),
        Route("/healthz", endpoint=healthz, methods=["GET"]),
    ]


def _dashboard_page(
    session: SessionRecord,
    *,
    services: ServiceContainer,
    settings: WaiMusicSettings,
    created_token: str | None = None,
    token_error: str | None = None,
) -> str:
    spotify = services.auth_store.get_spotify_connection(session.user_id)
    recent_playlists = services.cache.list_playlists(user_id=session.user_id)[-5:]
    personal_tokens = services.auth_store.list_personal_access_tokens(session.user_id)
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
            f'<span class="muted">{escape(item["playlist_id"])}</span></li>'
            for item in recent_playlists
        )
        + "</ul>"
        if recent_playlists
        else '<p class="muted">No playlist history recorded yet.</p>'
    )
    tokens_markup = (
        "<ul>"
        + "".join(
            f"<li><strong>{escape(token.label)}</strong> "
            f'<span class="muted">••••{escape(token.last4)} · expires {escape(_format_unix_ts(token.expires_at))}</span> '
            f'<form method="post" action="/tokens/revoke" style="display:inline">'
            f'<input type="hidden" name="token_fingerprint" value="{escape(token.token_fingerprint)}" />'
            f'<button class="secondary" type="submit">Revoke</button>'
            f"</form></li>"
            for token in personal_tokens
        )
        + "</ul>"
        if personal_tokens
        else '<p class="muted">No personal access tokens issued yet.</p>'
    )
    created_token_markup = (
        f"""
        <div class="error" style="background:#eef8f2;color:#1b5d3f;border-color:rgba(27,93,63,0.18);">
          Copy this token now. It will not be shown again.
          <p class="mono">{escape(created_token)}</p>
        </div>
        """
        if created_token is not None
        else ""
    )
    token_error_markup = (
        f'<div class="error">{escape(token_error)}</div>' if token_error is not None else ""
    )
    mcp_url = _mcp_url(settings)
    token_card_markup = (
        f"""
          <article class="card">
            <h2>Advanced Clients</h2>
            <p class="muted">
              Use personal access tokens for manual testing or clients that do not support OAuth.
              For Claude, prefer the OAuth flow above.
            </p>
            {token_error_markup}
            {created_token_markup}
            <form method="post" action="/tokens/create">
              <label>
                Token label
                <input name="label" placeholder="Inspector, local script, curl" />
              </label>
              <button type="submit">Generate token</button>
            </form>
            <div style="margin-top: 16px;">
              {tokens_markup}
            </div>
          </article>
        """
        if settings.enable_personal_access_tokens
        else ""
    )
    return _page(
        "Dashboard",
        f"""
        <section class="hero">
          <h1>{escape(session.email)}</h1>
          <p>
            This account owns a separate Spotify integration and receives user-scoped MCP access
            through OAuth. Start with the finder, then let Claude use this MCP server for the
            metadata, profile, and playlist steps.
          </p>
          <div class="actions">
            <a class="button" href="/find">Find music</a>
            <a class="button secondary" href="/spotify/connect">Spotify settings</a>
            <form method="post" action="/logout"><button class="secondary" type="submit">Sign out</button></form>
          </div>
        </section>
        <section class="grid">
          <article class="card">
            <h2>Music Finder</h2>
            <p>
              Choose mood, energy, era, format, and discovery depth. wai-music turns those choices
              into structured recommendations and a ready-to-use Claude prompt.
            </p>
            <a class="button" href="/find">Find music</a>
          </article>
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
            <h2>Connect Claude</h2>
            <ol>
              <li>Add a custom connector in Claude with the MCP endpoint above.</li>
              <li>Leave advanced OAuth client settings empty.</li>
              <li>No API key or manual token is required for the normal flow.</li>
              <li>Claude will redirect you back here for sign-in and approval.</li>
            </ol>
          </article>
          {token_card_markup}
          <article class="card">
            <h2>Recent Playlists</h2>
            {playlists_markup}
          </article>
        </section>
        """,
    )


def _finder_page(
    session: SessionRecord,
    result: MusicFinderResult,
    *,
    services: ServiceContainer,
    settings: WaiMusicSettings,
    submitted: bool,
    error: str | None = None,
) -> str:
    spotify = services.auth_store.get_spotify_connection(session.user_id)
    mcp_url = _mcp_url(settings)
    spotify_state = (
        f"""
        <span><span class="status-dot"></span>Spotify profile connected as
        <strong>{escape(spotify.spotify_user_id)}</strong></span>
        """
        if spotify is not None
        else """
        <strong>Connect Spotify to use your listening profile</strong>
        <a class="button secondary" href="/spotify/connect">Connect Spotify</a>
        """
    )
    error_markup = f'<div class="error">{escape(error)}</div>' if error else ""
    result_label = "Updated recommendations" if submitted else "Starter recommendations"
    body = f"""
    <section class="finder-layout" aria-label="AI music finder">
      <aside class="choice-panel">
        <h2>Tell wai-music what you're in the mood for</h2>
        <p>Fine-tune choices. Claude handles taste and narration; wai-music keeps the music data grounded.</p>
        {error_markup}
        {_finder_form(result.choices, spotify_connected=spotify is not None)}
      </aside>
      <section class="results-panel">
        <div class="results-head">
          <div>
            <h2>Wai's recommendations</h2>
            <p>{escape(result_label)} based on your choices.</p>
          </div>
          <a class="button ghost" href="/dashboard">Dashboard</a>
        </div>
        {_recommendations_markup(result)}
      </section>
    </section>
    <section class="status-strip" aria-label="MCP status">
      <div>
        <h3>MCP endpoint</h3>
        <p class="mono">{escape(mcp_url)}</p>
      </div>
      <div>
        <h3>Client status</h3>
        <p>{spotify_state}</p>
      </div>
      <div>
        <h3>Use this with Claude after connecting wai-music</h3>
        <div class="prompt-box mono">{escape(result.mcp_prompt)}</div>
      </div>
    </section>
    <h2 class="dashboard-title">Your dashboard continues below</h2>
    <section class="grid">
      <article class="card">
        <h2>Recent Playlists</h2>
        {_recent_playlists_markup(session, services=services)}
      </article>
      <article class="card">
        <h2>Connector</h2>
        <p>Add the MCP endpoint in Claude. No API key or manual token is required for the normal flow.</p>
      </article>
      <article class="card">
        <h2>Spotify</h2>
        <p>{spotify_state}</p>
      </article>
    </section>
    """
    return _page("Find music", body)


def _finder_form(choices: MusicFinderChoices, *, spotify_connected: bool) -> str:
    profile_disabled = "disabled" if not spotify_connected else ""
    return f"""
    <form method="post" action="/find">
      <div class="control-group">
        <label for="finder-seed">Seed</label>
        <input id="finder-seed" name="seed" value="{escape(choices.query or "")}" placeholder="artist, track, scene, mood, or free text" />
      </div>
      <div class="control-group">
        <label for="finder-intent">Intent</label>
        <select id="finder-intent" name="intent">
          {_option("playlist", "Make a playlist", choices.intent)}
          {_option("track", "Find one track", choices.intent)}
          {_option("album", "Find an album", choices.intent)}
          {_option("scene", "Explore a scene", choices.intent)}
        </select>
      </div>
      <div class="control-group">
        <label for="finder-source">Source</label>
        <select id="finder-source" name="source">
          {_option("curated", "Curated", choices.source)}
          {_option("manual_seed", "Manual seed", choices.source)}
          {_option("scene_dive", "Scene dive", choices.source)}
          {_option("spotify_profile", "Spotify profile", choices.source, disabled=profile_disabled)}
        </select>
      </div>
      <div class="control-group">
        <label for="finder-mood">Mood</label>
        <select id="finder-mood" name="mood">
          {_option("reflective", "Reflective", _first_choice(choices.moods, "reflective"))}
          {_option("focused", "Focused", _first_choice(choices.moods, "reflective"))}
          {_option("warm", "Warm", _first_choice(choices.moods, "reflective"))}
          {_option("energetic", "Energetic", _first_choice(choices.moods, "reflective"))}
        </select>
      </div>
      <div class="control-group">
        <label for="finder-energy">Energy</label>
        <input id="finder-energy" type="range" name="energy" min="0" max="100" value="{escape(str(choices.energy if choices.energy is not None else 45))}" />
        <div class="range-meta"><span>Calm</span><span>Balanced</span><span>Energetic</span></div>
      </div>
      <div class="control-group">
        <label for="finder-depth">Discovery depth</label>
        <select id="finder-depth" name="depth">
          {_option("familiar", "Familiar", choices.discovery_depth)}
          {_option("balanced", "Balanced", choices.discovery_depth)}
          {_option("adventurous", "Adventurous", choices.discovery_depth)}
        </select>
      </div>
      <div class="control-group">
        <label for="finder-era">Era</label>
        <select id="finder-era" name="era">
          {_option("", "Any era", _first_choice(choices.eras, ""))}
          {_option("1950s", "1950s", _first_choice(choices.eras, ""))}
          {_option("1970s", "1970s", _first_choice(choices.eras, ""))}
          {_option("1990s", "1990s", _first_choice(choices.eras, ""))}
          {_option("2000s", "2000s", _first_choice(choices.eras, ""))}
        </select>
      </div>
      <div class="control-group">
        <label for="finder-format">Format</label>
        <select id="finder-format" name="format">
          {_option("", "Any format", _first_choice(choices.formats, ""))}
          {_option("album", "Album", _first_choice(choices.formats, ""))}
          {_option("track", "Track", _first_choice(choices.formats, ""))}
          {_option("work", "Classical work", _first_choice(choices.formats, ""))}
        </select>
      </div>
      <button type="submit">Find music</button>
    </form>
    """


def _recommendations_markup(result: MusicFinderResult) -> str:
    if not result.candidates:
        return '<p class="muted">No recommendations matched these choices.</p>'
    rows = []
    for candidate in result.candidates:
        metadata = candidate.entity.metadata
        artist = metadata.get("artist") if isinstance(metadata.get("artist"), str) else None
        year = metadata.get("year") if isinstance(metadata.get("year"), int) else None
        raw_genre = metadata.get("genre")
        genre = raw_genre if isinstance(raw_genre, str) else candidate.source
        display_tags = _display_tags(result, genre, year)
        source_detail = " · ".join(
            part for part in [artist, str(year) if year is not None else None] if part
        )
        spotify_query = candidate.spotify_query or candidate.entity.name
        copy_prompt = _candidate_prompt(result, spotify_query)
        rows.append(
            f"""
            <article class="recommendation">
              <div class="cover-tile alt-{(candidate.rank - 1) % 3}"></div>
              <div class="rec-detail">
                <div class="rec-title"><span class="rank">{candidate.rank}.</span>{escape(candidate.entity.name)}</div>
                <p>{escape(source_detail or candidate.entity.type.value.title())}</p>
                <p><strong>Why it matches</strong><br />{escape("; ".join(candidate.reasons[:2]))}</p>
              </div>
              <div class="tag-list">
                <span class="tag-title">Scene tags</span>
                {"".join(f"<span>{escape(item)}</span>" for item in display_tags)}
              </div>
              <div class="rec-actions">
                <button class="ghost" type="button" data-copy="{escape(copy_prompt)}">Copy MCP prompt</button>
                <a class="button ghost" href="https://open.spotify.com/search/{quote(spotify_query)}">Search on Spotify</a>
                <form class="action-form" method="post" action="/find">
                  {_seed_hidden_inputs(result.choices, spotify_query)}
                  <button class="ghost" type="submit">Use as seed</button>
                </form>
              </div>
            </article>
            """
        )
    return "".join(rows)


def _display_tags(result: MusicFinderResult, genre: str, year: int | None) -> list[str]:
    tags = [genre.title()]
    if result.choices.eras:
        tags.append(result.choices.eras[0])
    elif year is not None:
        tags.append(f"{year // 10 * 10}s")
    if result.choices.formats:
        tags.append(result.choices.formats[0])
    if result.choices.moods:
        tags.append(result.choices.moods[0])
    deduped: list[str] = []
    for tag in tags:
        normalized = " ".join(tag.strip().split())
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped[:4]


def _candidate_prompt(result: MusicFinderResult, seed: str) -> str:
    choices = result.choices.model_copy(update={"query": seed, "source": "manual_seed"})
    return "\n".join(
        [
            "Use the wai-music MCP tools to refine this recommendation.",
            f"seed: {seed}",
            result.mcp_prompt,
            f"next_source: {choices.source}",
        ]
    )


def _seed_hidden_inputs(choices: MusicFinderChoices, seed: str) -> str:
    return "".join(
        [
            _hidden_input("seed", seed),
            _hidden_input("intent", choices.intent),
            _hidden_input("source", "manual_seed"),
            _hidden_input("mood", _first_choice(choices.moods, "reflective")),
            _hidden_input("energy", str(choices.energy if choices.energy is not None else 45)),
            _hidden_input("depth", choices.discovery_depth),
            _hidden_input("era", _first_choice(choices.eras, "")),
            _hidden_input("format", _first_choice(choices.formats, "")),
        ]
    )


def _hidden_input(name: str, value: str) -> str:
    return f'<input type="hidden" name="{escape(name)}" value="{escape(value)}" />'


def _finder_choices_from_form(
    form: dict[str, str],
    *,
    spotify_connected: bool,
) -> MusicFinderChoices:
    intent = _validated_intent(form.get("intent", "playlist"))
    source = _validated_source(form.get("source", "curated"))
    discovery_depth = _validated_depth(form.get("depth", "balanced"))
    if source == "spotify_profile" and not spotify_connected:
        raise ValueError("Connect Spotify to use your listening profile.")
    energy_raw = form.get("energy", "45")
    try:
        energy = int(energy_raw)
    except ValueError as exc:
        raise ValueError("Energy must be a number from 0 to 100.") from exc
    return MusicFinderChoices(
        intent=intent,
        source=source,
        query=form.get("seed"),
        moods=[form.get("mood", "reflective")],
        eras=_optional_list(form.get("era")),
        formats=_optional_list(form.get("format")),
        genres=_genres_for_form(form),
        energy=energy,
        discovery_depth=discovery_depth,
        include_tracks=False,
        use_listening_profile=False,
        limit=3,
    )


def _default_finder_choices() -> MusicFinderChoices:
    return MusicFinderChoices(
        intent="playlist",
        source="curated",
        query="late night jazz",
        genres=["jazz"],
        moods=["reflective"],
        energy=45,
        discovery_depth="balanced",
        formats=["album"],
        include_tracks=False,
        limit=3,
    )


def _genres_for_form(form: dict[str, str]) -> list[str]:
    seed = form.get("seed", "")
    mood = form.get("mood", "")
    genres: list[str] = []
    for candidate in ("jazz", "electronic", "rock", "hip-hop", "classical", "folk", "pop", "world"):
        if candidate in seed.lower() or candidate in mood.lower():
            genres.append(candidate)
    return genres


def _validated_intent(value: str) -> MusicFinderIntent:
    allowed = {"playlist", "track", "album", "artist", "scene", "daily_pick"}
    if value not in allowed:
        raise ValueError("Unsupported finder intent.")
    return cast(MusicFinderIntent, value)


def _validated_source(value: str) -> MusicFinderSource:
    allowed = {"curated", "spotify_profile", "manual_seed", "scene_dive"}
    if value not in allowed:
        raise ValueError("Unsupported finder source.")
    return cast(MusicFinderSource, value)


def _validated_depth(value: str) -> DiscoveryDepth:
    allowed = {"familiar", "balanced", "adventurous"}
    if value not in allowed:
        raise ValueError("Unsupported discovery depth.")
    return cast(DiscoveryDepth, value)


def _optional_list(value: str | None) -> list[str]:
    if value is None or not value.strip():
        return []
    return [value]


def _option(value: str, label: str, selected: str, *, disabled: str = "") -> str:
    selected_attr = " selected" if value == selected else ""
    disabled_attr = " disabled" if disabled else ""
    return f'<option value="{escape(value)}"{selected_attr}{disabled_attr}>{escape(label)}</option>'


def _first_choice(values: list[str], default: str) -> str:
    return values[0] if values else default


def _recent_playlists_markup(
    session: SessionRecord,
    *,
    services: ServiceContainer,
) -> str:
    recent_playlists = services.cache.list_playlists(user_id=session.user_id)[-5:]
    if not recent_playlists:
        return '<p class="muted">No playlist history recorded yet.</p>'
    return (
        "<ul>"
        + "".join(
            f"<li><strong>{escape(item['slug'])}</strong> "
            f'<span class="muted">{escape(item["playlist_id"])}</span></li>'
            for item in recent_playlists
        )
        + "</ul>"
    )


def _format_unix_ts(value: int) -> str:
    return datetime.fromtimestamp(value, UTC).isoformat(timespec="seconds")


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def hit(self, *, bucket: str, window_seconds: int, max_attempts: int) -> int | None:
        now = time.time()
        with self._lock:
            queue = self._events[bucket]
            while queue and queue[0] <= now - window_seconds:
                queue.popleft()
            if len(queue) >= max_attempts:
                retry_after = max(1, int(window_seconds - (now - queue[0])))
                return retry_after
            queue.append(now)
        return None


def _request_identity(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", maxsplit=1)[0].strip()
    if request.client is not None and request.client.host:
        return request.client.host
    return "unknown"


def _rate_limit_response(
    *,
    request: Request,
    limiter: InMemoryRateLimiter,
    bucket: str,
    window_seconds: int,
    max_attempts: int,
) -> Response | None:
    retry_after = limiter.hit(
        bucket=bucket,
        window_seconds=window_seconds,
        max_attempts=max_attempts,
    )
    if retry_after is None:
        return None
    body = _page(
        "Too many requests",
        """
        <section class="hero">
          <div class="error">
            Too many attempts from this client. Please wait and try again.
          </div>
        </section>
        """,
    )
    return HTMLResponse(
        body,
        status_code=429,
        headers={"Retry-After": str(retry_after)},
    )


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
    discover_current = ' aria-current="page"' if title in {"wai-music", "Find music"} else ""
    dashboard_current = ' aria-current="page"' if title == "Dashboard" else ""
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{escape(title)} | wai-music</title>
    <style>{APP_CSS}</style>
  </head>
  <body>
    <header class="topbar">
      <a class="brand" href="/">wai-music</a>
      <nav class="nav" aria-label="Primary">
        <a href="/find"{discover_current}>Discover</a>
        <a href="/dashboard"{dashboard_current}>Dashboard</a>
        <a href="/dashboard">Playlists</a>
        <a href="/dashboard">MCP</a>
      </nav>
      <div class="top-actions">
        <a class="button secondary" href="/sign-in">Sign in</a>
        <a class="button" href="/spotify/connect">Connect Spotify</a>
      </div>
    </header>
    <main class="shell">
      {body}
    </main>
    <script>
      document.addEventListener("click", async (event) => {{
        const button = event.target.closest("[data-copy]");
        if (!button) return;
        const original = button.textContent;
        const text = button.getAttribute("data-copy") || "";
        try {{
          await navigator.clipboard.writeText(text);
          button.textContent = "Copied";
        }} catch (error) {{
          button.textContent = "Copy failed";
          button.setAttribute("aria-label", "Copy failed");
        }}
        window.setTimeout(() => {{
          button.textContent = original;
          button.removeAttribute("aria-label");
        }}, 1800);
      }});
    </script>
  </body>
</html>
"""
