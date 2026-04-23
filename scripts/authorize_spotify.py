"""Run a local Spotify OAuth authorization flow and persist the refresh token cache."""

from __future__ import annotations

import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from queue import Queue
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
        redirect_uri=settings.spotify_redirect_uri,
        scope=" ".join(settings.spotify_scopes),
        cache_path=str(settings.spotify_cache_path),
        open_browser=False,
    )
    authorize_url = auth_manager.get_authorize_url()
    redirect = urlparse(settings.spotify_redirect_uri)
    if not redirect.hostname or not redirect.port:
        raise RuntimeError("SPOTIFY_REDIRECT_URI must include host and port")

    queue: Queue[str] = Queue()

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != redirect.path:
                self.send_error(404)
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
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    webbrowser.open(authorize_url)
    print(f"Open this URL if the browser did not launch:\n{authorize_url}\n")
    code = queue.get()
    token_info = auth_manager.get_access_token(code=code, as_dict=True, check_cache=False)
    server.server_close()

    if not token_info.get("refresh_token"):
        raise RuntimeError("Spotify did not return a refresh token")

    print(f"Token cache written to {settings.spotify_cache_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
