import unittest
from unittest.mock import MagicMock, patch

from podcast_vod_indexer.cli import run_matching


class LowConfidenceRetryTests(unittest.TestCase):
    @patch("podcast_vod_indexer.cli.upsert_match")
    @patch("podcast_vod_indexer.cli.refine_low_confidence_window_match")
    @patch("podcast_vod_indexer.cli.find_best_window_match")
    @patch("podcast_vod_indexer.cli.get_segments_for_video")
    @patch("podcast_vod_indexer.cli.get_match_confidence_for_episode")
    @patch("podcast_vod_indexer.cli.get_videos_with_segments_by_kind")
    def test_stores_improved_low_confidence_retry(
        self,
        get_videos,
        get_confidence,
        get_segments,
        find_match,
        refine_match,
        upsert_match,
    ) -> None:
        get_videos.side_effect = [
            [(1, "episode-id", "Episode")],
            [(2, "vod-id", "VOD")],
        ]
        get_confidence.return_value = None
        get_segments.side_effect = [
            [{"start": 0.0, "duration": 10.0, "text": "episode"}],
            [{"start": 0.0, "duration": 10.0, "text": "vod"}],
        ]
        find_match.return_value = {
            "start": 900.0,
            "end": 1800.0,
            "score": 0.14,
        }
        refine_match.return_value = {
            "start": 1080.0,
            "end": 1980.0,
            "score": 0.32,
        }
        conn = MagicMock()

        run_matching(conn)

        refine_match.assert_called_once()
        upsert_match.assert_called_once_with(
            conn,
            episode_video_id=1,
            vod_video_id=2,
            matched_start_seconds=1080.0,
            confidence=0.32,
        )

    @patch("podcast_vod_indexer.cli.upsert_match")
    @patch("podcast_vod_indexer.cli.refine_low_confidence_window_match")
    @patch("podcast_vod_indexer.cli.find_best_window_match")
    @patch("podcast_vod_indexer.cli.get_segments_for_video")
    @patch("podcast_vod_indexer.cli.get_match_confidence_for_episode")
    @patch("podcast_vod_indexer.cli.get_videos_with_segments_by_kind")
    def test_does_not_retry_accepted_coarse_match(
        self,
        get_videos,
        get_confidence,
        get_segments,
        find_match,
        refine_match,
        upsert_match,
    ) -> None:
        get_videos.side_effect = [
            [(1, "episode-id", "Episode")],
            [(2, "vod-id", "VOD")],
        ]
        get_confidence.return_value = None
        get_segments.side_effect = [
            [{"start": 0.0, "duration": 10.0, "text": "episode"}],
            [{"start": 0.0, "duration": 10.0, "text": "vod"}],
        ]
        find_match.return_value = {
            "start": 900.0,
            "end": 1800.0,
            "score": 0.20,
        }
        conn = MagicMock()

        run_matching(conn)

        refine_match.assert_not_called()
        upsert_match.assert_called_once_with(
            conn,
            episode_video_id=1,
            vod_video_id=2,
            matched_start_seconds=900.0,
            confidence=0.20,
        )


if __name__ == "__main__":
    unittest.main()
