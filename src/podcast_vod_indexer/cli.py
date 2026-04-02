from podcast_vod_indexer.db import (
    init_db,
    get_connection,
    insert_video,
    insert_segments,
    get_video_id_by_youtube_id,
    get_videos_without_segments_by_kind,
    get_videos_with_segments_by_kind,
    get_segments_for_video,
    upsert_match,
)
from podcast_vod_indexer.youtube import (
    get_latest_videos,
    get_video_info,
    get_transcript_segments,
    TranscriptRateLimitError,
)
from podcast_vod_indexer.matching import find_best_window_match
from podcast_vod_indexer.export import export_matches_html

import time


MATCH_CONFIDENCE_CUTOFF = 0.15


def process_source(conn, source_url: str, kind: str, limit: int) -> None:
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


def run_matching(conn) -> None:
    episodes = get_videos_with_segments_by_kind(conn, "episode")
    vods = get_videos_with_segments_by_kind(conn, "vod")

    for episode_id, _, episode_title in episodes:
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

        if (
            best_vod_id is not None
            and best_window_start is not None
            and best_score >= MATCH_CONFIDENCE_CUTOFF
        ):
            upsert_match(
                conn,
                episode_video_id=episode_id,
                vod_video_id=best_vod_id,
                matched_start_seconds=best_window_start,
                confidence=best_score,
            )
            conn.commit()
            print(f"  -> stored match ({best_score * 100:.2f}%)")
        else:
            print(
                f"  -> no match stored (best score: {best_score * 100:.2f}%)"
                )


def main() -> None:
    vod_source_url = "https://www.youtube.com/@ThePrimeTimeagen/streams"
    episode_source_url = (
        "https://www.youtube.com/playlist?"
        "list=PL2Fq-K0QdOQiJpufsnhEd1z3xOv2JMHuk"
    )

    init_db()

    with get_connection() as conn:
        process_source(conn, vod_source_url, kind="vod", limit=50)
        process_source(conn, episode_source_url, kind="episode", limit=5)

        fetch_missing_transcripts_with_budget(
            conn,
            vod_limit=9,
            episode_limit=1,
        )

        run_matching(conn)
        export_matches_html(conn)

        conn.commit()

    print("Done")
