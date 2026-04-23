"""Authentication and multi-user support for hosted wai-music."""

from wai_music.auth.current import current_user_id
from wai_music.auth.oauth import WaiAccessToken, WaiOAuthProvider, build_auth_settings
from wai_music.auth.store import SQLiteAuthStore

__all__ = [
    "SQLiteAuthStore",
    "WaiAccessToken",
    "WaiOAuthProvider",
    "build_auth_settings",
    "current_user_id",
]
