from __future__ import annotations

from wai_music.settings import WaiMusicSettings
from wai_music.telemetry import configure_sentry


def test_configure_sentry_is_noop_without_dsn(monkeypatch) -> None:
    settings = WaiMusicSettings()
    captured: list[object] = []

    def fake_init(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr("wai_music.telemetry.sentry_sdk.init", fake_init)

    configure_sentry(settings)

    assert captured == []


def test_configure_sentry_uses_explicit_settings(monkeypatch) -> None:
    monkeypatch.setenv("WAI_MUSIC_SENTRY_DSN", "https://examplePublicKey@o0.ingest.sentry.io/1")
    monkeypatch.setenv("WAI_MUSIC_SENTRY_ENVIRONMENT", "production")
    monkeypatch.setenv("WAI_MUSIC_SENTRY_TRACES_SAMPLE_RATE", "0.25")
    settings = WaiMusicSettings()
    captured: list[dict[str, object]] = []

    def fake_init(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr("wai_music.telemetry.sentry_sdk.init", fake_init)

    configure_sentry(settings)

    assert len(captured) == 1
    assert captured[0]["dsn"] == settings.sentry_dsn
    assert captured[0]["environment"] == "production"
    assert captured[0]["traces_sample_rate"] == 0.25
