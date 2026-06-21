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
CLIP_ITEM_SEPARATOR = "\x1e"
CLIP_FIELD_SEPARATOR = "\x1f"


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


def multi_link_cell(serialized_links: str | None) -> str:
    if not serialized_links:
        return ""

    links = []
    for item in serialized_links.split(CLIP_ITEM_SEPARATOR):
        title, url = item.split(CLIP_FIELD_SEPARATOR, 1)
        links.append(link_cell(url, title, new_tab=True))

    return ", ".join(links)


def render_rows(rows: list[tuple]) -> str:
    html_rows = []

    for (
        episode_title,
        episode_url,
        episode_date,
        clip_links,
        short_links,
        vod_title,
        vod_url,
        vod_date,
        matched_start_seconds,
        confidence,
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

        if (
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
                "        <td>"
                f"{link_cell(episode_url, episode_title, new_tab=True)}</td>",
                f"        <td>{escape(episode_date or '')}</td>",
                f"        <td>{multi_link_cell(clip_links)}</td>",
                f"        <td>{multi_link_cell(short_links)}</td>",
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


def load_template() -> Template:
    template_text = (
        files("podcast_vod_indexer")
        .joinpath("templates/index.html")
        .read_text(encoding="utf-8")
    )
    return Template(template_text)


def export_matches_html(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT
            e.title,
            e.webpage_url,
            e.upload_date,
            (
                SELECT GROUP_CONCAT(
                    clip_row.title || ? || clip_row.webpage_url,
                    ?
                )
                FROM (
                    SELECT clip.title, clip.webpage_url
                    FROM clip_matches clip_match
                    JOIN videos clip
                        ON clip.id = clip_match.clip_video_id
                    WHERE clip_match.episode_video_id = e.id
                      AND clip.kind = 'clip'
                      AND clip_match.confidence >= ?
                    ORDER BY clip.upload_date DESC
                ) clip_row
            ),
            (
                SELECT GROUP_CONCAT(
                    short_row.title || ? || short_row.webpage_url,
                    ?
                )
                FROM (
                    SELECT short.title, short.webpage_url
                    FROM clip_matches short_match
                    JOIN videos short
                        ON short.id = short_match.clip_video_id
                    WHERE short_match.episode_video_id = e.id
                      AND short.kind = 'short'
                      AND short_match.confidence >= ?
                    ORDER BY short.upload_date DESC
                ) short_row
            ),
            v.title,
            v.webpage_url,
            v.upload_date,
            m.matched_start_seconds,
            m.confidence,
            le.webpage_url,
            elm.confidence,
            ele.reason
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
        ORDER BY e.upload_date DESC
        """,
        (
            CLIP_FIELD_SEPARATOR,
            CLIP_ITEM_SEPARATOR,
            MATCH_CONFIDENCE_CUTOFF,
            CLIP_FIELD_SEPARATOR,
            CLIP_ITEM_SEPARATOR,
            MATCH_CONFIDENCE_CUTOFF,
            LONG_EPISODE_DURATION_TOLERANCE_SECONDS,
        ),
    ).fetchall()

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    html = load_template().substitute(rows=render_rows(rows))
    OUTPUT_PATH.write_text(html, encoding="utf-8")
