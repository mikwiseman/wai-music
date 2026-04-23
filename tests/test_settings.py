from wai_music.settings import WaiMusicSettings


def test_settings_expand_paths(monkeypatch) -> None:
    monkeypatch.setenv("WAI_MUSIC_DB_PATH", "~/cache.sqlite")
    monkeypatch.setenv("SPOTIFY_CACHE_PATH", "~/spotify.json")
    monkeypatch.setenv("WAI_MUSIC_DEFAULT_LANGUAGE", "ru")
    settings = WaiMusicSettings()
    assert str(settings.db_path).endswith("cache.sqlite")
    assert str(settings.spotify_cache_path).endswith("spotify.json")
    assert settings.default_language == "ru"


def test_settings_reject_unsupported_default_language(monkeypatch) -> None:
    monkeypatch.setenv("WAI_MUSIC_DEFAULT_LANGUAGE", "de")

    try:
        WaiMusicSettings()
    except ValueError as exc:
        assert "unsupported language" in str(exc)
    else:
        raise AssertionError("expected unsupported default language to fail")
