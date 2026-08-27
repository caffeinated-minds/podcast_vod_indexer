from datetime import datetime
from pathlib import Path
import sqlite3
import tempfile
import unittest

from podcast_vod_indexer.backup import backup_database


class DatabaseBackupTests(unittest.TestCase):
    def test_creates_valid_sqlite_backup_and_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_path = temp_path / "index.db"
            backup_dir = temp_path / "backups"

            with sqlite3.connect(source_path) as conn:
                conn.execute("CREATE TABLE example (value TEXT)")
                conn.execute("INSERT INTO example VALUES ('stored')")

            result = backup_database(
                source_path=source_path,
                backup_dir=backup_dir,
                now=datetime(2026, 8, 27, 12, 30, 0),
            )

            self.assertEqual(
                result.database_path,
                backup_dir / "index-20260827-123000.db",
            )
            self.assertTrue(result.checksum_path.is_file())
            self.assertEqual(len(result.checksum), 64)

            with sqlite3.connect(result.database_path) as conn:
                integrity = conn.execute(
                    "PRAGMA integrity_check"
                ).fetchone()
                value = conn.execute(
                    "SELECT value FROM example"
                ).fetchone()

            self.assertEqual(integrity, ("ok",))
            self.assertEqual(value, ("stored",))

            checksum_text = result.checksum_path.read_text(encoding="utf-8")
            self.assertEqual(
                checksum_text,
                f"{result.checksum}  index-20260827-123000.db\n",
            )

    def test_uses_numbered_name_when_timestamp_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_path = temp_path / "index.db"
            backup_dir = temp_path / "backups"
            backup_dir.mkdir()
            existing_backup = backup_dir / "index-20260827-123000.db"
            existing_backup.write_text("existing", encoding="utf-8")

            with sqlite3.connect(source_path) as conn:
                conn.execute("CREATE TABLE example (value TEXT)")

            result = backup_database(
                source_path=source_path,
                backup_dir=backup_dir,
                now=datetime(2026, 8, 27, 12, 30, 0),
            )

            self.assertEqual(
                result.database_path,
                backup_dir / "index-20260827-123000-1.db",
            )
