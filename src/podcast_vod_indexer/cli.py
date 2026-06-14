from podcast_vod_indexer.db import (
    init_db,
    get_connection,
    insert_video,
    insert_segments,
    get_video_id_by_youtube_id,
    upsert_spotify_episode,
    get_episode_videos_for_spotify_matching,
    get_spotify_episodes,
    upsert_spotify_match,
    get_videos_without_segments_by_kind,
    get_videos_with_segments_by_kind,
    get_segments_for_video,
    get_match_confidence_for_episode,
    upsert_match,
    upsert_episode_long_match,
)
from podcast_vod_indexer.youtube import (
    get_latest_videos,
    get_video_info,
    get_transcript_segments,
    TranscriptRateLimitError,
)
from podcast_vod_indexer.spotify import (
    SpotifyApiError,
    SpotifyCredentialsMissingError,
    fetch_show_episodes,
    spotify_match_score,
)
from podcast_vod_indexer.matching import (
    find_best_window_match,
    find_long_episode_transcript_match,
    refine_low_confidence_window_match,
)
from podcast_vod_indexer.export import export_matches_html

import time


MATCH_CONFIDENCE_CUTOFF = 0.15
MATCH_SKIP_CONFIDENCE_CUTOFF = 0.15
SHORT_EPISODE_MATCH_SECONDS = 15 * 60
LONG_EPISODE_SEARCH_SECONDS = 45 * 60
LONG_EPISODE_WINDOW_SECONDS = 15 * 60
LONG_EPISODE_STEP_SECONDS = 2 * 60
LONG_EPISODE_MATCH_METHOD = "transcript_short15m_long45m_window15m"
SPOTIFY_SHOW_ID = "01A062kejnXFkJE01bjN5J"
SPOTIFY_MATCH_METHOD = "metadata_title_date_duration"


def process_source(
        conn, source_url: str, kind: str, limit: int | None = None
        ) -> None:
    if limit is None:
        videos = get_latest_videos(source_url)
    else:
        videos = get_latest_videos(source_url, limit=limit)

    for v in videos:
        video_url = v["webpage_url"]
        youtube_id = v["youtube_id"]

        print(f"[{kind}] Processing metadata: {video_url}")

        existing_id = get_video_id_by_youtube_id(conn, youtube_id)
        if existing_id:
            print("  -> already known, skipping metadata")
            continue

        video = get_video_info(video_url, kind=kind)
        insert_video(conn, video)

    conn.commit()


def process_spotify_show(conn, show_id: str) -> None:
    print(f"[spotify] Processing show: {show_id}")

    try:
        episodes = fetch_show_episodes(show_id)
    except SpotifyCredentialsMissingError as e:
        print(f"  -> spotify sync skipped: {e}")
        return
    except SpotifyApiError as e:
        print(f"  -> spotify sync failed: {e}")
        return

    for episode in episodes:
        upsert_spotify_episode(conn, episode)

    conn.commit()
    print(f"  -> stored {len(episodes)} spotify episodes")


def run_spotify_matching(conn) -> None:
    episodes = get_episode_videos_for_spotify_matching(conn)
    spotify_episodes = get_spotify_episodes(conn)

    if not spotify_episodes:
        print("[spotify-match] No spotify episodes found")
        return

    candidates = []

    for episode in episodes:
        print(f"[spotify-match] Episode: {episode['title']}")

        for spotify_episode in spotify_episodes:
            candidates.append(
                {
                    "episode_id": episode["id"],
                    "episode_title": episode["title"],
                    "spotify_episode_id": spotify_episode["id"],
                    "spotify_episode_title": spotify_episode["title"],
                    "score": spotify_match_score(
                        episode,
                        spotify_episode,
                    ),
                }
            )

    candidates.sort(key=lambda candidate: candidate["score"], reverse=True)

    matched_episode_ids = set()
    matched_spotify_episode_ids = set()

    for candidate in candidates:
        episode_id = candidate["episode_id"]
        spotify_episode_id = candidate["spotify_episode_id"]

        if (
            episode_id in matched_episode_ids
            or spotify_episode_id in matched_spotify_episode_ids
        ):
            continue

        upsert_spotify_match(
            conn,
            episode_video_id=episode_id,
            spotify_episode_id=spotify_episode_id,
            confidence=candidate["score"],
            match_method=SPOTIFY_MATCH_METHOD,
        )
        conn.commit()

        matched_episode_ids.add(episode_id)
        matched_spotify_episode_ids.add(spotify_episode_id)

        if candidate["score"] >= MATCH_CONFIDENCE_CUTOFF:
            print(
                f"[spotify-match] Stored: "
                f"{candidate['episode_title']} -> "
                f"{candidate['spotify_episode_title']} "
                f"({candidate['score'] * 100:.2f}%)"
            )
        else:
            print(
                f"[spotify-match] Stored low-confidence candidate: "
                f"{candidate['episode_title']} -> "
                f"{candidate['spotify_episode_title']} "
                f"({candidate['score'] * 100:.2f}%)"
            )


