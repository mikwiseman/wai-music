"""Service container for the wai-music application."""

from __future__ import annotations

from dataclasses import dataclass

from wai_music.aggregator import EntityAggregator
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
    musicbrainz: MusicBrainzSource
    wikipedia: WikipediaSource
    aggregator: EntityAggregator
    backends: BackendRegistry

    async def close(self) -> None:
        await self.musicbrainz.close()
        await self.wikipedia.close()


def create_services(settings: WaiMusicSettings | None = None) -> ServiceContainer:
    configured = settings or WaiMusicSettings()
    configured.ensure_runtime_dirs()
    cache = SQLiteCache(configured.db_path)
    musicbrainz = MusicBrainzSource(settings=configured, cache=cache)
    wikipedia = WikipediaSource(settings=configured, cache=cache)
    aggregator = EntityAggregator(musicbrainz, wikipedia)
    backends = BackendRegistry()
    backends.register(SpotifyBackend(configured))
    return ServiceContainer(
        settings=configured,
        cache=cache,
        musicbrainz=musicbrainz,
        wikipedia=wikipedia,
        aggregator=aggregator,
        backends=backends,
    )
