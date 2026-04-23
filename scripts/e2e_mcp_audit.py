"""Live MCP contract audit for all wai-music tools."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from wai_music.server import build_server
from wai_music.services import create_services
from wai_music.settings import WaiMusicSettings


async def call_tool(server, name: str, arguments: dict[str, Any]) -> Any:
    _blocks, structured = await server.call_tool(name, arguments)
    if not isinstance(structured, dict):
        raise RuntimeError(f"tool {name!r} did not return structured output")
    return structured.get("result", structured)


async def main() -> int:
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    base_settings = WaiMusicSettings()
    with TemporaryDirectory(prefix="wai-music-audit-") as tmpdir:
        root = Path(tmpdir)
        settings = base_settings.model_copy(
            update={
                "db_path": root / "audit.sqlite",
                "playlists_dir": root / "playlists",
            }
        )
        services = create_services(settings)
        server = build_server(services, settings=settings)
        try:
            artist_results = await call_tool(
                server,
                "search",
                {"query": "Rachmaninoff", "type": "artist", "limit": 1},
            )
            release_results = await call_tool(
                server,
                "search",
                {"query": "Kind of Blue", "type": "release", "limit": 1},
            )
            recording_results = await call_tool(
                server,
                "search",
                {"query": "Blue in Green Miles Davis", "type": "recording", "limit": 1},
            )
            work_results = await call_tool(
                server,
                "search",
                {
                    "query": "Piano Concerto no. 2 in C minor, op. 18",
                    "type": "work",
                    "limit": 1,
                },
            )

            if not artist_results or not release_results or not recording_results or not work_results:
                raise RuntimeError("search tools did not return the required entity seeds")

            artist = artist_results[0]
            release = release_results[0]
            recording = recording_results[0]
            work = work_results[0]
            for label, entity in {
                "artist": artist,
                "release": release,
                "recording": recording,
                "work": work,
            }.items():
                if not entity.get("mbid"):
                    raise RuntimeError(f"{label} search result did not include an MBID")

            playlist_tracks = await call_tool(
                server,
                "find_track_on",
                {"backend": "spotify", "query_or_entity": "Miles Davis Blue in Green"},
            )
            if not playlist_tracks:
                raise RuntimeError("find_track_on did not return any Spotify matches")
            track_id = playlist_tracks[0]["track_id"]
            playlist = await call_tool(
                server,
                "create_playlist",
                {
                    "backend": "spotify",
                    "name": f"wai-music audit {stamp}",
                    "description": "Full MCP contract audit",
                    "track_ids": [track_id],
                    "public": False,
                },
            )
            added_tracks = await call_tool(
                server,
                "add_tracks_to_playlist",
                {
                    "backend": "spotify",
                    "playlist_id": playlist["playlist"]["playlist_id"],
                    "track_ids": [track_id],
                },
            )

            notes = await call_tool(
                server,
                "save_notes",
                {
                    "slug": f"audit-{stamp}",
                    "markdown": "# Audit\n\nFull MCP contract audit run.",
                },
            )

            audit_results = {
                "search": {
                    "artist": artist["mbid"],
                    "release": release["mbid"],
                    "recording": recording["mbid"],
                    "work": work["mbid"],
                },
                "resolve": await call_tool(server, "resolve", {"identifier": artist["mbid"]}),
                "get_artist": await call_tool(server, "get_artist", {"mbid": artist["mbid"]}),
                "get_release": await call_tool(server, "get_release", {"mbid": release["mbid"]}),
                "get_recording": await call_tool(server, "get_recording", {"mbid": recording["mbid"]}),
                "get_work": await call_tool(server, "get_work", {"mbid": work["mbid"]}),
                "get_related": await call_tool(server, "get_related", {"mbid": artist["mbid"]}),
                "get_artist_story": await call_tool(
                    server,
                    "get_artist_story",
                    {"mbid": artist["mbid"], "language": "en"},
                ),
                "get_release_story": await call_tool(
                    server,
                    "get_release_story",
                    {"mbid": release["mbid"], "language": "en"},
                ),
                "get_recording_story": await call_tool(
                    server,
                    "get_recording_story",
                    {"mbid": recording["mbid"], "language": "en"},
                ),
                "get_scene_story": await call_tool(
                    server,
                    "get_scene_story",
                    {"scene_key": "detroit-techno", "language": "en"},
                ),
                "find_track_on": playlist_tracks,
                "create_playlist": playlist,
                "add_tracks_to_playlist": added_tracks,
                "get_listening_profile": await call_tool(
                    server,
                    "get_listening_profile",
                    {"backend": "spotify", "time_range": "medium_term"},
                ),
                "composition_of_the_day": await call_tool(
                    server,
                    "composition_of_the_day",
                    {"mode": "scene_dive", "date": date.today().isoformat(), "language": "en"},
                ),
                "save_notes": notes,
            }

            for tool_name, result in audit_results.items():
                if isinstance(result, dict):
                    summary = ", ".join(sorted(result.keys())[:4])
                elif isinstance(result, list):
                    summary = f"{len(result)} items"
                else:
                    summary = str(result)
                print(f"{tool_name}: {summary}")
            return 0
        finally:
            await services.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