def fetch_transcripts_for_videos(conn, kind: str, videos: list, limit: int):
    successes = 0

    for video_id, _, video_url in videos:
        if successes >= limit:
            return True

        print(f"[{kind}] Fetching transcript: {video_url}")

        try:
            segments = get_transcript_segments(video_url)

            if not segments:
                print("  -> no transcript, skipping")
                continue

            insert_segments(conn, video_id, segments)
            conn.commit()
            time.sleep(5)
            successes += 1

        except TranscriptRateLimitError:
            print(
                " -> transcript rate limit hit, stopping"
                " transcript fetches for this run"
            )
            conn.commit()
            return False

        except Exception as e:
            print(f"  -> transcript fetch failed, skipping: {e}")
            conn.commit()
            time.sleep(20)

    return True


def fetch_missing_transcripts_with_budget(
    conn,
    vod_limit: int,
    episode_limit: int,
    long_episode_limit: int,
) -> None:
    episode_videos = get_videos_without_segments_by_kind(
        conn,
        kind="episode",
        limit=50,
    )

    long_episode_videos = get_videos_without_segments_by_kind(
        conn,
        kind="episode_long",
        limit=100,
    )

    vod_videos = get_videos_without_segments_by_kind(
        conn,
        kind="vod",
        limit=200,
    )

    if not fetch_transcripts_for_videos(
        conn,
        kind="episode",
        videos=episode_videos,
        limit=episode_limit,
    ):
        return

    if not fetch_transcripts_for_videos(
        conn,
        kind="episode_long",
        videos=long_episode_videos,
        limit=long_episode_limit,
    ):
        return

    fetch_transcripts_for_videos(
        conn,
        kind="vod",
        videos=vod_videos,
        limit=vod_limit,
    )


def run_matching(conn) -> None:
    episodes = get_videos_with_segments_by_kind(conn, "episode")
    vods = get_videos_with_segments_by_kind(conn, "vod")

    for episode_id, _, episode_title in episodes:
        existing_confidence = get_match_confidence_for_episode(
            conn, episode_id
        )

        if (
            existing_confidence is not None
            and existing_confidence >= MATCH_SKIP_CONFIDENCE_CUTOFF
        ):
            print(
                f"[match] Skipping: {episode_title} "
                f"({existing_confidence * 100:.2f}%)"
            )
            continue

        episode_segments = get_segments_for_video(conn, episode_id)

        best_vod_id = None
        best_vod_segments = None
        best_score = -1.0
        best_window_start = None

        print(f"[match] Episode: {episode_title}")

        for vod_id, _, vod_title in vods:
            vod_segments = get_segments_for_video(conn, vod_id)

            match = find_best_window_match(
                episode_segments,
                vod_segments,
                window_seconds=900.0,
                step_seconds=300.0,
            )

            if match is None:
                continue

            if match["score"] > best_score:
                best_score = match["score"]
                best_vod_id = vod_id
                best_vod_segments = vod_segments
                best_window_start = match["start"]

        if (
            best_vod_id is not None
            and best_vod_segments is not None
            and best_window_start is not None
            and best_score < MATCH_CONFIDENCE_CUTOFF
        ):
            refined_match = refine_low_confidence_window_match(
                episode_segments,
                best_vod_segments,
                coarse_start_seconds=best_window_start,
                window_seconds=900.0,
                search_radius_seconds=300.0,
                step_seconds=60.0,
            )

            if refined_match is not None and refined_match["score"] > best_score:
                best_score = refined_match["score"]
                best_window_start = refined_match["start"]
                print(
                    f"  -> refined low-confidence match "
                    f"({best_score * 100:.2f}%)"
                )

        if best_vod_id is not None and best_window_start is not None:
            upsert_match(
                conn,
                episode_video_id=episode_id,
                vod_video_id=best_vod_id,
                matched_start_seconds=best_window_start,
                confidence=best_score,
            )
            conn.commit()

            if best_score >= MATCH_CONFIDENCE_CUTOFF:
                print(f"  -> stored match ({best_score * 100:.2f}%)")
            else:
                print(
                    f"  -> stored low-confidence candidate "
                    f"({best_score * 100:.2f}%)"
                )
        else:
            print("  -> no candidate found")


