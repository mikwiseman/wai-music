from wai_music.settings import WaiMusicSettings


def test_settings_expand_paths(monkeypatch) -> None:
    monkeypatch.setenv("WAI_MUSIC_DB_PATH", "~/cache.sqlite")
    monkeypatch.setenv("SPOTIFY_CACHE_PATH", "~/spotify.json")
    monkeypatch.setenv("WAI_MUSIC_DEFAULT_LANGUAGE", "ru")
    settings = WaiMusicSettings()
    assert str(settings.db_path).endswith("cache.sqlite")
    assert str(settings.spotify_cache_path).endswith("spotify.json")
    assert settings.default_language == "ru"


def test_settings_read_magic_link_email_configuration(monkeypatch) -> None:
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("WAI_MUSIC_MAGIC_LINK_FROM_EMAIL", "login@example.com")
    monkeypatch.setenv("WAI_MUSIC_MAGIC_LINK_TTL_SECONDS", "600")

    settings = WaiMusicSettings()

    assert settings.resend_api_key == "re_test"
    assert settings.magic_link_from_email == "login@example.com"
    assert settings.magic_link_ttl_seconds == 600


def test_settings_reject_unsupported_default_language(monkeypatch) -> None:
    monkeypatch.setenv("WAI_MUSIC_DEFAULT_LANGUAGE", "de")

    try:
        WaiMusicSettings()
    except ValueError as exc:
        assert "unsupported language" in str(exc)
    else:
        raise AssertionError("expected unsupported default language to fail")
