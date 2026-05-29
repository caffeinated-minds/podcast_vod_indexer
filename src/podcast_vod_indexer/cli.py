from podcast_vod_indexer.db import (
    init_db,
    get_connection,
    insert_video,
    insert_segments,
    get_video_id_by_youtube_id,
    get_videos_without_segments_by_kind,
    get_videos_with_segments_by_kind,
    get_segments_for_video,
    get_match_confidence_for_episode,
    upsert_match,
    get_videos_by_kind,
    upsert_episode_long_match,
)
from podcast_vod_indexer.youtube import (
    get_latest_videos,
    get_video_info,
    get_transcript_segments,
    TranscriptRateLimitError,
)
from podcast_vod_indexer.matching import (
    find_best_window_match,
    find_best_title_match,
)
from podcast_vod_indexer.export import export_matches_html

import time


MATCH_CONFIDENCE_CUTOFF = 0.15
MATCH_SKIP_CONFIDENCE_CUTOFF = 0.15


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


def fetch_missing_transcripts_with_budget(
    conn,
    vod_limit: int,
    episode_limit: int,
) -> None:
    episode_videos = get_videos_without_segments_by_kind(
        conn,
        kind="episode",
        limit=50,
    )

    vod_videos = get_videos_without_segments_by_kind(
        conn,
        kind="vod",
        limit=200,
    )

    """Live VODs"""
    vod_successes = 0
    for video_id, _, video_url in vod_videos:
        if vod_successes >= vod_limit:
            break

        print(f"[vod] Fetching transcript: {video_url}")

        try:
            segments = get_transcript_segments(video_url)

            if not segments:
                print("  -> no transcript, skipping")
                continue

            insert_segments(conn, video_id, segments)
            conn.commit()
            time.sleep(5)
            vod_successes += 1

        except TranscriptRateLimitError:
            print(
                "  -> transcript rate limit hit, stopping"
                " transcript fetches for this run"
                )
            conn.commit()
            return

        except Exception as e:
            print(f"  -> transcript fetch failed, skipping: {e}")
            conn.commit()
            time.sleep(20)

    """ EPISODES """
    episode_successes = 0
    for video_id, _, video_url in episode_videos:
        if episode_successes >= episode_limit:
            break

        print(f"[episode] Fetching transcript: {video_url}")

        try:
            segments = get_transcript_segments(video_url)

            if not segments:
                print("  -> no transcript, skipping")
                continue

            insert_segments(conn, video_id, segments)
            conn.commit()
            time.sleep(5)
            episode_successes += 1

        except TranscriptRateLimitError:
            print(
                " -> transcript rate limit hit, stopping"
                " transcript fetches for this run"
            )
            conn.commit()
            return

        except Exception as e:
            print(f"  -> transcript fetch failed, skipping: {e}")
            conn.commit()
            time.sleep(20)


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
                best_window_start = match["start"]

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
    short_episodes = get_videos_by_kind(conn, "episode")
    long_episodes = get_videos_by_kind(conn, "episode_long")

    if not long_episodes:
        print("[long-episode-match] No long episodes found")
        return

    for episode_id, _, episode_title in short_episodes:
        match = find_best_title_match(episode_title, long_episodes)

        if match is None:
            print(f"[long-episode-match] No candidate: {episode_title}")
            continue

        upsert_episode_long_match(
            conn,
            short_episode_video_id=episode_id,
            long_episode_video_id=match["video_id"],
            confidence=match["score"],
        )
        conn.commit()

        print(
            f"[long-episode-match] Stored: {episode_title} "
            f"({match['score'] * 100:.2f}%)"
        )


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

        fetch_missing_transcripts_with_budget(
            conn,
            vod_limit=10,
            episode_limit=2,
        )

        run_matching(conn)
        run_long_episode_matching(conn)
        export_matches_html(conn)

        conn.commit()

    print("Done")
