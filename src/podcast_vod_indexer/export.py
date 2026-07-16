from html import escape
from importlib.resources import files
from pathlib import Path
from string import Template
import sqlite3

from podcast_vod_indexer.db import (
    LONG_EPISODE_DURATION_TOLERANCE_SECONDS,
)


OUTPUT_PATH = Path("output/index.html")
MATCH_CONFIDENCE_CUTOFF = 0.15


def format_time(seconds: float | None) -> str:
    if seconds is None:
        return ""

    start_seconds = int(seconds)
    hours = start_seconds // 3600
    minutes = (start_seconds % 3600) // 60
    seconds = start_seconds % 60
    return f"{hours:02}:{minutes:02}:{seconds:02}"


def link_cell(url: str, label: str, *, new_tab: bool = False) -> str:
    attrs = ""
    if new_tab:
        attrs = ' target="_blank" rel="noopener noreferrer"'

    return (
        f'<a href="{escape(url, quote=True)}"{attrs}>'
        f"{escape(label)}</a>"
    )


def render_rows(rows: list[tuple]) -> str:
    html_rows = []

    for (
        episode_title,
        episode_url,
        episode_date,
        vod_title,
        vod_url,
        vod_date,
        matched_start_seconds,
        confidence,
        long_episode_title,
        long_episode_url,
        long_episode_confidence,
        long_episode_exclusion_reason,
    ) in rows:
        start_seconds = (
            int(matched_start_seconds)
            if matched_start_seconds is not None
            else None
        )

        if (
            confidence is not None
            and confidence >= MATCH_CONFIDENCE_CUTOFF
            and vod_title is not None
            and vod_url is not None
            and vod_date is not None
            and start_seconds is not None
        ):
            timestamped_url = f"{vod_url}&t={start_seconds}s"
            vod_title_cell = link_cell(vod_url, vod_title)
            vod_date_cell = escape(vod_date or "")
            start_time_cell = format_time(matched_start_seconds)
            timestamp_cell = link_cell(timestamped_url, "Open", new_tab=True)
            confidence_cell = f"{confidence * 100:.2f}%"
        else:
            vod_title_cell = ""
            vod_date_cell = ""
            start_time_cell = ""
            timestamp_cell = ""
            confidence_cell = (
                f"{confidence * 100:.2f}%"
                if confidence is not None
                else ""
            )

        if long_episode_url is not None and long_episode_title is not None:
            long_episode_cell = link_cell(
                long_episode_url,
                long_episode_title,
                new_tab=True,
            )
        elif (
            long_episode_url is not None
            and long_episode_confidence is not None
            and long_episode_confidence >= MATCH_CONFIDENCE_CUTOFF
        ):
            long_episode_cell = link_cell(
                long_episode_url,
                "Open",
                new_tab=True,
            )
        else:
            long_episode_cell = ""

        if (
            not long_episode_cell
            and long_episode_exclusion_reason == "equivalent_duration"
        ):
            long_episode_cell = "~ Equivalent upload (not needed)"

        html_rows.extend(
            [
                "      <tr>",
                f"        <td>{episode_cell(episode_url, episode_title)}</td>",
                f"        <td>{escape(episode_date or '')}</td>",
                f"        <td>{long_episode_cell}</td>",
                f"        <td>{vod_title_cell}</td>",
                f"        <td>{vod_date_cell}</td>",
                f"        <td>{start_time_cell}</td>",
                f"        <td>{timestamp_cell}</td>",
                f"        <td>{confidence_cell}</td>",
                "      </tr>",
            ]
        )

    return "\n".join(html_rows)


def episode_cell(url: str | None, title: str | None) -> str:
    if url is None or title is None:
        return "N/a"

    return link_cell(url, title, new_tab=True)


def load_template() -> Template:
    template_text = (
        files("podcast_vod_indexer")
        .joinpath("templates/index.html")
        .read_text(encoding="utf-8")
    )
    return Template(template_text)


def get_export_rows(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute(
        """
        SELECT
            episode_title,
            episode_url,
            episode_date,
            vod_title,
            vod_url,
            vod_date,
            matched_start_seconds,
            confidence,
            long_episode_title,
            long_episode_url,
            long_episode_confidence,
            long_episode_exclusion_reason
        FROM (
            SELECT
                e.title AS episode_title,
                e.webpage_url AS episode_url,
                e.upload_date AS episode_date,
                v.title AS vod_title,
                v.webpage_url AS vod_url,
                v.upload_date AS vod_date,
                m.matched_start_seconds AS matched_start_seconds,
                m.confidence AS confidence,
                NULL AS long_episode_title,
                le.webpage_url AS long_episode_url,
                elm.confidence AS long_episode_confidence,
                ele.reason AS long_episode_exclusion_reason,
                e.upload_date AS sort_date
            FROM videos e
            LEFT JOIN matches m ON m.episode_video_id = e.id
            LEFT JOIN videos v ON v.id = m.vod_video_id
            LEFT JOIN episode_long_matches elm
                ON elm.short_episode_video_id = e.id
                AND NOT EXISTS (
                    SELECT 1
                    FROM videos candidate_long
                    WHERE candidate_long.id = elm.long_episode_video_id
                      AND e.duration_seconds IS NOT NULL
                      AND candidate_long.duration_seconds
                          <= e.duration_seconds + ?
                )
            LEFT JOIN videos le ON le.id = elm.long_episode_video_id
            LEFT JOIN episode_long_exclusions ele
                ON ele.short_episode_video_id = e.id
            WHERE e.kind = 'episode'
              AND EXISTS (
                  SELECT 1
                  FROM segments episode_segment
                  WHERE episode_segment.video_id = e.id
              )

            UNION ALL

            SELECT
                NULL AS episode_title,
                NULL AS episode_url,
                long_episode.upload_date AS episode_date,
                fallback_vod.title AS vod_title,
                fallback_vod.webpage_url AS vod_url,
                fallback_vod.upload_date AS vod_date,
                fallback_match.matched_start_seconds AS matched_start_seconds,
                fallback_match.confidence AS confidence,
                long_episode.title AS long_episode_title,
                long_episode.webpage_url AS long_episode_url,
                1.0 AS long_episode_confidence,
                NULL AS long_episode_exclusion_reason,
                long_episode.upload_date AS sort_date
            FROM videos long_episode
            LEFT JOIN episode_long_vod_matches fallback_match
                ON fallback_match.long_episode_video_id = long_episode.id
            LEFT JOIN videos fallback_vod
                ON fallback_vod.id = fallback_match.vod_video_id
            WHERE long_episode.kind = 'episode_long'
              AND EXISTS (
                  SELECT 1
                  FROM segments long_episode_segment
                  WHERE long_episode_segment.video_id = long_episode.id
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM episode_long_matches normal_long_match
                  WHERE normal_long_match.long_episode_video_id =
                      long_episode.id
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM episode_long_exclusions normal_long_exclusion
                  WHERE normal_long_exclusion.long_episode_video_id =
                      long_episode.id
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM matches normal_vod_match
                  WHERE normal_vod_match.vod_video_id =
                      fallback_match.vod_video_id
                    AND normal_vod_match.confidence >= ?
              )
        )
        ORDER BY sort_date DESC
        """,
        (
            LONG_EPISODE_DURATION_TOLERANCE_SECONDS,
            MATCH_CONFIDENCE_CUTOFF,
        ),
    ).fetchall()


def export_matches_html(conn: sqlite3.Connection) -> None:
    rows = get_export_rows(conn)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    html = load_template().substitute(rows=render_rows(rows))
    OUTPUT_PATH.write_text(html, encoding="utf-8")
