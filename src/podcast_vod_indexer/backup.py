from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import os
from pathlib import Path
import sqlite3

from podcast_vod_indexer.db import DB_PATH


DEFAULT_BACKUP_DIR = Path("~/gdrive/Archive/podcast-vod-indexer").expanduser()


@dataclass(frozen=True)
class DatabaseBackupResult:
    database_path: Path
    checksum_path: Path
    checksum: str


def backup_database(
    source_path: Path = DB_PATH,
    backup_dir: Path | None = None,
    now: datetime | None = None,
) -> DatabaseBackupResult:
    source_path = Path(source_path)
    if not source_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {source_path}")

    target_dir = _resolve_backup_dir(backup_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    timestamp = (now or datetime.now().astimezone()).strftime(
        "%Y%m%d-%H%M%S"
    )
    backup_path = _next_backup_path(target_dir / f"index-{timestamp}.db")
    temp_path = backup_path.with_name(f".{backup_path.name}.tmp")

    if temp_path.exists():
        temp_path.unlink()

    try:
        with sqlite3.connect(source_path) as source:
            with sqlite3.connect(temp_path) as target:
                source.backup(target)

        _validate_backup(temp_path)
        temp_path.replace(backup_path)

        checksum = _file_sha256(backup_path)
        checksum_path = backup_path.with_suffix(
            backup_path.suffix + ".sha256"
        )
        checksum_path.write_text(
            f"{checksum}  {backup_path.name}\n",
            encoding="utf-8",
        )
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    return DatabaseBackupResult(
        database_path=backup_path,
        checksum_path=checksum_path,
        checksum=checksum,
    )


def _resolve_backup_dir(backup_dir: Path | None) -> Path:
    if backup_dir is not None:
        return Path(backup_dir).expanduser()

    configured_dir = os.environ.get("PODCAST_VOD_INDEXER_BACKUP_DIR")
    if configured_dir:
        return Path(configured_dir).expanduser()

    return DEFAULT_BACKUP_DIR


def _next_backup_path(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix

    for index in range(1, 1000):
        candidate = path.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate

    raise RuntimeError(f"Could not find unused backup path for {path}")


def _validate_backup(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        result = conn.execute("PRAGMA integrity_check").fetchone()

    if result is None or result[0] != "ok":
        detail = result[0] if result else "no result"
        raise RuntimeError(f"SQLite backup integrity check failed: {detail}")


def _file_sha256(path: Path) -> str:
    digest = sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()
