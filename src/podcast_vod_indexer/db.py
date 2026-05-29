import sqlite3
from pathlib import Path

DB_PATH = Path("data/index.db")


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                youtube_id TEXT UNIQUE,
                kind TEXT,
                title TEXT,
                uploader TEXT,
                upload_date TEXT,
                duration_seconds INTEGER,
                webpage_url TEXT
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id INTEGER,
                start REAL,
                duration REAL,
                text TEXT,
                FOREIGN KEY(video_id) REFERENCES videos(id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                episode_video_id INTEGER UNIQUE,
                vod_video_id INTEGER,
                matched_start_seconds REAL,
                confidence REAL,
                FOREIGN KEY(episode_video_id) REFERENCES videos(id),
                FOREIGN KEY(vod_video_id) REFERENCES videos(id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS episode_long_matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                short_episode_video_id INTEGER UNIQUE,
                long_episode_video_id INTEGER,
                confidence REAL,
                FOREIGN KEY(short_episode_video_id) REFERENCES videos(id),
                FOREIGN KEY(long_episode_video_id) REFERENCES videos(id)
            )
            """
        )


def insert_video(conn, video: dict) -> int:
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO videos (
            youtube_id, kind, title, uploader, upload_date,
            duration_seconds, webpage_url
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            video["youtube_id"],
            video["kind"],
            video["title"],
            video["uploader"],
            video["upload_date"],
            video["duration_seconds"],
            video["webpage_url"],
        ),
    )

    if cursor.lastrowid:
        return cursor.lastrowid

    # already exists → fetch id
    row = conn.execute(
        "SELECT id FROM videos WHERE youtube_id = ?",
        (video["youtube_id"],),
    ).fetchone()

    return row[0]


def insert_segments(conn, video_id: int, segments: list[dict]) -> None:
    conn.execute("DELETE FROM segments WHERE video_id = ?", (video_id,))

    conn.executemany(
        """
        INSERT INTO segments (video_id, start, duration, text)
        VALUES (?, ?, ?, ?)
        """,
        [
            (video_id, s["start"], s["duration"], s["text"])
            for s in segments
        ],
    )


def video_has_segments(conn, video_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM segments WHERE video_id = ? LIMIT 1",
        (video_id,),
    ).fetchone()

    return row is not None


def get_video_id_by_youtube_id(conn, youtube_id: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM videos WHERE youtube_id = ?",
        (youtube_id,),
    ).fetchone()

    return row[0] if row else None


def get_videos_by_kind(conn, kind: str) -> list[tuple[int, str, str]]:
    rows = conn.execute(
        """
        SELECT id, youtube_id, title
        FROM videos
        WHERE kind = ?
        ORDER BY upload_date DESC
        """,
        (kind,),
    ).fetchall()

    return rows


def get_segments_for_video(conn, video_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT start, duration, text
        FROM segments
        WHERE video_id = ?
        ORDER BY start ASC
        """,
        (video_id,),
    ).fetchall()

    return [
        {
            "start": row[0],
            "duration": row[1],
            "text": row[2],
        }
        for row in rows
    ]


def get_match_confidence_for_episode(
    conn, episode_video_id: int
) -> float | None:
    row = conn.execute(
        """
        SELECT confidence
        FROM matches
        WHERE episode_video_id = ?
        """,
        (episode_video_id,),
    ).fetchone()

    return row[0] if row else None


def get_videos_without_segments_by_kind(
        conn, kind: str, limit: int
        ) -> list[tuple[int, str, str]]:
    rows = conn.execute(
        """
        SELECT v.id, v.youtube_id, v.webpage_url
        FROM videos v
        WHERE v.kind = ?
          AND NOT EXISTS (
              SELECT 1
              FROM segments s
              WHERE s.video_id = v.id
          )
        ORDER BY v.upload_date DESC
        LIMIT ?
        """,
        (kind, limit),
    ).fetchall()

    return rows


def get_videos_with_segments_by_kind(
    conn, kind: str
) -> list[tuple[int, str, str]]:
    rows = conn.execute(
        """
        SELECT v.id, v.youtube_id, v.title
        FROM videos v
        WHERE v.kind = ?
          AND EXISTS (
              SELECT 1
              FROM segments s
              WHERE s.video_id = v.id
          )
        ORDER BY v.upload_date DESC
        """,
        (kind,),
    ).fetchall()

    return rows


def upsert_match(
    conn,
    episode_video_id: int,
    vod_video_id: int,
    matched_start_seconds: float,
    confidence: float,
) -> None:
    conn.execute(
        """
        INSERT INTO matches (
            episode_video_id,
            vod_video_id,
            matched_start_seconds,
            confidence
        )
        VALUES (?, ?, ?, ?)
        ON CONFLICT(episode_video_id)
        DO UPDATE SET
            vod_video_id = excluded.vod_video_id,
            matched_start_seconds = excluded.matched_start_seconds,
            confidence = excluded.confidence
        """,
        (
            episode_video_id,
            vod_video_id,
            matched_start_seconds,
            confidence,
        ),
    )


def upsert_episode_long_match(
    conn,
    short_episode_video_id: int,
    long_episode_video_id: int,
    confidence: float,
) -> None:
    conn.execute(
        """
        INSERT INTO episode_long_matches (
            short_episode_video_id,
            long_episode_video_id,
            confidence
        )
        VALUES (?, ?, ?)
        ON CONFLICT(short_episode_video_id)
        DO UPDATE SET
            long_episode_video_id = excluded.long_episode_video_id,
            confidence = excluded.confidence
        """,
        (
            short_episode_video_id,
            long_episode_video_id,
            confidence,
        ),
    )
