# wai-music

`wai-music` is an open-source MCP server and Python toolkit for music discovery, context, and playlist workflows.

It is designed around a simple split of responsibilities:

- host LLMs handle taste, narrative, and recommendation language
- `wai-music` provides canonical metadata, structured stories, backend playback integration, and curated music context

The canonical metadata spine is MusicBrainz. Playback is backend-based from day one, with `SpotifyBackend` implemented in `v0.1`.

## What It Exposes

`wai-music` ships 19 MCP tools:

1. `search`
2. `resolve`
3. `find_music`
4. `plan_music_discovery`
5. `get_artist`
6. `get_release`
7. `get_recording`
8. `get_work`
9. `get_related`
10. `get_artist_story`
11. `get_release_story`
12. `get_recording_story`
13. `get_scene_story`
14. `find_track_on`
15. `create_playlist`
16. `add_tracks_to_playlist`
17. `get_listening_profile`
18. `composition_of_the_day`
19. `save_notes`

Every tool returns Pydantic models. Public models live in `wai_music.models`.

The MCP server also exposes:

- resource `wai-music://catalogs/discovery` for catalog capability, limits, and source status
- prompt `music_discovery_session` for source-aware discovery sessions

## Installation

With `uv`:

```bash
uv sync --extra dev
```

Build distributable artifacts:

```bash
uv build
```

Install the built wheel into an isolated environment:

```bash
uv tool install dist/wai_music-0.1.0-py3-none-any.whl
```

Run the local MCP server in stdio mode:

```bash
uv run wai-music
```

Run the streamable HTTP transport:

```bash
uv run wai-music --http --port 8765
```

This hosted mode now serves both:

- a browser UI (`/`, `/sign-in`, `/dashboard`)
- the MCP endpoint (`/mcp`)

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
WAI_MUSIC_HOST=127.0.0.1
WAI_MUSIC_PORT=8765
WAI_MUSIC_PUBLIC_BASE_URL=
WAI_MUSIC_SECRET_KEY=
WAI_MUSIC_ENABLE_PERSONAL_ACCESS_TOKENS=false
WAI_MUSIC_MAGIC_LINK_FROM_EMAIL=
WAI_MUSIC_MAGIC_LINK_TTL_SECONDS=900
RESEND_API_KEY=

MUSICBRAINZ_USER_AGENT=wai-music/0.1 (+https://github.com/mikwiseman/wai-music)
```

Spotify scopes used by the project:

- `user-library-read`
- `user-top-read`
- `playlist-modify-private`
- `playlist-modify-public`
- `user-read-recently-played`

## Spotify OAuth

From a source checkout, run the local authorization helper:

```bash
uv run python scripts/authorize_spotify.py
```

The script opens the browser, captures the callback on `SPOTIFY_REDIRECT_URI`, exchanges the code, and stores the refresh-token cache at `SPOTIFY_CACHE_PATH`.

For hosted multi-user mode, set:

```dotenv
WAI_MUSIC_PUBLIC_BASE_URL=https://music.waiwai.is
WAI_MUSIC_SECRET_KEY=...
RESEND_API_KEY=...
WAI_MUSIC_MAGIC_LINK_FROM_EMAIL=login@music.waiwai.is
```

and register this Spotify redirect URI:

`https://music.waiwai.is/auth/spotify/callback`

In hosted mode, users sign in through short-lived email magic links, connect Spotify through the web UI, and receive user-scoped MCP access through OAuth.

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

## Hosted Mode

`wai-music` can now run as a hosted multi-user service:

- browser magic-link auth and dashboard
- per-user Spotify connections
- protected MCP endpoint with OAuth
- user-scoped playlist history and notes

For production deployment under `music.waiwai.is`, see [docs/deploy/ubuntu-24.04.md](docs/deploy/ubuntu-24.04.md).

For the hosted end-user and Claude connector flow, see [docs/hosted-users.md](docs/hosted-users.md).

## Claude.ai Connector Flow

For the normal `claude.ai` flow, users do not need a manually generated API key.

Recommended flow:

1. The user enters their email and opens the magic link from `wai-music`.
2. The user connects Spotify in the dashboard.
3. In Claude, the user adds a custom connector pointing to `https://music.waiwai.is/mcp`.
4. Leave Claude's advanced OAuth client settings empty unless you intentionally manage client credentials yourself.
5. Claude discovers the server's OAuth metadata, starts OAuth, and redirects the user back to `wai-music`.
6. The user approves access on `wai-music`, and the server issues user-scoped OAuth tokens to Claude.

That means:

- no shared global API key
- no manual token copy-paste for end users
- each Claude connection is tied to one `wai-music` user
- each `wai-music` user is tied to their own Spotify connection

The hosted server stores Spotify tokens and MCP OAuth tokens separately. Spotify tokens stay on `wai-music` and are encrypted at rest.

For advanced manual testing, the dashboard can also mint revocable personal access tokens when `WAI_MUSIC_ENABLE_PERSONAL_ACCESS_TOKENS=true`. Those are intended for MCP Inspector, `curl`, or clients without OAuth support. For `claude.ai`, prefer the built-in OAuth flow.

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

## Source Catalog Strategy

Current implemented sources:

- MusicBrainz for canonical IDs, relations, tags, releases, recordings, and works
- Wikipedia / Wikidata for story context and factual grounding
- Spotify for user listening profile, playable track search, and playlist writes
- Wai curated data for fast first-pass recommendations and scene anchors

Planned adapter slots:

- ListenBrainz for MBID-first collaborative recommendations
- Last.fm for similar artists and community tags
- Discogs for label, pressing, format, and catalog-number context

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
- implement ListenBrainz, Last.fm, and Discogs adapters behind explicit configuration
- add Apple Music / Deezer / Tidal / Yandex backends
- extend curated scene metadata and anniversary indexing
