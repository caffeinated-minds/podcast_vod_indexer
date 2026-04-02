from difflib import SequenceMatcher


def join_segment_text(segments: list[dict]) -> str:
    return " ".join(segment["text"] for segment in segments)


def similarity_score(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def build_windows(
    segments: list[dict],
    window_seconds: float = 900.0,
    step_seconds: float = 300.0,
) -> list[dict]:
    if not segments:
        return []

    max_time = max(
        segment["start"] + segment["duration"] for segment in segments
    )
    windows: list[dict] = []

    window_start = 0.0
    while window_start < max_time:
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
) -> dict | None:
    episode_text = join_segment_text(episode_segments)

    best_match = None
    best_score = -1.0

    for window in build_windows(vod_segments, window_seconds, step_seconds):
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
