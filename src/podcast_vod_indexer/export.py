from html import escape
from importlib.resources import files
from pathlib import Path
from string import Template
import sqlite3


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
        long_episode_url,
        long_episode_confidence,
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

        html_rows.extend(
            [
                "      <tr>",
                "        <td>"
                f"{link_cell(episode_url, episode_title)}</td>",
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
            v.title,
            v.webpage_url,
            v.upload_date,
            m.matched_start_seconds,
            m.confidence,
            le.webpage_url,
            elm.confidence
        FROM videos e
        JOIN segments s ON s.video_id = e.id
        LEFT JOIN matches m ON m.episode_video_id = e.id
        LEFT JOIN videos v ON v.id = m.vod_video_id
        LEFT JOIN episode_long_matches elm
            ON elm.short_episode_video_id = e.id
        LEFT JOIN videos le ON le.id = elm.long_episode_video_id
        WHERE e.kind = 'episode'
        GROUP BY
            e.id,
            e.title,
            e.webpage_url,
            e.upload_date,
            v.title,
            v.webpage_url,
            v.upload_date,
            m.matched_start_seconds,
            m.confidence,
            le.webpage_url,
            elm.confidence
        ORDER BY e.upload_date DESC
        """
    ).fetchall()

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    html = load_template().substitute(rows=render_rows(rows))
    OUTPUT_PATH.write_text(html, encoding="utf-8")
