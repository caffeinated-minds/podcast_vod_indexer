import json
import unittest
from unittest.mock import MagicMock, patch

from podcast_vod_indexer.youtube import YTDLP_BIN, get_latest_videos


class PlaylistDiscoveryTests(unittest.TestCase):
    @patch("podcast_vod_indexer.youtube.subprocess.run")
    def test_uses_browser_cookies_for_playlist_discovery(
        self,
        run,
    ) -> None:
        run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(
                {
                    "entries": [
                        {
                            "id": "member-vod",
                            "title": "Members-only VOD",
                            "url": "member-vod",
                        }
                    ]
                }
            ),
        )

        videos = get_latest_videos(
            "https://example.com/streams",
            limit=25,
        )

        run.assert_called_once_with(
            [
                YTDLP_BIN,
                "--cookies-from-browser",
                "brave+gnomekeyring",
                "--dump-single-json",
                "--flat-playlist",
                "--skip-download",
                "--playlist-end",
                "25",
                "https://example.com/streams",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            videos,
            [
                {
                    "youtube_id": "member-vod",
                    "title": "Members-only VOD",
                    "webpage_url": (
                        "https://www.youtube.com/watch?v=member-vod"
                    ),
                }
            ],
        )

    @patch("podcast_vod_indexer.youtube.subprocess.run")
    def test_raises_when_authenticated_discovery_fails(self, run) -> None:
        run.return_value = MagicMock(
            returncode=1,
            stderr="browser keyring unavailable",
        )

        with self.assertRaisesRegex(RuntimeError, "keyring unavailable"):
            get_latest_videos("https://example.com/streams")


if __name__ == "__main__":
    unittest.main()
