from typing import Dict, List, Optional, Tuple

Song = Dict[str, object]
PlaylistMap = Dict[str, List[Song]]

DEFAULT_PROFILE = {
    "name": "Default",
    "hype_min_energy": 7,
    "chill_max_energy": 3,
    "favorite_genre": "rock",
    "include_mixed": True,
}


def normalize_title(title: str) -> str:
    """Normalize a song title for comparisons."""
    if not isinstance(title, str):
        return ""
    return title.strip()


def normalize_artist(artist: str) -> str:
    """Normalize an artist name for comparisons."""
    if not artist:
        return ""
    return artist.strip().lower()


def normalize_genre(genre: str) -> str:
    """Normalize a genre name for comparisons."""
    return genre.lower().strip()


def normalize_song(raw: Song) -> Song:
    """Return a normalized song dict with expected keys."""
    title = normalize_title(str(raw.get("title", "")))
    artist = normalize_artist(str(raw.get("artist", "")))
    genre = normalize_genre(str(raw.get("genre", "")))
    energy = raw.get("energy", 0)

    if isinstance(energy, str):
        try:
            energy = int(energy)
        except ValueError:
            energy = 0

    tags = raw.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]

    return {
        "title": title,
        "artist": artist,
        "genre": genre,
        "energy": energy,
        "tags": tags,
    }


def classify_song(song: Song, profile: Dict[str, object]) -> str:
    """Return a mood label given a song and user profile.

    The original implementation looked for chill keywords in the *title* rather
    than the genre, which meant tracks with a chill genre would not be picked up
    unless the genre also matched one of the keywords.  This was surprising when
    songs like "Lo-fi Rain" (genre "lofi") were not classified as Chill because
    the word "lofi" wasn't in the title.  Examples in the UI could end up in
    Mixed even though the genre clearly belonged in Chill, which felt off to
    users.

    The fix simply checks the genre for both hype and chill keywords so that the
    logic is consistent.
    """
    energy = song.get("energy", 0)
    genre = song.get("genre", "")
    title = song.get("title", "")

    hype_min_energy = profile.get("hype_min_energy", 7)
    chill_max_energy = profile.get("chill_max_energy", 3)
    favorite_genre = profile.get("favorite_genre", "")

    hype_keywords = ["rock", "punk", "party"]
    chill_keywords = ["lofi", "ambient", "sleep"]

    is_hype_keyword = any(k in genre for k in hype_keywords)
    # corrected field for chill keywords
    is_chill_keyword = any(k in genre for k in chill_keywords)

    if genre == favorite_genre or energy >= hype_min_energy or is_hype_keyword:
        return "Hype"
    if energy <= chill_max_energy or is_chill_keyword:
        return "Chill"
    return "Mixed"


def build_playlists(songs: List[Song], profile: Dict[str, object]) -> PlaylistMap:
    """Group songs into playlists based on mood and profile."""
    playlists: PlaylistMap = {
        "Hype": [],
        "Chill": [],
        "Mixed": [],
    }

    for song in songs:
        normalized = normalize_song(song)
        mood = classify_song(normalized, profile)
        normalized["mood"] = mood
        playlists[mood].append(normalized)

    return playlists


def merge_playlists(a: PlaylistMap, b: PlaylistMap) -> PlaylistMap:
    """Merge two playlist maps into a new map."""
    merged: PlaylistMap = {}
    for key in set(list(a.keys()) + list(b.keys())):
        merged[key] = a.get(key, [])
        merged[key].extend(b.get(key, []))
    return merged