def run_long_episode_matching(conn) -> None:
    short_episodes = get_videos_with_segments_by_kind(conn, "episode")
    long_episodes = get_videos_with_segments_by_kind(conn, "episode_long")

    if not long_episodes:
        print("[long-episode-match] No long episodes with transcripts found")
        return

    candidates = []

    for episode_id, _, episode_title in short_episodes:
        episode_segments = get_segments_for_video(conn, episode_id)

        print(f"[long-episode-match] Episode: {episode_title}")

        for long_episode_id, _, long_episode_title in long_episodes:
            long_episode_segments = get_segments_for_video(
                conn, long_episode_id
            )

            match = find_long_episode_transcript_match(
                episode_segments,
                long_episode_segments,
                max_episode_seconds=SHORT_EPISODE_MATCH_SECONDS,
                max_long_episode_seconds=LONG_EPISODE_SEARCH_SECONDS,
                window_seconds=LONG_EPISODE_WINDOW_SECONDS,
                step_seconds=LONG_EPISODE_STEP_SECONDS,
            )

            if match is None:
                continue

            candidates.append(
                {
                    "short_episode_id": episode_id,
                    "short_episode_title": episode_title,
                    "long_episode_id": long_episode_id,
                    "long_episode_title": long_episode_title,
                    "score": match["score"],
                }
            )

    candidates.sort(key=lambda candidate: candidate["score"], reverse=True)

    matched_short_episode_ids = set()
    matched_long_episode_ids = set()

    for candidate in candidates:
        short_episode_id = candidate["short_episode_id"]
        long_episode_id = candidate["long_episode_id"]

        if (
            short_episode_id in matched_short_episode_ids
            or long_episode_id in matched_long_episode_ids
        ):
            continue

        upsert_episode_long_match(
            conn,
            short_episode_video_id=short_episode_id,
            long_episode_video_id=long_episode_id,
            confidence=candidate["score"],
            match_method=LONG_EPISODE_MATCH_METHOD,
        )
        conn.commit()

        matched_short_episode_ids.add(short_episode_id)
        matched_long_episode_ids.add(long_episode_id)

        if candidate["score"] >= MATCH_CONFIDENCE_CUTOFF:
            print(
                f"[long-episode-match] Stored: "
                f"{candidate['short_episode_title']} -> "
                f"{candidate['long_episode_title']} "
                f"({candidate['score'] * 100:.2f}%)"
            )
        else:
            print(
                f"[long-episode-match] Stored low-confidence candidate: "
                f"{candidate['short_episode_title']} -> "
                f"{candidate['long_episode_title']} "
                f"({candidate['score'] * 100:.2f}%)"
            )

    unmatched_short_episodes = [
        episode_title
        for episode_id, _, episode_title in short_episodes
        if episode_id not in matched_short_episode_ids
    ]

    for episode_title in unmatched_short_episodes:
        print(f"[long-episode-match] No candidate: {episode_title}")


def main() -> None:
    vod_source_url = "https://www.youtube.com/@ThePrimeTimeagen/streams"
    episode_source_url = (
        "https://www.youtube.com/playlist?"
        "list=PL2Fq-K0QdOQiJpufsnhEd1z3xOv2JMHuk"
    )
    long_episode_source_url = (
        "https://www.youtube.com/playlist?"
        "list=PLnO2sUspiA2b-gmVb-khiLa2NoQ7mHzZ-"
    )

    init_db()

    with get_connection() as conn:
        process_source(conn, vod_source_url, kind="vod")
        process_source(conn, episode_source_url, kind="episode")
        process_source(conn, long_episode_source_url, kind="episode_long")
        process_spotify_show(conn, SPOTIFY_SHOW_ID)

        fetch_missing_transcripts_with_budget(
            conn,
            vod_limit=10,
            episode_limit=2,
            long_episode_limit=2,
        )

        run_matching(conn)
        run_long_episode_matching(conn)
        run_spotify_matching(conn)
        export_matches_html(conn)

        conn.commit()

    print("Done")
