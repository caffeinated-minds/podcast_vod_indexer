from difflib import SequenceMatcher
import re


TITLE_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "is",
    "of",
    "on",
    "the",
    "to",
}


def join_segment_text(segments: list[dict]) -> str:
    return " ".join(segment["text"] for segment in segments)


def similarity_score(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def normalize_title(title: str) -> str:
    title = title.lower()
    title = title.replace("thestandup", "the standup")
    title = re.sub(r"[^a-z0-9]+", " ", title)

    words = [
        word
        for word in title.split()
        if word not in TITLE_STOP_WORDS
    ]

    return " ".join(words)


def find_best_title_match(
    title: str, candidates: list[tuple[int, str, str]]
) -> dict | None:
    normalized_title = normalize_title(title)

    if not normalized_title:
        return None

    best_match = None
    best_score = -1.0

    for video_id, _, candidate_title in candidates:
        normalized_candidate = normalize_title(candidate_title)

        if not normalized_candidate:
            continue

        score = similarity_score(normalized_title, normalized_candidate)

        if score > best_score:
            best_score = score
            best_match = {
                "video_id": video_id,
                "score": score,
            }

    return best_match


def get_segments_before(
    segments: list[dict],
    max_seconds: float,
) -> list[dict]:
    return [
        segment
        for segment in segments
        if segment["start"] < max_seconds
    ]


def find_long_episode_transcript_match(
    episode_segments: list[dict],
    long_episode_segments: list[dict],
    max_episode_seconds: float,
    max_long_episode_seconds: float,
    window_seconds: float,
    step_seconds: float,
) -> dict | None:
    episode_text = join_segment_text(
        get_segments_before(episode_segments, max_episode_seconds)
    )

    if not episode_text:
        return None

    long_episode_windows = build_windows(
        get_segments_before(long_episode_segments, max_long_episode_seconds),
        window_seconds=window_seconds,
        step_seconds=step_seconds,
    )

    best_match = None
    best_score = -1.0

    for window in long_episode_windows:
        score = similarity_score(
            episode_text[:5000],
            window["text"][:5000],
        )

        if score > best_score:
            best_score = score
            best_match = {
                "start": window["start"],
                "end": window["end"],
                "score": score,
            }

    return best_match


def build_windows(
    segments: list[dict],
    window_seconds: float = 900.0,
    step_seconds: float = 300.0,
    start_seconds: float = 0.0,
    end_seconds: float | None = None,
) -> list[dict]:
    if not segments:
        return []

    max_time = max(
        segment["start"] + segment["duration"] for segment in segments
    )
    windows: list[dict] = []

    window_start = start_seconds
    while (
        window_start < max_time
        and (end_seconds is None or window_start <= end_seconds)
    ):
        window_end = window_start + window_seconds

        window_segments = [
            segment
            for segment in segments
            if segment["start"] < window_end
            and (segment["start"] + segment["duration"]) > window_start
        ]

        if window_segments:
            windows.append(
                {
                    "start": window_start,
                    "end": window_end,
                    "text": join_segment_text(window_segments),
                }
            )

        window_start += step_seconds

    return windows


def find_best_window_match(
    episode_segments: list[dict],
    vod_segments: list[dict],
    window_seconds: float = 900.0,
    step_seconds: float = 300.0,
    start_seconds: float = 0.0,
    end_seconds: float | None = None,
) -> dict | None:
    episode_text = join_segment_text(episode_segments)

    best_match = None
    best_score = -1.0

    for window in build_windows(
        vod_segments,
        window_seconds,
        step_seconds,
        start_seconds,
        end_seconds,
    ):
        score = similarity_score(
            episode_text[:5000],
            window["text"][:5000],
        )

        if score > best_score:
            best_score = score
            best_match = {
                "start": window["start"],
                "end": window["end"],
                "score": score,
            }

    return best_match


def find_best_window_pair_match(
    episode_segments: list[dict],
    vod_segments: list[dict],
    window_seconds: float = 900.0,
    episode_step_seconds: float = 300.0,
    vod_step_seconds: float = 60.0,
    char_limit: int = 5000,
) -> dict | None:
    episode_windows = build_windows(
        episode_segments,
        window_seconds=window_seconds,
        step_seconds=episode_step_seconds,
    )
    vod_windows = build_windows(
        vod_segments,
        window_seconds=window_seconds,
        step_seconds=vod_step_seconds,
    )

    best_match = None
    best_score = -1.0

    for episode_window in episode_windows:
        episode_text = episode_window["text"][:char_limit]

        for vod_window in vod_windows:
            score = similarity_score(
                episode_text,
                vod_window["text"][:char_limit],
            )

            if score > best_score:
                best_score = score
                best_match = {
                    "episode_start": episode_window["start"],
                    "episode_end": episode_window["end"],
                    "start": vod_window["start"],
                    "end": vod_window["end"],
                    "score": score,
                }

    return best_match


def refine_low_confidence_window_match(
    episode_segments: list[dict],
    vod_segments: list[dict],
    coarse_start_seconds: float,
    window_seconds: float = 900.0,
    search_radius_seconds: float = 300.0,
    step_seconds: float = 60.0,
) -> dict | None:
    return find_best_window_match(
        episode_segments,
        vod_segments,
        window_seconds=window_seconds,
        step_seconds=step_seconds,
        start_seconds=max(0.0, coarse_start_seconds - search_radius_seconds),
        end_seconds=coarse_start_seconds + search_radius_seconds,
    )
