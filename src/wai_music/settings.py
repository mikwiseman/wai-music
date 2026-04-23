"""Application settings."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from wai_music.languages import validate_language

DEFAULT_LOCAL_SPOTIFY_REDIRECT_URI = "http://127.0.0.1:8888/callback"


class WaiMusicSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    spotify_client_id: str | None = Field(default=None, alias="SPOTIFY_CLIENT_ID")
    spotify_client_secret: str | None = Field(default=None, alias="SPOTIFY_CLIENT_SECRET")
    spotify_redirect_uri: str = Field(
        default=DEFAULT_LOCAL_SPOTIFY_REDIRECT_URI,
        alias="SPOTIFY_REDIRECT_URI",
    )
    spotify_cache_path: Path = Field(
        default=Path("~/.config/wai-music/spotify_token.json"),
        alias="SPOTIFY_CACHE_PATH",
    )
    db_path: Path = Field(
        default=Path("~/.config/wai-music/cache.sqlite"),
        alias="WAI_MUSIC_DB_PATH",
    )
    playlists_dir: Path = Field(default=Path("./playlists"), alias="WAI_MUSIC_PLAYLISTS_DIR")
    default_language: str = Field(default="en", alias="WAI_MUSIC_DEFAULT_LANGUAGE")
    musicbrainz_user_agent: str = Field(
        default="wai-music/0.1 (+https://github.com/mikwiseman/wai-music)",
        alias="MUSICBRAINZ_USER_AGENT",
    )
    http_timeout_seconds: float = 10.0
    musicbrainz_rate_limit_per_second: float = 1.0
    host: str = Field(default="127.0.0.1", alias="WAI_MUSIC_HOST")
    port: int = Field(default=8765, alias="WAI_MUSIC_PORT")
    public_base_url: str | None = Field(default=None, alias="WAI_MUSIC_PUBLIC_BASE_URL")
    secret_key: str | None = Field(default=None, alias="WAI_MUSIC_SECRET_KEY")
    session_cookie_name: str = Field(default="wai_music_session", alias="WAI_MUSIC_SESSION_COOKIE")
    session_ttl_seconds: int = Field(
        default=60 * 60 * 24 * 30, alias="WAI_MUSIC_SESSION_TTL_SECONDS"
    )
    oauth_access_token_ttl_seconds: int = Field(
        default=60 * 60,
        alias="WAI_MUSIC_OAUTH_ACCESS_TOKEN_TTL_SECONDS",
    )
    oauth_refresh_token_ttl_seconds: int = Field(
        default=60 * 60 * 24 * 90,
        alias="WAI_MUSIC_OAUTH_REFRESH_TOKEN_TTL_SECONDS",
    )
    oauth_auth_request_ttl_seconds: int = Field(
        default=60 * 10,
        alias="WAI_MUSIC_OAUTH_AUTH_REQUEST_TTL_SECONDS",
    )
    oauth_authorization_code_ttl_seconds: int = Field(
        default=60 * 5,
        alias="WAI_MUSIC_OAUTH_AUTHORIZATION_CODE_TTL_SECONDS",
    )
    enable_personal_access_tokens: bool = Field(
        default=False,
        alias="WAI_MUSIC_ENABLE_PERSONAL_ACCESS_TOKENS",
    )
    personal_access_token_ttl_seconds: int = Field(
        default=60 * 60 * 24 * 30,
        alias="WAI_MUSIC_PERSONAL_ACCESS_TOKEN_TTL_SECONDS",
    )
    signup_rate_limit_window_seconds: int = Field(
        default=60 * 15,
        alias="WAI_MUSIC_SIGNUP_RATE_LIMIT_WINDOW_SECONDS",
    )
    signup_rate_limit_max_attempts: int = Field(
        default=5,
        alias="WAI_MUSIC_SIGNUP_RATE_LIMIT_MAX_ATTEMPTS",
    )
    signin_rate_limit_window_seconds: int = Field(
        default=60 * 15,
        alias="WAI_MUSIC_SIGNIN_RATE_LIMIT_WINDOW_SECONDS",
    )
    signin_rate_limit_max_attempts: int = Field(
        default=10,
        alias="WAI_MUSIC_SIGNIN_RATE_LIMIT_MAX_ATTEMPTS",
    )
    personal_access_token_rate_limit_window_seconds: int = Field(
        default=60 * 60,
        alias="WAI_MUSIC_PERSONAL_ACCESS_TOKEN_RATE_LIMIT_WINDOW_SECONDS",
    )
    personal_access_token_rate_limit_max_attempts: int = Field(
        default=5,
        alias="WAI_MUSIC_PERSONAL_ACCESS_TOKEN_RATE_LIMIT_MAX_ATTEMPTS",
    )
    spotify_oauth_state_ttl_seconds: int = Field(
        default=60 * 10,
        alias="WAI_MUSIC_SPOTIFY_OAUTH_STATE_TTL_SECONDS",
    )
    sentry_dsn: str | None = Field(default=None, alias="WAI_MUSIC_SENTRY_DSN")
    sentry_environment: str | None = Field(default=None, alias="WAI_MUSIC_SENTRY_ENVIRONMENT")
    sentry_traces_sample_rate: float = Field(
        default=0.0,
        alias="WAI_MUSIC_SENTRY_TRACES_SAMPLE_RATE",
    )

    @field_validator("spotify_cache_path", "db_path", "playlists_dir", mode="before")
    @classmethod
    def expand_paths(cls, value: object) -> object:
        if isinstance(value, Path):
            return value.expanduser()
        if isinstance(value, str):
            return Path(value).expanduser()
        return value

    @field_validator("default_language")
    @classmethod
    def validate_default_language(cls, value: str) -> str:
        return validate_language(value)

    @property
    def spotify_scopes(self) -> list[str]:
        return [
            "user-library-read",
            "user-top-read",
            "playlist-modify-private",
            "playlist-modify-public",
            "user-read-recently-played",
        ]

    @property
    def effective_spotify_redirect_uri(self) -> str:
        if self.public_base_url and self.spotify_redirect_uri == DEFAULT_LOCAL_SPOTIFY_REDIRECT_URI:
            return f"{self.public_base_url.rstrip('/')}/auth/spotify/callback"
        return self.spotify_redirect_uri

    @property
    def oauth_enabled(self) -> bool:
        return self.public_base_url is not None

    @property
    def effective_secret_key(self) -> str:
        if self.secret_key:
            return self.secret_key
        return "wai-music-development-secret-key"

    @property
    def cookie_secure(self) -> bool:
        return bool(self.public_base_url and self.public_base_url.startswith("https://"))

    @property
    def public_host(self) -> str | None:
        if not self.public_base_url:
            return None
        parsed = urlparse(self.public_base_url)
        return parsed.netloc or None

    @property
    def allowed_hosts(self) -> list[str]:
        if not self.public_host:
            return [self.host, f"{self.host}:{self.port}"]
        return [self.public_host]

    @property
    def allowed_origins(self) -> list[str]:
        if not self.public_base_url:
            return [f"http://{self.host}:{self.port}"]
        return [self.public_base_url]

    @property
    def oauth_issuer_url(self) -> str | None:
        return self.public_base_url

    @property
    def oauth_resource_server_url(self) -> str | None:
        if not self.public_base_url:
            return None
        return f"{self.public_base_url.rstrip('/')}/mcp"

    @property
    def oauth_required_scopes(self) -> list[str]:
        return ["mcp:tools"]

    @property
    def effective_sentry_environment(self) -> str:
        if self.sentry_environment:
            return self.sentry_environment
        return "production" if self.public_base_url else "development"

    def ensure_runtime_dirs(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.spotify_cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.playlists_dir.mkdir(parents=True, exist_ok=True)
