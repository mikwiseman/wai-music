"""Service container for the wai-music application."""

from __future__ import annotations

from dataclasses import dataclass, field
from inspect import isawaitable

from wai_music.aggregator import EntityAggregator
from wai_music.auth.magic_email import MagicLinkEmailSender, ResendMagicLinkEmailSender
from wai_music.auth.store import SQLiteAuthStore
from wai_music.backends.base import BackendRegistry
from wai_music.backends.spotify import SpotifyBackend
from wai_music.cache import SQLiteCache
from wai_music.settings import WaiMusicSettings
from wai_music.sources.musicbrainz import MusicBrainzSource
from wai_music.sources.wikipedia import WikipediaSource


@dataclass
class ServiceContainer:
    settings: WaiMusicSettings
    cache: SQLiteCache
    auth_store: SQLiteAuthStore
    musicbrainz: MusicBrainzSource
    wikipedia: WikipediaSource
    aggregator: EntityAggregator
    backends: BackendRegistry
    magic_link_email_sender: MagicLinkEmailSender
    _closed: bool = field(default=False, init=False, repr=False)

    async def close(self) -> None:
        if self._closed:
            return
        errors: list[Exception] = []
        closers = [self.musicbrainz.close, self.wikipedia.close]
        for backend_name in self.backends.names():
            backend = self.backends.get(backend_name)
            backend_close = getattr(backend, "close", None)
            if callable(backend_close):
                closers.append(backend_close)

        for close in closers:
            try:
                result = close()
                if isawaitable(result):
                    await result
            except Exception as exc:
                errors.append(exc)

        if errors:
            raise ExceptionGroup("failed to close wai-music services", errors)
        self._closed = True


def create_services(settings: WaiMusicSettings | None = None) -> ServiceContainer:
    configured = settings or WaiMusicSettings()
    configured.ensure_runtime_dirs()
    cache = SQLiteCache(configured.db_path)
    auth_store = SQLiteAuthStore(configured.db_path, secret_key=configured.effective_secret_key)
    musicbrainz = MusicBrainzSource(settings=configured, cache=cache)
    wikipedia = WikipediaSource(settings=configured, cache=cache)
    aggregator = EntityAggregator(musicbrainz, wikipedia)
    backends = BackendRegistry()
    backends.register(SpotifyBackend(configured, auth_store=auth_store))
    magic_link_email_sender = ResendMagicLinkEmailSender(
        api_key=configured.resend_api_key,
        from_email=configured.magic_link_from_email,
    )
    return ServiceContainer(
        settings=configured,
        cache=cache,
        auth_store=auth_store,
        musicbrainz=musicbrainz,
        wikipedia=wikipedia,
        aggregator=aggregator,
        backends=backends,
        magic_link_email_sender=magic_link_email_sender,
    )
