import unittest

from podcast_vod_indexer.export import load_template, render_rows


class ExportHtmlTests(unittest.TestCase):
    def test_rendered_index_has_no_spotify_column(self) -> None:
        rows = [
            (
                "Episode",
                "https://example.com/episode",
                "20260615",
                "VOD",
                "https://example.com/vod",
                "20260614",
                60.0,
                0.5,
                "https://example.com/long-episode",
                0.5,
                None,
            )
        ]

        html = load_template().substitute(rows=render_rows(rows))

        self.assertNotIn("Spotify", html)
        self.assertEqual(html.count('<th scope="col">'), 8)
        self.assertEqual(html.count("<td>"), 8)
        self.assertIn(
            '<a href="https://example.com/episode" '
            'target="_blank" rel="noopener noreferrer">Episode</a>',
            html,
        )

    def test_marks_equivalent_long_episode_as_not_needed(self) -> None:
        rows = [
            (
                "Episode",
                "https://example.com/episode",
                "20260615",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                "equivalent_duration",
            )
        ]

        html = render_rows(rows)

        self.assertIn("~ Equivalent upload (not needed)", html)


if __name__ == "__main__":
    unittest.main()