def compute_playlist_stats(playlists: PlaylistMap) -> Dict[str, object]:
    """Compute statistics across all playlists.

    The previous implementation had two incorrect calculations:

    * `hype_ratio` was computed as `len(hype) / len(hype)` (always 1.0 when any
      hype songs existed) because the `total` variable was accidentally set to
      the length of the hype list instead of the total number of songs.
    * `avg_energy` summed only the energies of hype songs but then divided by the
      number of *all* songs, producing a value that was much lower than any
      individual track energy when there were non-hype songs.

    Both of these led to confusing metrics in the UI; the ratio should reflect
    how many of the tracks are hype versus the full collection, and the average
    energy should be the mean energy across all songs, not just one bucket.
    """
    all_songs: List[Song] = []
    for songs in playlists.values():
        all_songs.extend(songs)

    hype = playlists.get("Hype", [])
    chill = playlists.get("Chill", [])
    mixed = playlists.get("Mixed", [])

    total_songs = len(all_songs)
    hype_ratio = len(hype) / total_songs if total_songs > 0 else 0.0

    avg_energy = 0.0
    if all_songs:
        total_energy = sum(song.get("energy", 0) for song in all_songs)
        avg_energy = total_energy / total_songs

    top_artist, top_count = most_common_artist(all_songs)

    return {
        "total_songs": total_songs,
        "hype_count": len(hype),
        "chill_count": len(chill),
        "mixed_count": len(mixed),
        "hype_ratio": hype_ratio,
        "avg_energy": avg_energy,
        "top_artist": top_artist,
        "top_artist_count": top_count,
    }


def most_common_artist(songs: List[Song]) -> Tuple[str, int]:
    """Return the most common artist and count."""
    counts: Dict[str, int] = {}
    for song in songs:
        artist = str(song.get("artist", ""))
        if not artist:
            continue
        counts[artist] = counts.get(artist, 0) + 1

    if not counts:
        return "", 0

    items = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    return items[0]


def search_songs(
    songs: List[Song],
    query: str,
    field: str = "artist",
) -> List[Song]:
    """Return songs matching the query on a given field.

    The earlier version was doing `value in q` which meant the entire field
    content had to be a substring of the *query*, effectively preventing
    partial matches unless the user typed the full artist/genre/etc.  In the
    UI that caused searches like "oce" to return nothing even though "ocean"
    was present.  The check has been flipped and a couple of small tweaks were
    added for clarity.
    """
    if not query:
        return songs

    q = query.lower().strip()
    filtered: List[Song] = []

    for song in songs:
        value = str(song.get(field, "")).lower()
        # match if the query is contained within the song's field value
        if value and q in value:
            filtered.append(song)

    return filtered


def lucky_pick(
    playlists: PlaylistMap,
    mode: str = "any",
) -> Optional[Song]:
    """Pick a song from the playlists according to mode.

    The helper `random_choice_or_none` now safe-guards against empty lists, so
    callers can rely on a `None` result rather than letting an IndexError bubble
    up.  This mirrors the UI check where a warning message is shown if no
    song is available.  Without the guard a user could crash the app by hitting
    "Feeling lucky" when there were no songs in the requested category.
    """
    if mode == "hype":
        songs = playlists.get("Hype", [])
    elif mode == "chill":
        songs = playlists.get("Chill", [])
    else:
        songs = playlists.get("Hype", []) + playlists.get("Chill", [])

    return random_choice_or_none(songs)


def random_choice_or_none(songs: List[Song]) -> Optional[Song]:
    """Return a random song or None.

    `random.choice` raises an IndexError when passed an empty sequence, which
    isn't appropriate for the UI code that expects a `None` return value and
    handles it by showing a warning.  Guarding here keeps callers simpler and
    prevents crashes during edge cases (e.g. empty library or mode with no
    songs).
    """
    import random

    if not songs:
        return None
    return random.choice(songs)


def history_summary(history: List[Song]) -> Dict[str, int]:
    """Return a summary of moods seen in the history."""
    counts = {"Hype": 0, "Chill": 0, "Mixed": 0}
    for song in history:
        mood = song.get("mood", "Mixed")
        if mood not in counts:
            counts["Mixed"] += 1
        else:
            counts[mood] += 1
    return counts
