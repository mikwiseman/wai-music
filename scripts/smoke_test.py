"""End-to-end smoke flow for wai-music."""

from __future__ import annotations

import asyncio
from textwrap import dedent

from wai_music.models import EntityType
from wai_music.services import create_services
from wai_music.tools.artifacts import save_markdown_notes
from wai_music.tools.playback import create_backend_playlist, find_track


async def main() -> int:
    services = create_services()
    try:
        artists = await services.aggregator.search_entities(
            "Rachmaninoff", EntityType.ARTIST, limit=1
        )
        if not artists:
            raise RuntimeError("Rachmaninoff artist search returned no results")
        artist = artists[0]
        if not artist.mbid:
            raise RuntimeError("Resolved artist does not have an MBID")

        artist_entity = await services.aggregator.aggregate_entity(artist.mbid, EntityType.ARTIST)
        works = await services.aggregator.search_entities(
            "Piano Concerto no. 2 in C minor, op. 18",
            EntityType.WORK,
            limit=5,
        )
        target_work = next(
            (work for work in works if "Piano Concerto" in work.name),
            None,
        )
        if target_work is None:
            raise RuntimeError("Could not find Piano Concerto no. 2 work")

        track_matches = await find_track(
            "spotify",
            f"{artist_entity.name} Piano Concerto no. 2 Adagio",
            services=services,
        )
        if not track_matches:
            raise RuntimeError("Spotify backend did not return a matching track")

        playlist = await create_backend_playlist(
            "spotify",
            "wai-music smoke test",
            "Rachmaninoff smoke playlist",
            [track_matches[0].track_id],
            services=services,
        )
        notes = save_markdown_notes(
            "rachmaninoff-smoke-test",
            dedent(
                f"""
                # wai-music smoke test

                Artist: {artist_entity.name}
                Work: {target_work.name}
                Track: {track_matches[0].name}
                Playlist: {playlist.playlist.url or playlist.playlist.playlist_id}
                """
            ).strip(),
            services=services,
            entities=[artist_entity, target_work],
        )

        print(f"Rachmaninoff MBID: {artist_entity.mbid}")
        print(f"Resolved work: {target_work.name}")
        print(f"Spotify URI: {track_matches[0].uri or track_matches[0].track_id}")
        print(f"Playlist URL: {playlist.playlist.url or playlist.playlist.playlist_id}")
        print(f"Notes path: {notes.path}")
        return 0
    finally:
        await services.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
