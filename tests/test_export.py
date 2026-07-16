import sqlite3
import unittest
from unittest.mock import patch

from podcast_vod_indexer.db import init_db
from podcast_vod_indexer.export import get_export_rows, load_template, render_rows


class ExportHtmlTests(unittest.TestCase):
    def test_rendered_index_has_no_spotify_column(self) -> None:
        rows = [
            (
                "Episode",
                "https://example.com/episode",
                "20260615",
                "VOD",
                "https://example.com/vod",
                "20260614",
                60.0,
                0.5,
                None,
                "https://example.com/long-episode",
                0.5,
                None,
            )
        ]

        html = load_template().substitute(rows=render_rows(rows))

        self.assertNotIn("Spotify", html)
        self.assertNotIn("Clips", html)
        self.assertNotIn("Shorts", html)
        self.assertEqual(html.count('<th scope="col">'), 8)
        self.assertEqual(html.count("<td>"), 8)
        self.assertIn(
            '<a href="https://example.com/episode" '
            'target="_blank" rel="noopener noreferrer">Episode</a>',
            html,
        )

    def test_marks_equivalent_long_episode_as_not_needed(self) -> None:
        rows = [
            (
                "Episode",
                "https://example.com/episode",
                "20260615",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                "equivalent_duration",
            )
        ]

        html = render_rows(rows)

        self.assertIn("~ Equivalent upload (not needed)", html)

    def test_renders_unmatched_long_episode_fallback_row(self) -> None:
        rows = [
            (
                None,
                None,
                "20260626",
                "VOD",
                "https://example.com/vod",
                "20260625",
                120.0,
                0.30,
                "Long Episode",
                "https://example.com/long",
                1.0,
                None,
            )
        ]

        html = render_rows(rows)

        self.assertIn("<td>N/a</td>", html)
        self.assertIn(
            '<a href="https://example.com/long" '
            'target="_blank" rel="noopener noreferrer">Long Episode</a>',
            html,
        )

    def test_export_rows_include_unmatched_long_episode_fallback(self) -> None:
        conn = sqlite3.connect(":memory:")
        with patch("podcast_vod_indexer.db.get_connection", return_value=conn):
            init_db()

        conn.executemany(
            """
            INSERT INTO videos (
                id, youtube_id, kind, title, upload_date, webpage_url
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    1,
                    "long",
                    "episode_long",
                    "Long Episode",
                    "20260626",
                    "https://example.com/long",
                ),
                (
                    2,
                    "vod",
                    "vod",
                    "VOD",
                    "20260625",
                    "https://example.com/vod",
                ),
            ],
        )
        conn.execute(
            """
            INSERT INTO segments (video_id, start, duration, text)
            VALUES (1, 0, 1, 'transcript')
            """
        )
        conn.execute(
            """
            INSERT INTO episode_long_vod_matches (
                long_episode_video_id,
                vod_video_id,
                matched_start_seconds,
                confidence
            )
            VALUES (1, 2, 120, 0.30)
            """
        )

        rows = get_export_rows(conn)

        self.assertEqual(rows[0][0], None)
        self.assertEqual(rows[0][2], "20260626")
        self.assertEqual(rows[0][3], "VOD")
        self.assertEqual(rows[0][8], "Long Episode")
        conn.close()

    def test_export_rows_hide_fallback_when_normal_row_uses_same_vod(self) -> None:
        conn = sqlite3.connect(":memory:")
        with patch("podcast_vod_indexer.db.get_connection", return_value=conn):
            init_db()

        conn.executemany(
            """
            INSERT INTO videos (
                id, youtube_id, kind, title, upload_date, webpage_url
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    1,
                    "episode",
                    "episode",
                    "Episode",
                    "20260626",
                    "https://example.com/episode",
                ),
                (
                    2,
                    "long",
                    "episode_long",
                    "Long Episode",
                    "20260626",
                    "https://example.com/long",
                ),
                (
                    3,
                    "vod",
                    "vod",
                    "VOD",
                    "20260625",
                    "https://example.com/vod",
                ),
            ],
        )
        conn.executemany(
            """
            INSERT INTO segments (video_id, start, duration, text)
            VALUES (?, 0, 1, 'transcript')
            """,
            [(1,), (2,)],
        )
        conn.execute(
            """
            INSERT INTO matches (
                episode_video_id,
                vod_video_id,
                matched_start_seconds,
                confidence
            )
            VALUES (1, 3, 120, 0.30)
            """
        )
        conn.execute(
            """
            INSERT INTO episode_long_vod_matches (
                long_episode_video_id,
                vod_video_id,
                matched_start_seconds,
                confidence
            )
            VALUES (2, 3, 120, 0.30)
            """
        )

        rows = get_export_rows(conn)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "Episode")
        conn.close()


if __name__ == "__main__":
    unittest.main()
