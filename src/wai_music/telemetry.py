"""Telemetry and error reporting."""

from __future__ import annotations

import importlib.metadata
import logging

import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration

from wai_music.settings import WaiMusicSettings


def configure_sentry(settings: WaiMusicSettings) -> None:
    if not settings.sentry_dsn:
        return
    logging_integration = LoggingIntegration(
        level=logging.INFO,
        sentry_logs_level=logging.INFO,
        event_level=logging.ERROR,
    )
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.effective_sentry_environment,
        release=_release_name(),
        integrations=[logging_integration],
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
        enable_logs=True,
    )


def _release_name() -> str:
    return f"wai-music@{importlib.metadata.version('wai-music')}"
