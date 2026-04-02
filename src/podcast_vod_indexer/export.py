from pathlib import Path
import sqlite3


OUTPUT_PATH = Path("output/index.html")


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
            m.confidence
        FROM matches m
        JOIN videos e ON e.id = m.episode_video_id
        JOIN videos v ON v.id = m.vod_video_id
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
        "        <th>Confidence</th>",
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
    ) in rows:
        start_seconds = int(matched_start_seconds)
        hours = start_seconds // 3600
        minutes = (start_seconds % 3600) // 60
        seconds = start_seconds % 60
        start_time = f"{hours:02}:{minutes:02}:{seconds:02}"
        timestamped_url = f"{vod_url}&t={start_seconds}s"

        html.extend(
            [
                "      <tr>",
                (
                    '        <td><a href="'
                    f"{episode_url}"
                    '">'
                    f"{episode_title}"
                    "</a></td>"
                ),
                f"        <td>{episode_date}</td>",
                (
                    '        <td><a href="'
                    f"{vod_url}"
                    '">'
                    f"{vod_title}"
                    "</a></td>"
                ),
                f"        <td>{vod_date}</td>",
                f"        <td>{start_time}</td>",
                (
                    '        <td><a href="'
                    f"{timestamped_url}"
                    '">Open</a></td>'
                ),
                f"        <td>{confidence:.4f}</td>",
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