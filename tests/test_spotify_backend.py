from __future__ import annotations

from wai_music.backends.spotify import _allow_track_item, _looks_classical
from wai_music.models import TrackQuery


def test_classical_heuristics_filter_compilations() -> None:
    query = TrackQuery(query="Piano Concerto no. 2 adagio")
    assert _looks_classical(query.query or "", query) is True

    compilation = {
        "album": {"name": "Relaxing Classical Moods"},
        "duration_ms": 300000,
    }
    short_track = {
        "album": {"name": "Rachmaninoff Concerto"},
        "duration_ms": 60000,
    }
    valid = {
        "album": {"name": "Rachmaninoff: Piano Concertos"},
        "duration_ms": 600000,
    }

    assert _allow_track_item(compilation, classical=True) is False
    assert _allow_track_item(short_track, classical=True) is False
    assert _allow_track_item(valid, classical=True) is True
