from wai_music.settings import WaiMusicSettings


def test_settings_expand_paths(monkeypatch) -> None:
    monkeypatch.setenv("WAI_MUSIC_DB_PATH", "~/cache.sqlite")
    monkeypatch.setenv("SPOTIFY_CACHE_PATH", "~/spotify.json")
    settings = WaiMusicSettings()
    assert str(settings.db_path).endswith("cache.sqlite")
    assert str(settings.spotify_cache_path).endswith("spotify.json")
