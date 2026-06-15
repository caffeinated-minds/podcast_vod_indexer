import sqlite3
import unittest
from unittest.mock import patch

from podcast_vod_indexer.db import init_db


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


if __name__ == "__main__":
    unittest.main()
