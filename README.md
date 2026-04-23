# wai-music

`wai-music` is an open-source MCP server and Python toolkit for music discovery, context, and playlist workflows.

It is designed around a simple split of responsibilities:

- host LLMs handle taste, narrative, and recommendation language
- `wai-music` provides canonical metadata, structured stories, backend playback integration, and curated music context

The canonical metadata spine is MusicBrainz. Playback is backend-based from day one, with `SpotifyBackend` implemented in `v0.1`.

## What It Exposes

`wai-music` ships 17 MCP tools:

1. `search`
2. `resolve`
3. `get_artist`
4. `get_release`
5. `get_recording`
6. `get_work`
7. `get_related`
8. `get_artist_story`
9. `get_release_story`
10. `get_recording_story`
11. `get_scene_story`
12. `find_track_on`
13. `create_playlist`
14. `add_tracks_to_playlist`
15. `get_listening_profile`
16. `composition_of_the_day`
17. `save_notes`

Every tool returns Pydantic models. Public models live in `wai_music.models`.

## Installation

With `uv`:

```bash
uv sync --extra dev
```

Run the local MCP server in stdio mode:

```bash
uv run wai-music
```

Run the streamable HTTP transport:

```bash
uv run wai-music --http --port 8765
```

## Environment

Create `.env` from `.env.example` and fill at least the Spotify values if you want playback tools:

```dotenv
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback
SPOTIFY_CACHE_PATH=~/.config/wai-music/spotify_token.json

WAI_MUSIC_DB_PATH=~/.config/wai-music/cache.sqlite
WAI_MUSIC_PLAYLISTS_DIR=./playlists
WAI_MUSIC_DEFAULT_LANGUAGE=en

MUSICBRAINZ_USER_AGENT=wai-music/0.1 (+https://github.com/mikwiseman/wai-music)
```

Spotify scopes used by the project:

- `user-library-read`
- `user-top-read`
- `playlist-modify-private`
- `playlist-modify-public`
- `user-read-recently-played`

## Spotify OAuth

Run the local authorization helper:

```bash
uv run python scripts/authorize_spotify.py
```

The script opens the browser, captures the callback on `SPOTIFY_REDIRECT_URI`, exchanges the code, and stores the refresh-token cache at `SPOTIFY_CACHE_PATH`.

## Claude Code / MCP Setup

Example `.mcp.json` entry:

```json
{
  "mcpServers": {
    "wai-music": {
      "command": "uv",
      "args": ["run", "wai-music"],
      "cwd": "/absolute/path/to/wai-music"
    }
  }
}
```

For HTTP-based clients:

```bash
uv run wai-music --http --port 8765
```

Then point the client to `http://127.0.0.1:8765/mcp`.

## Example Prompts

- "Find the artist Rachmaninoff and tell me the story behind Piano Concerto No. 2."
- "Give me a composition of the day in `scene_dive` mode."
- "Find a Spotify recording of `Blue in Green` and create a private playlist."
- "Summarize my current Spotify listening profile."

## Python API

Third-party code can import the public models directly:

```python
from wai_music.models import Entity, Story, TrackMatch, PlaylistRef
```

All public models generate JSON Schema cleanly via `.model_json_schema()`.

## Curated Data

The package includes starter curated data under `src/wai_music/data/`:

- `scenes.json`
- `must_hear.json`
- `seasonal_tags.json`

The data is intentionally editable and expandable. Some starter `must_hear` entries are seeded without verified MBIDs yet; the file format is stable so the editorial dataset can be tightened without changing tool interfaces.

## Development

Static checks:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/
```

Tests:

```bash
uv run pytest tests/ -v
uv run pytest tests/ --cov=src/wai_music --cov-report=term-missing
```

Smoke flow:

```bash
uv run python scripts/smoke_test.py
```

## Adding a Backend

Implement the `PlaybackBackend` protocol in [`src/wai_music/backends/base.py`](src/wai_music/backends/base.py), register the backend in `create_services()`, and keep tool code backend-agnostic. Tool modules should not know backend-specific APIs.

## Roadmap

- verify and expand curated MBIDs in `must_hear.json`
- add richer MusicBrainz relation traversal for releases and works
- add Apple Music / Deezer / Tidal / Yandex backends
- extend curated scene metadata and anniversary indexing
