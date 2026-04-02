from podcast_vod_indexer.db import (
    init_db,
    get_connection,
    insert_video,
    insert_segments,
    get_video_id_by_youtube_id,
    get_videos_without_segments_by_kind,
)
from podcast_vod_indexer.youtube import (
    get_latest_videos,
    get_video_info,
    get_transcript_segments,
)

import time


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

        except Exception as e:
            print(f"  -> transcript fetch failed, skipping: {e}")
            conn.commit()
            time.sleep(20)

    vod_videos = get_videos_without_segments_by_kind(
        conn,
        kind="vod",
        limit=200,
    )

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

        except Exception as e:
            print(f"  -> transcript fetch failed, skipping: {e}")
            conn.commit()
            time.sleep(20)


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

        conn.commit()

    print("Done")
