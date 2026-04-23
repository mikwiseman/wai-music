"""Run a local Spotify OAuth authorization flow and persist the refresh token cache."""

from __future__ import annotations

import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from queue import Empty, Queue
from urllib.parse import parse_qs, urlparse

from spotipy.oauth2 import SpotifyOAuth

from wai_music.settings import WaiMusicSettings


def main() -> int:
    settings = WaiMusicSettings()
    settings.ensure_runtime_dirs()
    if not settings.spotify_client_id or not settings.spotify_client_secret:
        raise RuntimeError("Spotify credentials are not configured in the environment")

    auth_manager = SpotifyOAuth(
        client_id=settings.spotify_client_id,
        client_secret=settings.spotify_client_secret,
        redirect_uri=settings.effective_spotify_redirect_uri,
        scope=" ".join(settings.spotify_scopes),
        cache_path=str(settings.spotify_cache_path),
        open_browser=False,
    )
    expected_state = secrets.token_urlsafe(32)
    authorize_url = auth_manager.get_authorize_url(state=expected_state)
    redirect = urlparse(settings.effective_spotify_redirect_uri)
    if not redirect.hostname or not redirect.port:
        raise RuntimeError("SPOTIFY_REDIRECT_URI must include host and port")

    queue: Queue[str] = Queue()

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != redirect.path:
                self.send_error(404)
                return
            state = parse_qs(parsed.query).get("state", [None])[0]
            if state != expected_state:
                self.send_error(400, "Invalid OAuth state")
                return
            code = parse_qs(parsed.query).get("code", [None])[0]
            if code is None:
                self.send_error(400, "Missing authorization code")
                return
            queue.put(code)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Spotify authorization captured. You can close this tab.")

        def log_message(self, format: str, *args: object) -> None:
            return

    server = HTTPServer((redirect.hostname, redirect.port), CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    webbrowser.open(authorize_url)
    print(f"Open this URL if the browser did not launch:\n{authorize_url}\n")
    try:
        code = queue.get(timeout=300)
    except Empty as exc:
        raise TimeoutError("Timed out waiting for Spotify OAuth callback") from exc
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)

    token_info = auth_manager.get_access_token(code=code, as_dict=True, check_cache=False)

    if not token_info.get("refresh_token"):
        raise RuntimeError("Spotify did not return a refresh token")

    print(f"Token cache written to {settings.spotify_cache_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
