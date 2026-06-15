import sqlite3
import unittest
from unittest.mock import patch

from podcast_vod_indexer.db import (
    get_first_episode_matched_vod_date,
    get_videos_with_segments_by_kind,
    get_videos_without_segments_by_kind,
    init_db,
    prune_vods_before_date,
)


class DatabaseSchemaTests(unittest.TestCase):
    def test_fresh_database_has_no_spotify_schema(self) -> None:
        conn = sqlite3.connect(":memory:")

        with patch(
            "podcast_vod_indexer.db.get_connection",
            return_value=conn,
        ):
            init_db()

        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        video_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(videos)").fetchall()
        }

        self.assertNotIn("spotify_episodes", tables)
        self.assertNotIn("spotify_matches", tables)
        self.assertNotIn("spotify_url", video_columns)
        conn.close()

    def test_vod_cutoff_prunes_and_filters_old_unreferenced_vods(self) -> None:
        conn = sqlite3.connect(":memory:")

        with patch(
            "podcast_vod_indexer.db.get_connection",
            return_value=conn,
        ):
            init_db()

        videos = [
            (1, "episode", "episode", "20250306"),
            (2, "cutoff-vod", "vod", "20250305"),
            (3, "old-vod", "vod", "20250304"),
            (4, "new-vod", "vod", "20250307"),
            (5, "new-vod-missing-transcript", "vod", "20250308"),
        ]
        conn.executemany(
            """
            INSERT INTO videos (
                id, youtube_id, kind, title, upload_date, webpage_url
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    video_id,
                    youtube_id,
                    kind,
                    youtube_id,
                    upload_date,
                    f"https://example.com/{youtube_id}",
                )
                for video_id, youtube_id, kind, upload_date in videos
            ],
        )
        conn.executemany(
            """
            INSERT INTO segments (video_id, start, duration, text)
            VALUES (?, 0, 1, 'transcript')
            """,
            [(2,), (3,), (4,)],
        )
        conn.execute(
            """
            INSERT INTO matches (
                episode_video_id, vod_video_id, matched_start_seconds,
                confidence
            )
            VALUES (1, 2, 0, 0.20)
            """
        )

        cutoff = get_first_episode_matched_vod_date(conn, 0.15)
        pruned = prune_vods_before_date(conn, cutoff)

        self.assertEqual(cutoff, "20250305")
        self.assertEqual(pruned, (1, 1))
        self.assertEqual(
            get_videos_with_segments_by_kind(
                conn,
                "vod",
                min_upload_date=cutoff,
            ),
            [
                (4, "new-vod", "new-vod"),
                (2, "cutoff-vod", "cutoff-vod"),
            ],
        )
        self.assertEqual(
            get_videos_without_segments_by_kind(
                conn,
                "vod",
                limit=10,
                min_upload_date=cutoff,
            ),
            [
                (
                    5,
                    "new-vod-missing-transcript",
                    "https://example.com/new-vod-missing-transcript",
                )
            ],
        )
        conn.close()

    def test_vod_cutoff_pruning_rejects_referenced_old_vod(self) -> None:
        conn = sqlite3.connect(":memory:")

        with patch(
            "podcast_vod_indexer.db.get_connection",
            return_value=conn,
        ):
            init_db()

        conn.executemany(
            """
            INSERT INTO videos (id, youtube_id, kind, upload_date)
            VALUES (?, ?, ?, ?)
            """,
            [
                (1, "episode", "episode", "20250306"),
                (2, "old-vod", "vod", "20250304"),
            ],
        )
        conn.execute(
            """
            INSERT INTO matches (
                episode_video_id, vod_video_id, matched_start_seconds,
                confidence
            )
            VALUES (1, 2, 0, 0.20)
            """
        )

        with self.assertRaisesRegex(RuntimeError, "referenced"):
            prune_vods_before_date(conn, "20250305")

        conn.close()


if __name__ == "__main__":
    unittest.main()
