import sqlite3
from pathlib import Path

DB_PATH = Path("data/index.db")
LONG_EPISODE_DURATION_TOLERANCE_SECONDS = 5


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
                match_method TEXT,
                FOREIGN KEY(short_episode_video_id) REFERENCES videos(id),
                FOREIGN KEY(long_episode_video_id) REFERENCES videos(id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS episode_long_exclusions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                short_episode_video_id INTEGER UNIQUE,
                long_episode_video_id INTEGER,
                reason TEXT NOT NULL,
                FOREIGN KEY(short_episode_video_id) REFERENCES videos(id),
                FOREIGN KEY(long_episode_video_id) REFERENCES videos(id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS clip_matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                clip_video_id INTEGER UNIQUE,
                episode_video_id INTEGER,
                matched_against_video_id INTEGER,
                matched_start_seconds REAL,
                confidence REAL,
                match_method TEXT,
                FOREIGN KEY(clip_video_id) REFERENCES videos(id),
                FOREIGN KEY(episode_video_id) REFERENCES videos(id),
                FOREIGN KEY(matched_against_video_id) REFERENCES videos(id)
            )
            """
        )

        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(episode_long_matches)"
            ).fetchall()
        }
        if "match_method" not in columns:
            conn.execute(
                "ALTER TABLE episode_long_matches ADD COLUMN match_method TEXT"
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


def get_episode_long_match_for_episode(
    conn, short_episode_video_id: int
) -> tuple[float, str | None] | None:
    row = conn.execute(
        """
        SELECT confidence, match_method
        FROM episode_long_matches
        WHERE short_episode_video_id = ?
        """,
        (short_episode_video_id,),
    ).fetchone()

    return (row[0], row[1]) if row else None


def get_clip_match_confidence_for_clip(
    conn, clip_video_id: int
) -> float | None:
    row = conn.execute(
        """
        SELECT confidence
        FROM clip_matches
        WHERE clip_video_id = ?
        """,
        (clip_video_id,),
    ).fetchone()

    return row[0] if row else None


def get_first_episode_matched_vod_date(
    conn,
    min_confidence: float,
) -> str | None:
    row = conn.execute(
        """
        SELECT vod.upload_date
        FROM videos episode
        JOIN matches match ON match.episode_video_id = episode.id
        JOIN videos vod ON vod.id = match.vod_video_id
        WHERE episode.id = (
            SELECT id
            FROM videos
            WHERE kind = 'episode'
            ORDER BY upload_date ASC
            LIMIT 1
        )
          AND match.confidence >= ?
          AND vod.upload_date IS NOT NULL
        """,
        (min_confidence,),
    ).fetchone()

    return row[0] if row else None


def prune_vods_before_date(conn, min_upload_date: str) -> tuple[int, int]:
    referenced_count = conn.execute(
        """
        SELECT COUNT(*)
        FROM matches match
        JOIN videos vod ON vod.id = match.vod_video_id
        WHERE vod.kind = 'vod'
          AND vod.upload_date < ?
        """,
        (min_upload_date,),
    ).fetchone()[0]

    if referenced_count:
        raise RuntimeError(
            "Cannot prune VODs that are referenced by existing matches."
        )

    segment_count = conn.execute(
        """
        SELECT COUNT(*)
        FROM segments
        WHERE video_id IN (
            SELECT id
            FROM videos
            WHERE kind = 'vod'
              AND upload_date < ?
        )
        """,
        (min_upload_date,),
    ).fetchone()[0]
    vod_count = conn.execute(
        """
        SELECT COUNT(*)
        FROM videos
        WHERE kind = 'vod'
          AND upload_date < ?
        """,
        (min_upload_date,),
    ).fetchone()[0]

    conn.execute(
        """
        DELETE FROM segments
        WHERE video_id IN (
            SELECT id
            FROM videos
            WHERE kind = 'vod'
              AND upload_date < ?
        )
        """,
        (min_upload_date,),
    )
    conn.execute(
        """
        DELETE FROM videos
        WHERE kind = 'vod'
          AND upload_date < ?
        """,
        (min_upload_date,),
    )

    return vod_count, segment_count


def get_matched_long_episode_ids(conn) -> set[int]:
    rows = conn.execute(
        """
        SELECT long_episode_video_id
        FROM episode_long_matches
        WHERE long_episode_video_id IS NOT NULL
        """
    ).fetchall()

    return {row[0] for row in rows}


def get_excluded_long_episode_match_ids(conn) -> set[int]:
    rows = conn.execute(
        """
        SELECT short_episode_video_id
        FROM episode_long_exclusions
        """
    ).fetchall()

    return {row[0] for row in rows}


def get_excluded_long_episode_ids(conn) -> set[int]:
    rows = conn.execute(
        """
        SELECT long_episode_video_id
        FROM episode_long_exclusions
        WHERE long_episode_video_id IS NOT NULL
        """
    ).fetchall()

    return {row[0] for row in rows}


def get_video_durations_by_kind(conn, kind: str) -> dict[int, int]:
    rows = conn.execute(
        """
        SELECT id, duration_seconds
        FROM videos
        WHERE kind = ?
          AND duration_seconds IS NOT NULL
        """,
        (kind,),
    ).fetchall()

    return {row[0]: row[1] for row in rows}


def remove_non_distinct_long_episode_matches(conn) -> int:
    conn.execute(
        """
        INSERT INTO episode_long_exclusions (
            short_episode_video_id,
            long_episode_video_id,
            reason
        )
        SELECT
            match.short_episode_video_id,
            match.long_episode_video_id,
            'equivalent_duration'
        FROM episode_long_matches match
        JOIN videos episode
            ON episode.id = match.short_episode_video_id
        JOIN videos long_episode
            ON long_episode.id = match.long_episode_video_id
        WHERE episode.duration_seconds IS NOT NULL
          AND long_episode.duration_seconds
              <= episode.duration_seconds + ?
        ON CONFLICT(short_episode_video_id)
        DO UPDATE SET
            long_episode_video_id = excluded.long_episode_video_id,
            reason = excluded.reason
        """,
        (LONG_EPISODE_DURATION_TOLERANCE_SECONDS,),
    )

    cursor = conn.execute(
        """
        DELETE FROM episode_long_matches
        WHERE id IN (
            SELECT match.id
            FROM episode_long_matches match
            JOIN videos episode
                ON episode.id = match.short_episode_video_id
            JOIN videos long_episode
                ON long_episode.id = match.long_episode_video_id
            WHERE episode.duration_seconds IS NOT NULL
              AND long_episode.duration_seconds
                  <= episode.duration_seconds + ?
        )
        """,
        (LONG_EPISODE_DURATION_TOLERANCE_SECONDS,),
    )

    return cursor.rowcount


def get_videos_without_segments_by_kind(
        conn, kind: str, limit: int, min_upload_date: str | None = None
        ) -> list[tuple[int, str, str]]:
    rows = conn.execute(
        """
        SELECT v.id, v.youtube_id, v.webpage_url
        FROM videos v
        WHERE v.kind = ?
          AND (? IS NULL OR v.upload_date >= ?)
          AND NOT EXISTS (
              SELECT 1
              FROM segments s
              WHERE s.video_id = v.id
          )
        ORDER BY v.upload_date DESC
        LIMIT ?
        """,
        (kind, min_upload_date, min_upload_date, limit),
    ).fetchall()

    return rows


def get_videos_with_segments_by_kind(
    conn, kind: str, min_upload_date: str | None = None
) -> list[tuple[int, str, str]]:
    rows = conn.execute(
        """
        SELECT v.id, v.youtube_id, v.title
        FROM videos v
        WHERE v.kind = ?
          AND (? IS NULL OR v.upload_date >= ?)
          AND EXISTS (
              SELECT 1
              FROM segments s
              WHERE s.video_id = v.id
          )
        ORDER BY v.upload_date DESC
        """,
        (kind, min_upload_date, min_upload_date),
    ).fetchall()

    return rows


def get_videos_with_segments_by_kinds(
    conn,
    kinds: list[str],
) -> list[tuple[int, str, str, str, str | None]]:
    if not kinds:
        return []

    placeholders = ", ".join("?" for _ in kinds)
    rows = conn.execute(
        f"""
        SELECT v.id, v.youtube_id, v.kind, v.title, v.upload_date
        FROM videos v
        WHERE v.kind IN ({placeholders})
          AND EXISTS (
              SELECT 1
              FROM segments s
              WHERE s.video_id = v.id
          )
        ORDER BY v.upload_date DESC
        """,
        kinds,
    ).fetchall()

    return rows


def get_clip_episode_match_targets(
    conn,
    min_confidence: float,
) -> list[tuple[int, str, str, str | None, int]]:
    rows = conn.execute(
        """
        WITH long_targets AS (
            SELECT
                short_episode_video_id,
                long_episode_video_id
            FROM episode_long_matches
            WHERE confidence >= ?

            UNION

            SELECT
                short_episode_video_id,
                long_episode_video_id
            FROM episode_long_exclusions
            WHERE long_episode_video_id IS NOT NULL
        )
        SELECT
            episode.id,
            episode.youtube_id,
            episode.title,
            episode.upload_date,
            long_episode.id AS matched_against_video_id
        FROM videos episode
        JOIN long_targets target
            ON target.short_episode_video_id = episode.id
        JOIN videos long_episode
            ON long_episode.id = target.long_episode_video_id
            AND long_episode.kind = 'episode_long'
        WHERE episode.kind = 'episode'
          AND EXISTS (
              SELECT 1
              FROM segments episode_segment
              WHERE episode_segment.video_id = episode.id
          )
          AND EXISTS (
              SELECT 1
              FROM segments target_segment
              WHERE target_segment.video_id = long_episode.id
          )
        ORDER BY episode.upload_date DESC
        """,
        (min_confidence,),
    ).fetchall()

    return rows


def get_videos_with_segments_by_kind_and_date(
    conn, kind: str, min_upload_date: str | None = None
) -> list[tuple[int, str, str, str | None]]:
    rows = conn.execute(
        """
        SELECT v.id, v.youtube_id, v.title, v.upload_date
        FROM videos v
        WHERE v.kind = ?
          AND (? IS NULL OR v.upload_date >= ?)
          AND EXISTS (
              SELECT 1
              FROM segments s
              WHERE s.video_id = v.id
          )
        ORDER BY v.upload_date DESC
        """,
        (kind, min_upload_date, min_upload_date),
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
    match_method: str,
) -> None:
    conn.execute(
        """
        DELETE FROM episode_long_exclusions
        WHERE short_episode_video_id = ?
        """,
        (short_episode_video_id,),
    )
    conn.execute(
        """
        INSERT INTO episode_long_matches (
            short_episode_video_id,
            long_episode_video_id,
            confidence,
            match_method
        )
        VALUES (?, ?, ?, ?)
        ON CONFLICT(short_episode_video_id)
        DO UPDATE SET
            long_episode_video_id = excluded.long_episode_video_id,
            confidence = excluded.confidence,
            match_method = excluded.match_method
        """,
        (
            short_episode_video_id,
            long_episode_video_id,
            confidence,
            match_method,
        ),
    )


def upsert_clip_match(
    conn,
    clip_video_id: int,
    episode_video_id: int,
    matched_against_video_id: int,
    matched_start_seconds: float,
    confidence: float,
    match_method: str,
) -> None:
    conn.execute(
        """
        INSERT INTO clip_matches (
            clip_video_id,
            episode_video_id,
            matched_against_video_id,
            matched_start_seconds,
            confidence,
            match_method
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(clip_video_id)
        DO UPDATE SET
            episode_video_id = excluded.episode_video_id,
            matched_against_video_id = excluded.matched_against_video_id,
            matched_start_seconds = excluded.matched_start_seconds,
            confidence = excluded.confidence,
            match_method = excluded.match_method
        """,
        (
            clip_video_id,
            episode_video_id,
            matched_against_video_id,
            matched_start_seconds,
            confidence,
            match_method,
        ),
    )
