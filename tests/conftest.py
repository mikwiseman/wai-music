from pathlib import Path

import pytest

from wai_music.settings import WaiMusicSettings


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "cache.sqlite"


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> WaiMusicSettings:
    monkeypatch.setenv("WAI_MUSIC_DB_PATH", str(tmp_path / "cache.sqlite"))
    monkeypatch.setenv("SPOTIFY_CACHE_PATH", str(tmp_path / "spotify.json"))
    monkeypatch.setenv("WAI_MUSIC_PLAYLISTS_DIR", str(tmp_path / "playlists"))
    return WaiMusicSettings()


@pytest.fixture(scope="session")
def vcr_cassette_dir() -> str:
    return str(Path(__file__).parent / "fixtures" / "vcr")


@pytest.fixture(scope="session")
def vcr_config() -> dict[str, object]:
    return {"filter_headers": ["authorization"], "record_mode": "once"}
