from __future__ import annotations

from base64 import b64encode
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import json
import os
from difflib import SequenceMatcher


SPOTIFY_ACCOUNTS_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE_URL = "https://api.spotify.com/v1"


class SpotifyCredentialsMissingError(Exception):
    pass


class SpotifyApiError(Exception):
    pass


def normalize_title(title: str | None) -> str:
    if not title:
        return ""

    title = title.lower()
    title = title.replace("thestandup", "the standup")
    title = "".join(
        char if char.isalnum() else " "
        for char in title
    )
    return " ".join(title.split())


def title_similarity(a: str | None, b: str | None) -> float:
    normalized_a = normalize_title(a)
    normalized_b = normalize_title(b)

    if not normalized_a or not normalized_b:
        return 0.0

    return SequenceMatcher(None, normalized_a, normalized_b).ratio()


def date_similarity(youtube_date: str | None, spotify_date: str | None) -> float:
    if not youtube_date or not spotify_date:
        return 0.0

    normalized_youtube_date = youtube_date
    if len(youtube_date) == 8 and youtube_date.isdigit():
        normalized_youtube_date = (
            f"{youtube_date[0:4]}-{youtube_date[4:6]}-{youtube_date[6:8]}"
        )

    if normalized_youtube_date == spotify_date:
        return 1.0

    if normalized_youtube_date[:7] == spotify_date[:7]:
        return 0.6

    if normalized_youtube_date[:4] == spotify_date[:4]:
        return 0.2

    return 0.0


def duration_similarity(
    youtube_duration_seconds: int | None,
    spotify_duration_ms: int | None,
) -> float:
    if not youtube_duration_seconds or not spotify_duration_ms:
        return 0.0

    spotify_duration_seconds = spotify_duration_ms / 1000
    max_duration = max(youtube_duration_seconds, spotify_duration_seconds)

    if max_duration <= 0:
        return 0.0

    diff_ratio = abs(youtube_duration_seconds - spotify_duration_seconds)
    diff_ratio /= max_duration
    return max(0.0, 1.0 - diff_ratio)


def spotify_match_score(
    youtube_episode: dict[str, object],
    spotify_episode: dict[str, object],
) -> float:
    title_score = title_similarity(
        youtube_episode.get("title"),
        spotify_episode.get("title"),
    )
    date_score = date_similarity(
        youtube_episode.get("upload_date"),
        spotify_episode.get("release_date"),
    )
    duration_score = duration_similarity(
        youtube_episode.get("duration_seconds"),
        spotify_episode.get("duration_ms"),
    )

    return (
        title_score * 0.70
        + date_score * 0.20
        + duration_score * 0.10
    )


def get_access_token() -> str:
    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")

    if not client_id or not client_secret:
        raise SpotifyCredentialsMissingError(
            "SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET are required."
        )

    credentials = f"{client_id}:{client_secret}".encode("utf-8")
    auth_header = b64encode(credentials).decode("ascii")
    body = urlencode({"grant_type": "client_credentials"}).encode("utf-8")

    request = Request(
        SPOTIFY_ACCOUNTS_TOKEN_URL,
        data=body,
        headers={
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )

    data = _request_json(request)
    token = data.get("access_token")

    if not token:
        raise SpotifyApiError("Spotify token response did not include a token.")

    return token


def fetch_show_episodes(show_id: str) -> list[dict[str, Any]]:
    token = get_access_token()
    episodes: list[dict[str, Any]] = []
    limit = 50
    offset = 0

    while True:
        query = urlencode(
            {
                "limit": limit,
                "offset": offset,
            }
        )
        request = Request(
            f"{SPOTIFY_API_BASE_URL}/shows/{show_id}/episodes?{query}",
            headers={"Authorization": f"Bearer {token}"},
        )
        data = _request_json(request)
        items = data.get("items") or []
        episodes.extend(items)

        if not data.get("next") or len(items) < limit:
            break

        offset += limit

    return [normalize_episode(show_id, episode) for episode in episodes]


def normalize_episode(show_id: str, episode: dict[str, Any]) -> dict[str, Any]:
    return {
        "spotify_id": episode.get("id"),
        "show_id": show_id,
        "title": episode.get("name"),
        "description": episode.get("description"),
        "html_description": episode.get("html_description"),
        "release_date": episode.get("release_date"),
        "release_date_precision": episode.get("release_date_precision"),
        "duration_ms": episode.get("duration_ms"),
        "spotify_url": (episode.get("external_urls") or {}).get("spotify"),
    }


def _request_json(request: Request) -> dict[str, Any]:
    try:
        with urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise SpotifyApiError(
            f"Spotify API request failed ({e.code}): {detail}"
        ) from e
