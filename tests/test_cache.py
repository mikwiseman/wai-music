from wai_music.cache import SQLiteCache


def test_cache_roundtrip(tmp_db_path) -> None:
    cache = SQLiteCache(tmp_db_path)
    cache.set_json("https://example.com", {"ok": True}, ttl_seconds=60)

    payload = cache.get_json("https://example.com")

    assert payload == {"ok": True}


def test_playlist_history(tmp_db_path) -> None:
    cache = SQLiteCache(tmp_db_path)
    cache.record_playlist(backend="spotify", playlist_id="playlist-1", slug="rachmaninov")

    entries = cache.list_playlists()

    assert len(entries) == 1
    assert entries[0]["backend"] == "spotify"
