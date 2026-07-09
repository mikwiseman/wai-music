"""Minimal web UI and browser auth routes for hosted wai-music."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from datetime import UTC, datetime
from html import escape
from threading import Lock
from typing import cast
from urllib.parse import parse_qs, quote, urlencode

from mcp.server.auth.provider import construct_redirect_uri
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import BaseRoute, Route

from wai_music.auth.magic_email import EmailDeliveryError
from wai_music.auth.oauth import WaiOAuthProvider
from wai_music.auth.spotify import build_authorize_url, current_user_profile, exchange_code
from wai_music.auth.store import SessionRecord
from wai_music.models import (
    CatalogSignal,
    DiscoveryDepth,
    DiscoveryWorkflowStep,
    MusicDiscoveryPlan,
    MusicFinderChoices,
    MusicFinderIntent,
    MusicFinderResult,
    MusicFinderSource,
)
from wai_music.services import ServiceContainer
from wai_music.settings import WaiMusicSettings
from wai_music.tools.workflow import build_music_discovery_plan

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
.top-actions form {
  display: block;
  margin: 0;
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
.source-strip {
  display: grid;
  grid-template-columns: 210px minmax(0, 1fr);
  gap: 18px;
  align-items: center;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: rgba(255, 255, 255, 0.58);
  padding: 14px 16px;
  margin-bottom: 8px;
}
.source-strip-head,
.workflow-heading {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}
.source-strip h3,
.workflow-panel h3 {
  margin: 0 0 4px;
  font-size: 13px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.source-strip p,
.workflow-panel p {
  margin: 0;
  font-size: 13px;
}
.source-marker {
  display: inline-flex;
  width: 10px;
  height: 10px;
  border-radius: 999px;
  background: #d99a32;
  margin-top: 2px;
}
.source-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
}
.source-pill {
  display: inline-flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-height: 32px;
  max-width: 230px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: rgba(255, 253, 248, 0.82);
  padding: 7px 9px;
  font-size: 13px;
}
.source-pill span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.source-pill strong {
  color: var(--faint);
  font-size: 11px;
  font-weight: 760;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.source-active {
  border-color: rgba(6, 75, 71, 0.4);
}
.source-active strong {
  color: var(--teal-dark);
}
.source-planned {
  background: rgba(245, 241, 233, 0.68);
}
.recommendation {
  display: grid;
  grid-template-columns: 48px minmax(0, 1.3fr) minmax(140px, 0.55fr) 176px;
  gap: 18px;
  align-items: center;
  border-top: 1px solid var(--line);
  padding: 14px 0;
}
.cover-tile {
  width: 38px;
  height: 38px;
  border-radius: 999px;
  border: 1px solid rgba(23, 19, 15, 0.08);
  background:
    linear-gradient(135deg, rgba(6, 75, 71, 0.1), rgba(6, 75, 71, 0.22)),
    var(--surface-strong);
  position: relative;
}
.cover-tile::after {
  content: "";
  position: absolute;
  left: 15px;
  top: 11px;
  border-left: 11px solid var(--nav);
  border-top: 7px solid transparent;
  border-bottom: 7px solid transparent;
}
.cover-tile.alt-1 {
  background:
    linear-gradient(135deg, rgba(166, 106, 16, 0.1), rgba(166, 106, 16, 0.2)),
    var(--surface-strong);
}
.cover-tile.alt-2 {
  background:
    linear-gradient(135deg, rgba(21, 35, 42, 0.08), rgba(21, 35, 42, 0.18)),
    var(--surface-strong);
}
.rank {
  color: var(--amber);
  font: 760 13px/1 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  margin-right: 8px;
}
.rec-title {
  display: flex;
  align-items: baseline;
  gap: 2px;
  font-family: Georgia, "Iowan Old Style", "Palatino Linotype", serif;
  font-size: 20px;
  line-height: 1.08;
  margin-bottom: 6px;
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
.workflow-panel {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, 0.85fr);
  gap: 18px;
  border: 1px solid var(--line);
  border-top: 0;
  border-radius: 0 0 var(--radius) var(--radius);
  padding: 18px 28px 24px;
  background: rgba(255, 253, 248, 0.92);
}
.workflow-steps {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-top: 12px;
}
.workflow-step {
  display: grid;
  align-content: space-between;
  min-height: 112px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: rgba(255, 255, 255, 0.62);
  padding: 12px;
}
.workflow-step strong {
  display: block;
  font-size: 14px;
  margin-bottom: 5px;
}
.workflow-step p {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.38;
}
.workflow-step span {
  justify-self: start;
  max-width: 100%;
  border-radius: 5px;
  background: rgba(23, 19, 15, 0.06);
  color: var(--ink);
  padding: 5px 7px;
  font: 12px/1.25 "SFMono-Regular", "Menlo", "Monaco", monospace;
  overflow-wrap: anywhere;
}
.step-requires_connection {
  opacity: 0.78;
}
.prompt-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.prompt-title .ghost {
  min-height: 32px;
  padding: 6px 10px;
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
.prompt-box-large {
  max-height: 184px;
  color: #f5efe5;
  background: #14161a;
  border-color: rgba(255, 253, 248, 0.12);
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
  .status-strip,
  .source-strip,
  .workflow-panel {
    grid-template-columns: 1fr;
  }
  .workflow-steps {
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

AUTH_PAGE_TITLES = {
    "Create account",
    "Sign in",
    "Check your email",
    "Continue sign-in",
    "Magic link expired",
}


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

    async def _request_magic_link(request: Request, *, title: str, action: str) -> Response:
        if request.method == "GET":
            return HTMLResponse(_auth_form(title, action, next_path=_safe_next(request)))
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
        email = form.get("email", "")
        if email.strip():
            email_limited = _rate_limit_response(
                request=request,
                limiter=rate_limiter,
                bucket=f"signin-email:{email.strip().lower()}",
                window_seconds=settings.signin_rate_limit_window_seconds,
                max_attempts=settings.signin_rate_limit_max_attempts,
            )
            if email_limited is not None:
                return email_limited
        try:
            magic_link_record, raw_token = services.auth_store.issue_magic_link(
                email=email,
                next_path=next_path,
                ttl_seconds=settings.magic_link_ttl_seconds,
            )
        except ValueError as exc:
            return HTMLResponse(
                _auth_form(
                    title,
                    action,
                    error=str(exc),
                    next_path=next_path,
                    email=email,
                ),
                status_code=400,
            )

        try:
            services.magic_link_email_sender.send_magic_link(
                recipient_email=magic_link_record.email,
                magic_link=_magic_link_url(request, settings=settings, raw_token=raw_token),
                expires_in_minutes=_ttl_minutes(settings.magic_link_ttl_seconds),
            )
        except EmailDeliveryError as exc:
            services.auth_store.delete_magic_link(raw_token)
            return HTMLResponse(
                _auth_form(
                    title,
                    action,
                    error=str(exc),
                    next_path=next_path,
                    email=email,
                ),
                status_code=500,
            )
        return HTMLResponse(
            _magic_link_requested_page(
                email=magic_link_record.email,
                expires_in_minutes=_ttl_minutes(settings.magic_link_ttl_seconds),
            )
        )

    async def sign_up(request: Request) -> Response:
        return await _request_magic_link(request, title="Create account", action="/sign-up")

    async def sign_in(request: Request) -> Response:
        return await _request_magic_link(request, title="Sign in", action="/sign-in")

    async def magic_link(request: Request) -> Response:
        if request.method == "GET":
            raw_token = request.query_params.get("token", "")
            magic_link_record = services.auth_store.get_magic_link(raw_token) if raw_token else None
            if magic_link_record is None:
                return _invalid_magic_link_response()
            return HTMLResponse(
                _magic_link_continue_page(
                    token=raw_token,
                    email=magic_link_record.email,
                    expires_at=magic_link_record.expires_at,
                )
            )
        form = await _parse_form(request)
        consumed = services.auth_store.consume_magic_link(form.get("token", ""))
        if consumed is None:
            return _invalid_magic_link_response()
        return _session_redirect(
            consumed.user.user_id,
            consumed.next_path,
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
        plan = await build_music_discovery_plan(
            choices,
            services=services,
            limit=3,
            language=settings.default_language,
            spotify_connected=spotify is not None,
        )
        return HTMLResponse(
            _finder_page(
                session,
                plan,
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
            return HTMLResponse(_page("Approve MCP access", body, authenticated=True))
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
        Route("/auth/magic-link", endpoint=magic_link, methods=["GET", "POST"]),
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
        authenticated=True,
    )


def _finder_page(
    session: SessionRecord,
    plan: MusicDiscoveryPlan,
    *,
    services: ServiceContainer,
    settings: WaiMusicSettings,
    submitted: bool,
    error: str | None = None,
) -> str:
    result = plan.result
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
        {_source_intelligence_markup(plan.catalogs)}
        {_recommendations_markup(result, workflow_prompt=plan.mcp_prompt)}
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
        <h3>Source coverage</h3>
        <p>{_catalog_summary_markup(plan.catalogs)}</p>
      </div>
    </section>
    {_workflow_panel_markup(plan)}
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
    return _page("Find music", body, authenticated=True)


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


def _source_intelligence_markup(catalogs: list[CatalogSignal]) -> str:
    visible = catalogs[:7]
    return f"""
    <section class="source-strip" aria-label="Source intelligence">
      <div class="source-strip-head">
        <span class="source-marker" aria-hidden="true"></span>
        <div>
          <h3>Source intelligence</h3>
          <p>{escape(str(len([catalog for catalog in catalogs if catalog.status == "active"])))} active catalogs</p>
        </div>
      </div>
      <div class="source-list">
        {"".join(_catalog_pill_markup(catalog) for catalog in visible)}
      </div>
    </section>
    """


def _catalog_pill_markup(catalog: CatalogSignal) -> str:
    return f"""
    <div class="source-pill source-{escape(catalog.status)}">
      <span>{escape(catalog.name)}</span>
      <strong>{escape(_catalog_status_label(catalog.status))}</strong>
    </div>
    """


def _catalog_summary_markup(catalogs: list[CatalogSignal]) -> str:
    active = [catalog.name for catalog in catalogs if catalog.status == "active"]
    planned = [catalog.name for catalog in catalogs if catalog.status == "planned"]
    parts = [f"{len(active)} active"]
    if planned:
        parts.append(f"{len(planned)} planned")
    return escape(" · ".join(parts))


def _workflow_panel_markup(plan: MusicDiscoveryPlan) -> str:
    return f"""
    <section class="workflow-panel" aria-label="MCP workflow">
      <div>
        <div class="workflow-heading">
          <span class="source-marker" aria-hidden="true"></span>
          <div>
            <h3>MCP workflow</h3>
            <p>Source-aware plan for Claude and other MCP clients.</p>
          </div>
        </div>
        <div class="workflow-steps">
          {"".join(_workflow_step_markup(step) for step in plan.workflow_steps[:6])}
        </div>
      </div>
      <div>
        <div class="prompt-title">
          <h3>Prompt</h3>
          <button class="ghost" type="button" data-copy="{escape(plan.mcp_prompt)}">Copy</button>
        </div>
        <div class="prompt-box mono prompt-box-large">{escape(plan.mcp_prompt)}</div>
      </div>
    </section>
    """


def _workflow_step_markup(step: DiscoveryWorkflowStep) -> str:
    tool_label = ", ".join(step.tool_names)
    return f"""
    <div class="workflow-step step-{escape(step.status)}">
      <div>
        <strong>{escape(step.label)}</strong>
        <p>{escape(step.reason)}</p>
      </div>
      <span>{escape(tool_label)}</span>
    </div>
    """


def _catalog_status_label(status: str) -> str:
    labels = {
        "active": "active",
        "available": "ready",
        "planned": "planned",
    }
    return labels.get(status, status)


def _recommendations_markup(result: MusicFinderResult, *, workflow_prompt: str) -> str:
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
        copy_prompt = _candidate_prompt(result, spotify_query, workflow_prompt=workflow_prompt)
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


def _candidate_prompt(result: MusicFinderResult, seed: str, *, workflow_prompt: str) -> str:
    choices = result.choices.model_copy(update={"query": seed, "source": "manual_seed"})
    return "\n".join(
        [
            "Use the wai-music MCP tools to refine this recommendation.",
            f"seed: {seed}",
            workflow_prompt,
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


def _magic_link_url(
    request: Request,
    *,
    settings: WaiMusicSettings,
    raw_token: str,
) -> str:
    base_url = (
        settings.public_base_url.rstrip("/")
        if settings.public_base_url
        else str(request.base_url).rstrip("/")
    )
    return f"{base_url}/auth/magic-link?{urlencode({'token': raw_token})}"


def _ttl_minutes(ttl_seconds: int) -> int:
    return max(1, round(ttl_seconds / 60))


def _magic_link_requested_page(*, email: str, expires_in_minutes: int) -> str:
    body = f"""
    <section class="hero">
      <h1>Check your email</h1>
      <p>
        We sent a sign-in link to <strong>{escape(email)}</strong>. Open it on this device
        and continue within {expires_in_minutes} minutes.
      </p>
      <div class="actions">
        <a class="button secondary" href="/sign-in">Use a different email</a>
      </div>
    </section>
    """
    return _page("Check your email", body)


def _magic_link_continue_page(*, token: str, email: str, expires_at: int) -> str:
    body = f"""
    <section class="hero">
      <h1>Continue sign-in</h1>
      <p>
        Continue to wai-music as <strong>{escape(email)}</strong>. This one-time link expires at
        {escape(_format_unix_ts(expires_at))}.
      </p>
      <form method="post" action="/auth/magic-link">
        <input type="hidden" name="token" value="{escape(token)}" />
        <div class="actions">
          <button type="submit">Continue</button>
          <a class="button secondary" href="/sign-in">Cancel</a>
        </div>
      </form>
    </section>
    """
    return _page("Continue sign-in", body)


def _invalid_magic_link_response() -> HTMLResponse:
    return HTMLResponse(
        _page(
            "Magic link expired",
            """
            <section class="hero">
              <h1>Magic link expired</h1>
              <p>This sign-in link is expired or has already been used.</p>
              <div class="actions">
                <a class="button" href="/sign-in">Request a new link</a>
              </div>
            </section>
            """,
        ),
        status_code=400,
    )


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
        Enter your email and wai-music will send a secure sign-in link. Spotify tokens,
        playlists, and notes stay scoped to the person who opened the link.
      </p>
    </section>
    <section class="card" style="margin-top: 18px;">
      {error_markup}
      <form method="post" action="{escape(action)}">
        <input type="hidden" name="next" value="{escape(next_path)}" />
        <label>Email
          <input type="email" name="email" value="{escape(email)}" autocomplete="email" required />
        </label>
        <div class="actions">
          <button type="submit">Send sign-in link</button>
          <a class="button secondary" href="/">Back</a>
        </div>
      </form>
    </section>
    """
    return _page(title, body)


def _page(title: str, body: str, *, authenticated: bool = False) -> str:
    discover_current = ' aria-current="page"' if title in {"wai-music", "Find music"} else ""
    dashboard_current = ' aria-current="page"' if title == "Dashboard" else ""
    if title in AUTH_PAGE_TITLES:
        top_actions = ""
    elif authenticated:
        top_actions = """
        <form method="post" action="/logout"><button class="secondary" type="submit">Sign out</button></form>
        <a class="button" href="/spotify/connect">Connect Spotify</a>
        """
    else:
        top_actions = """
        <a class="button secondary" href="/sign-in">Sign in</a>
        <a class="button" href="/spotify/connect">Connect Spotify</a>
        """
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
        {top_actions}
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
