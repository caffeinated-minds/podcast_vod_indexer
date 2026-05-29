from pathlib import Path
import sqlite3


OUTPUT_PATH = Path("output/index.html")
MATCH_CONFIDENCE_CUTOFF = 0.15


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
            le.title,
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
            le.title,
            le.webpage_url,
            elm.confidence
        ORDER BY e.upload_date DESC
        """
    ).fetchall()

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    html = [
        "<!doctype html>",
        "<html>",
        "<head>",
        '  <meta charset="utf-8">',
        "  <title>Podcast VOD Index</title>",
        "</head>",
        "<body>",
        "  <h1>Podcast VOD Index</h1>",
        "  <table border='1' cellspacing='0' cellpadding='6'>",
        "    <thead>",
        "      <tr>",
        "        <th>Episode</th>",
        "        <th>Episode Date</th>",
        "        <th>VOD</th>",
        "        <th>VOD Date</th>",
        "        <th>Start Time</th>",
        "        <th>Timestamp Link</th>",
        "        <th>Long Episode</th>",
        "        <th>Confidence <br/>(cutoff 15%)</th>",
        "      </tr>",
        "    </thead>",
        "    <tbody>",
    ]

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
    ) in rows:
        if matched_start_seconds is not None:
            start_seconds = int(matched_start_seconds)
            hours = start_seconds // 3600
            minutes = (start_seconds % 3600) // 60
            seconds = start_seconds % 60
            start_time = f"{hours:02}:{minutes:02}:{seconds:02}"
        else:
            start_seconds = None
            start_time = "N/a"

        if (
            confidence is not None
            and confidence >= MATCH_CONFIDENCE_CUTOFF
            and vod_title is not None
            and vod_url is not None
            and vod_date is not None
            and start_seconds is not None
        ):
            timestamped_url = f"{vod_url}&t={start_seconds}s"
            vod_title_cell = f'<a href="{vod_url}">{vod_title}</a>'
            vod_date_cell = vod_date
            start_time_cell = start_time
            timestamp_cell = (
                f'<a href="{timestamped_url}" target="_blank" '
                f'rel="noopener noreferrer">Open</a>'
            )
            confidence_cell = f"{confidence * 100:.2f}%"
        else:
            vod_title_cell = "N/a"
            vod_date_cell = "N/a"
            start_time_cell = "N/a"
            timestamp_cell = "N/a"
            confidence_cell = (
                f"{confidence * 100:.2f}%"
                if confidence is not None
                else "N/a"
            )

        if (
            long_episode_title is not None
            and long_episode_url is not None
            and long_episode_confidence is not None
            and long_episode_confidence >= MATCH_CONFIDENCE_CUTOFF
        ):
            long_episode_cell = (
                f'<a href="{long_episode_url}">{long_episode_title}</a>'
            )
        else:
            long_episode_cell = "N/a"

        html.extend(
            [
                "      <tr>",
                f'        <td><a href="{episode_url}">{episode_title}</a></td>',
                f"        <td>{episode_date}</td>",
                f"        <td>{vod_title_cell}</td>",
                f"        <td>{vod_date_cell}</td>",
                f"        <td>{start_time_cell}</td>",
                f"        <td>{timestamp_cell}</td>",
                f"        <td>{long_episode_cell}</td>",
                f"        <td>{confidence_cell}</td>",
                "      </tr>",
            ]
        )

    html.extend(
        [
            "    </tbody>",
            "  </table>",
            "</body>",
            "</html>",
        ]
    )

    OUTPUT_PATH.write_text("\n".join(html), encoding="utf-8")
