import unittest

from podcast_vod_indexer.export import load_template, render_rows
from podcast_vod_indexer.export import CLIP_FIELD_SEPARATOR, CLIP_ITEM_SEPARATOR


class ExportHtmlTests(unittest.TestCase):
    def test_rendered_index_has_no_spotify_column(self) -> None:
        rows = [
            (
                "Episode",
                "https://example.com/episode",
                "20260615",
                None,
                None,
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
        self.assertEqual(html.count('<th scope="col">'), 10)
        self.assertEqual(html.count("<td>"), 10)
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
                None,
                None,
                "equivalent_duration",
            )
        ]

        html = render_rows(rows)

        self.assertIn("~ Equivalent upload (not needed)", html)

    def test_renders_clip_and_short_links(self) -> None:
        rows = [
            (
                "Episode",
                "https://example.com/episode",
                "20260615",
                CLIP_ITEM_SEPARATOR.join(
                    [
                        CLIP_FIELD_SEPARATOR.join(
                            ["Clip A", "https://example.com/clip-a"]
                        ),
                        CLIP_FIELD_SEPARATOR.join(
                            ["Clip B", "https://example.com/clip-b"]
                        ),
                    ]
                ),
                CLIP_FIELD_SEPARATOR.join(
                    ["Short A", "https://example.com/short-a"]
                ),
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            )
        ]

        html = render_rows(rows)

        self.assertIn("Clip A", html)
        self.assertIn("Clip B", html)
        self.assertIn("Short A", html)
        self.assertIn('target="_blank" rel="noopener noreferrer"', html)


if __name__ == "__main__":
    unittest.main()
