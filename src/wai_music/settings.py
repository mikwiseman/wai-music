"""Application settings."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class WaiMusicSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    spotify_client_id: str | None = Field(default=None, alias="SPOTIFY_CLIENT_ID")
    spotify_client_secret: str | None = Field(default=None, alias="SPOTIFY_CLIENT_SECRET")
    spotify_redirect_uri: str = Field(
        default="http://127.0.0.1:8888/callback",
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

    @field_validator("spotify_cache_path", "db_path", "playlists_dir", mode="before")
    @classmethod
    def expand_paths(cls, value: object) -> object:
        if isinstance(value, Path):
            return value.expanduser()
        if isinstance(value, str):
            return Path(value).expanduser()
        return value

    @property
    def spotify_scopes(self) -> list[str]:
        return [
            "user-library-read",
            "user-top-read",
            "playlist-modify-private",
            "playlist-modify-public",
            "user-read-recently-played",
        ]

    def ensure_runtime_dirs(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.spotify_cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.playlists_dir.mkdir(parents=True, exist_ok=True)
