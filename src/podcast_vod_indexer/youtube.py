from __future__ import annotations

from typing import Any
from pathlib import Path
from urllib.request import urlopen
from urllib.error import HTTPError
from html import unescape

import json
import subprocess
import xml.etree.ElementTree as ET
import yt_dlp


YDL_OPTS = {
    "quiet": True,
}

YTDLP_BIN = "/home/cm/Code/podcast_vod_indexer/.venv/bin/yt-dlp"


def _extract_info(video_url: str) -> dict[str, Any]:
    command = [
        YTDLP_BIN,
        "--cookies-from-browser",
        "brave+gnomekeyring",
        "--dump-single-json",
        "--skip-download",
        "--ignore-no-formats-error",
        video_url,
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())

    return json.loads(result.stdout)


def _get_english_caption_url(info: dict[str, Any]) -> str | None:
    automatic_captions = info.get("automatic_captions") or {}
    english_tracks = automatic_captions.get("en") or []

    if not english_tracks:
        return None

    return english_tracks[0].get("url")


def get_video_info(video_url: str, kind: str) -> dict[str, Any]:
    info = _extract_info(video_url)

    return {
        "youtube_id": info.get("id"),
        "kind": kind,
        "title": info.get("title"),
        "uploader": info.get("uploader"),
        "upload_date": info.get("upload_date"),
        "duration_seconds": info.get("duration"),
        "webpage_url": info.get("webpage_url"),
        "start_time": info.get("start_time"),
        "has_automatic_captions": bool(info.get("automatic_captions")),
        "has_subtitles": bool(info.get("subtitles")),
    }


def save_auto_caption_track(video_url: str, output_path: Path) -> bool:
    info = _extract_info(video_url)

    track_url = _get_english_caption_url(info)
    if not track_url:
        return False

    with urlopen(track_url) as response:
        caption_data = response.read().decode("utf-8")

    output_path.write_text(caption_data, encoding="utf-8")
    return True


def parse_caption_file(caption_path: Path) -> list[dict[str, object]]:
    root = ET.fromstring(caption_path.read_text(encoding="utf-8"))
    segments: list[dict[str, object]] = []

    for node in root.findall("text"):
        start = float(node.attrib.get("start", 0.0))
        duration = float(node.attrib.get("dur", 0.0))
        text = "".join(node.itertext()).strip()
        text = unescape(text)

        if not text:
            continue

        segments.append(
            {
                "start": start,
                "duration": duration,
                "text": text,
            }
        )

    return segments


def parse_json3_captions(data: dict[str, Any]) -> list[dict[str, object]]:
    segments: list[dict[str, object]] = []

    for event in data.get("events", []):
        start = event.get("tStartMs")
        duration = event.get("dDurationMs")
        segs = event.get("segs")

        if start is None or duration is None or not segs:
            continue

        text = "".join(seg.get("utf8", "") for seg in segs).strip()

        if not text:
            continue

        segments.append(
            {
                "start": start / 1000,
                "duration": duration / 1000,
                "text": text,
            }
        )

    return segments


def _download_json_track(track_url: str) -> dict:
    try:
        with urlopen(track_url) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as e:
        if e.code == 429:
            raise
        raise


def get_transcript_segments(video_url: str) -> list[dict[str, object]]:
    info = _extract_info(video_url)

    track_url = _get_english_caption_url(info)
    if not track_url:
        return []

    data = _download_json_track(track_url)
    return parse_json3_captions(data)


def get_latest_videos(source_url: str, limit: int = 5) -> list[dict]:
    ydl_opts = {
        "quiet": True,
        "extract_flat": True,
        "playlistend": limit,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(source_url, download=False)

    entries = info.get("entries", []) or []

    return [
        {
            "youtube_id": e.get("id"),
            "title": e.get("title"),
            "webpage_url": e.get("url"),
        }
        for e in entries
        if e.get("id")
    ]
