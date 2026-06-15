import unittest
from unittest.mock import MagicMock, patch

from podcast_vod_indexer.cli import (
    TranscriptFetchResults,
    fetch_missing_transcripts_with_budget,
    fetch_transcripts_for_videos,
    main,
    process_source,
    run_long_episode_matching,
    run_matching,
)


class SourceProcessingTests(unittest.TestCase):
    @patch("podcast_vod_indexer.cli.insert_video")
    @patch("podcast_vod_indexer.cli.get_video_info")
    @patch("podcast_vod_indexer.cli.get_video_id_by_youtube_id")
    @patch("podcast_vod_indexer.cli.get_latest_videos")
    def test_stops_collecting_vod_metadata_at_cutoff(
        self,
        get_latest_videos,
        get_video_id,
        get_video_info,
        insert_video,
    ) -> None:
        get_latest_videos.return_value = [
            {"youtube_id": "new", "webpage_url": "https://example.com/new"},
            {"youtube_id": "old", "webpage_url": "https://example.com/old"},
            {
                "youtube_id": "older",
                "webpage_url": "https://example.com/older",
            },
        ]
        get_video_id.return_value = None
        get_video_info.side_effect = [
            {
                "youtube_id": "new",
                "kind": "vod",
                "upload_date": "20250306",
            },
            {
                "youtube_id": "old",
                "kind": "vod",
                "upload_date": "20250304",
            },
        ]
        conn = MagicMock()

        process_source(
            conn,
            "https://example.com/streams",
            kind="vod",
            min_upload_date="20250305",
        )

        self.assertEqual(get_video_info.call_count, 2)
        insert_video.assert_called_once_with(
            conn,
            {
                "youtube_id": "new",
                "kind": "vod",
                "upload_date": "20250306",
            },
        )


class LowConfidenceRetryTests(unittest.TestCase):
    @patch("podcast_vod_indexer.cli.upsert_match")
    @patch("podcast_vod_indexer.cli.find_best_window_match")
    @patch("podcast_vod_indexer.cli.get_segments_for_video")
    @patch("podcast_vod_indexer.cli.get_match_confidence_for_episode")
    @patch("podcast_vod_indexer.cli.get_videos_with_segments_by_kind")
    def test_does_not_rerun_existing_accepted_vod_match(
        self,
        get_videos,
        get_confidence,
        get_segments,
        find_match,
        upsert_match,
    ) -> None:
        get_videos.return_value = [(1, "episode-id", "Episode")]
        get_confidence.return_value = 0.20

        run_matching(MagicMock())

        get_videos.assert_called_once()
        get_segments.assert_not_called()
        find_match.assert_not_called()
        upsert_match.assert_not_called()

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
        get_confidence.return_value = 0.14
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

        run_matching(conn, new_vod_transcript_ids={2})

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

    @patch("podcast_vod_indexer.cli.upsert_match")
    @patch("podcast_vod_indexer.cli.find_best_window_match")
    @patch("podcast_vod_indexer.cli.get_segments_for_video")
    @patch("podcast_vod_indexer.cli.get_match_confidence_for_episode")
    @patch("podcast_vod_indexer.cli.get_videos_with_segments_by_kind")
    def test_does_not_retry_low_confidence_without_new_evidence(
        self,
        get_videos,
        get_confidence,
        get_segments,
        find_match,
        upsert_match,
    ) -> None:
        get_videos.side_effect = [
            [(1, "episode-id", "Episode")],
            [(2, "vod-id", "VOD")],
        ]
        get_confidence.return_value = 0.14

        run_matching(MagicMock())

        get_segments.assert_not_called()
        find_match.assert_not_called()
        upsert_match.assert_not_called()

    @patch("podcast_vod_indexer.cli.upsert_match")
    @patch("podcast_vod_indexer.cli.refine_low_confidence_window_match")
    @patch("podcast_vod_indexer.cli.find_best_window_match")
    @patch("podcast_vod_indexer.cli.get_segments_for_video")
    @patch("podcast_vod_indexer.cli.get_match_confidence_for_episode")
    @patch("podcast_vod_indexer.cli.get_videos_with_segments_by_kind")
    def test_retries_low_confidence_after_new_long_match(
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
        get_confidence.return_value = 0.14
        get_segments.side_effect = [
            [{"start": 0.0, "duration": 10.0, "text": "episode"}],
            [{"start": 0.0, "duration": 10.0, "text": "vod"}],
        ]
        find_match.return_value = {
            "start": 900.0,
            "end": 1800.0,
            "score": 0.20,
        }

        run_matching(
            MagicMock(),
            newly_long_matched_episode_ids={1},
        )

        refine_match.assert_not_called()
        upsert_match.assert_called_once()

    @patch("podcast_vod_indexer.cli.upsert_match")
    @patch("podcast_vod_indexer.cli.refine_low_confidence_window_match")
    @patch("podcast_vod_indexer.cli.find_best_window_match")
    @patch("podcast_vod_indexer.cli.get_segments_for_video")
    @patch("podcast_vod_indexer.cli.get_match_confidence_for_episode")
    @patch("podcast_vod_indexer.cli.get_videos_with_segments_by_kind")
    def test_new_vod_trigger_searches_only_new_vods(
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
            [(2, "old-vod-id", "Old VOD"), (3, "new-vod-id", "New VOD")],
        ]
        get_confidence.return_value = 0.14
        episode_segments = [
            {"start": 0.0, "duration": 10.0, "text": "episode"}
        ]
        new_vod_segments = [
            {"start": 0.0, "duration": 10.0, "text": "new vod"}
        ]
        get_segments.side_effect = [episode_segments, new_vod_segments]
        find_match.return_value = {
            "start": 900.0,
            "end": 1800.0,
            "score": 0.20,
        }

        run_matching(MagicMock(), new_vod_transcript_ids={3})

        find_match.assert_called_once_with(
            episode_segments,
            new_vod_segments,
            window_seconds=900.0,
            step_seconds=300.0,
        )
        refine_match.assert_not_called()
        upsert_match.assert_called_once()

    @patch("podcast_vod_indexer.cli.upsert_match")
    @patch("podcast_vod_indexer.cli.refine_low_confidence_window_match")
    @patch("podcast_vod_indexer.cli.find_best_window_match")
    @patch("podcast_vod_indexer.cli.get_segments_for_video")
    @patch("podcast_vod_indexer.cli.get_match_confidence_for_episode")
    @patch("podcast_vod_indexer.cli.get_videos_with_segments_by_kind")
    def test_does_not_replace_stronger_existing_vod_candidate(
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
            [(2, "new-vod-id", "New VOD")],
        ]
        get_confidence.return_value = 0.14
        get_segments.side_effect = [
            [{"start": 0.0, "duration": 10.0, "text": "episode"}],
            [{"start": 0.0, "duration": 10.0, "text": "vod"}],
        ]
        find_match.return_value = {
            "start": 900.0,
            "end": 1800.0,
            "score": 0.10,
        }
        refine_match.return_value = {
            "start": 960.0,
            "end": 1860.0,
            "score": 0.12,
        }

        run_matching(MagicMock(), new_vod_transcript_ids={2})

        upsert_match.assert_not_called()


class TranscriptFetchTriggerTests(unittest.TestCase):
    @patch("podcast_vod_indexer.cli.time.sleep")
    @patch("podcast_vod_indexer.cli.insert_segments")
    @patch("podcast_vod_indexer.cli.get_transcript_segments")
    def test_returns_ids_of_newly_fetched_transcripts(
        self,
        get_transcript_segments,
        insert_segments,
        sleep,
    ) -> None:
        get_transcript_segments.return_value = [
            {"start": 0.0, "duration": 1.0, "text": "transcript"}
        ]
        conn = MagicMock()

        completed, fetched_ids = fetch_transcripts_for_videos(
            conn,
            kind="vod",
            videos=[(10, "youtube-id", "https://example.com/vod")],
            limit=1,
        )

        self.assertTrue(completed)
        self.assertEqual(fetched_ids, {10})
        insert_segments.assert_called_once()
        sleep.assert_called_once()

    @patch("podcast_vod_indexer.cli.fetch_transcripts_for_videos")
    @patch("podcast_vod_indexer.cli.get_videos_without_segments_by_kind")
    def test_missing_transcript_fetch_returns_only_new_vod_ids(
        self,
        get_videos,
        fetch_transcripts,
    ) -> None:
        get_videos.return_value = []
        fetch_transcripts.side_effect = [
            (True, {1}),
            (True, {2}),
            (True, {3}),
        ]

        results = fetch_missing_transcripts_with_budget(
            MagicMock(),
            vod_limit=10,
            episode_limit=2,
            long_episode_limit=2,
        )

        self.assertEqual(results.episode_ids, {1})
        self.assertEqual(results.long_episode_ids, {2})
        self.assertEqual(results.vod_ids, {3})


class NewlyAcceptedLongMatchTests(unittest.TestCase):
    @patch("podcast_vod_indexer.cli.upsert_episode_long_match")
    @patch("podcast_vod_indexer.cli.get_episode_long_match_for_episode")
    @patch("podcast_vod_indexer.cli.find_long_episode_transcript_match")
    @patch("podcast_vod_indexer.cli.get_segments_for_video")
    @patch("podcast_vod_indexer.cli.get_matched_long_episode_ids")
    @patch("podcast_vod_indexer.cli.get_videos_with_segments_by_kind")
    def test_returns_episode_that_newly_crosses_acceptance_threshold(
        self,
        get_videos,
        get_matched_long_ids,
        get_segments,
        find_match,
        get_existing_match,
        upsert_match,
    ) -> None:
        get_videos.side_effect = [
            [(1, "episode-id", "Episode")],
            [(2, "long-id", "Long Episode")],
        ]
        get_segments.return_value = [
            {"start": 0.0, "duration": 1.0, "text": "transcript"}
        ]
        find_match.return_value = {"start": 0.0, "end": 900.0, "score": 0.20}
        get_existing_match.return_value = (0.10, "old-method")
        get_matched_long_ids.return_value = set()

        newly_matched_ids = run_long_episode_matching(
            MagicMock(),
            new_episode_transcript_ids={1},
        )

        self.assertEqual(newly_matched_ids, {1})
        upsert_match.assert_called_once()

    @patch("podcast_vod_indexer.cli.upsert_episode_long_match")
    @patch("podcast_vod_indexer.cli.get_episode_long_match_for_episode")
    @patch("podcast_vod_indexer.cli.find_long_episode_transcript_match")
    @patch("podcast_vod_indexer.cli.get_segments_for_video")
    @patch("podcast_vod_indexer.cli.get_matched_long_episode_ids")
    @patch("podcast_vod_indexer.cli.get_videos_with_segments_by_kind")
    def test_does_not_rerun_already_accepted_episode(
        self,
        get_videos,
        get_matched_long_ids,
        get_segments,
        find_match,
        get_existing_match,
        upsert_match,
    ) -> None:
        get_videos.side_effect = [
            [(1, "episode-id", "Episode")],
            [(2, "long-id", "Long Episode")],
        ]
        get_existing_match.return_value = (0.20, "existing-method")
        get_matched_long_ids.return_value = {2}

        newly_matched_ids = run_long_episode_matching(
            MagicMock(),
            new_long_episode_transcript_ids={2},
        )

        self.assertEqual(newly_matched_ids, set())
        get_segments.assert_not_called()
        find_match.assert_not_called()
        upsert_match.assert_not_called()

    @patch("podcast_vod_indexer.cli.upsert_episode_long_match")
    @patch("podcast_vod_indexer.cli.get_episode_long_match_for_episode")
    @patch("podcast_vod_indexer.cli.find_long_episode_transcript_match")
    @patch("podcast_vod_indexer.cli.get_segments_for_video")
    @patch("podcast_vod_indexer.cli.get_matched_long_episode_ids")
    @patch("podcast_vod_indexer.cli.get_videos_with_segments_by_kind")
    def test_does_not_rerun_low_confidence_match_without_new_transcripts(
        self,
        get_videos,
        get_matched_long_ids,
        get_segments,
        find_match,
        get_existing_match,
        upsert_match,
    ) -> None:
        get_videos.side_effect = [
            [(1, "episode-id", "Episode")],
            [(2, "long-id", "Long Episode")],
        ]
        get_matched_long_ids.return_value = {2}
        get_existing_match.return_value = (0.10, "existing-method")

        newly_matched_ids = run_long_episode_matching(MagicMock())

        self.assertEqual(newly_matched_ids, set())
        get_segments.assert_not_called()
        find_match.assert_not_called()
        upsert_match.assert_not_called()

    @patch("podcast_vod_indexer.cli.upsert_episode_long_match")
    @patch("podcast_vod_indexer.cli.get_episode_long_match_for_episode")
    @patch("podcast_vod_indexer.cli.find_long_episode_transcript_match")
    @patch("podcast_vod_indexer.cli.get_segments_for_video")
    @patch("podcast_vod_indexer.cli.get_matched_long_episode_ids")
    @patch("podcast_vod_indexer.cli.get_videos_with_segments_by_kind")
    def test_matches_missing_long_episode_result_without_new_transcripts(
        self,
        get_videos,
        get_matched_long_ids,
        get_segments,
        find_match,
        get_existing_match,
        upsert_match,
    ) -> None:
        get_videos.side_effect = [
            [(1, "episode-id", "Episode")],
            [(2, "long-id", "Long Episode")],
        ]
        get_matched_long_ids.return_value = set()
        get_existing_match.return_value = None
        get_segments.return_value = [
            {"start": 0.0, "duration": 1.0, "text": "transcript"}
        ]
        find_match.return_value = {"start": 0.0, "end": 900.0, "score": 0.20}

        run_long_episode_matching(MagicMock())

        find_match.assert_called_once()
        upsert_match.assert_called_once()

    @patch("podcast_vod_indexer.cli.upsert_episode_long_match")
    @patch("podcast_vod_indexer.cli.get_episode_long_match_for_episode")
    @patch("podcast_vod_indexer.cli.find_long_episode_transcript_match")
    @patch("podcast_vod_indexer.cli.get_segments_for_video")
    @patch("podcast_vod_indexer.cli.get_matched_long_episode_ids")
    @patch("podcast_vod_indexer.cli.get_videos_with_segments_by_kind")
    def test_new_long_trigger_searches_only_new_long_episode(
        self,
        get_videos,
        get_matched_long_ids,
        get_segments,
        find_match,
        get_existing_match,
        upsert_match,
    ) -> None:
        get_videos.side_effect = [
            [(1, "episode-id", "Episode")],
            [(2, "old-long-id", "Old Long"), (3, "new-long-id", "New Long")],
        ]
        get_matched_long_ids.return_value = {2}
        get_existing_match.return_value = (0.10, "old-method")
        episode_segments = [
            {"start": 0.0, "duration": 1.0, "text": "episode"}
        ]
        new_long_segments = [
            {"start": 0.0, "duration": 1.0, "text": "new long"}
        ]
        get_segments.side_effect = [episode_segments, new_long_segments]
        find_match.return_value = {"start": 0.0, "end": 900.0, "score": 0.20}

        run_long_episode_matching(
            MagicMock(),
            new_long_episode_transcript_ids={3},
        )

        find_match.assert_called_once()
        upsert_match.assert_called_once_with(
            unittest.mock.ANY,
            short_episode_video_id=1,
            long_episode_video_id=3,
            confidence=0.20,
            match_method="transcript_short15m_long45m_window15m",
        )

    @patch("podcast_vod_indexer.cli.upsert_episode_long_match")
    @patch("podcast_vod_indexer.cli.get_episode_long_match_for_episode")
    @patch("podcast_vod_indexer.cli.find_long_episode_transcript_match")
    @patch("podcast_vod_indexer.cli.get_segments_for_video")
    @patch("podcast_vod_indexer.cli.get_matched_long_episode_ids")
    @patch("podcast_vod_indexer.cli.get_videos_with_segments_by_kind")
    def test_does_not_replace_stronger_existing_long_candidate(
        self,
        get_videos,
        get_matched_long_ids,
        get_segments,
        find_match,
        get_existing_match,
        upsert_match,
    ) -> None:
        get_videos.side_effect = [
            [(1, "episode-id", "Episode")],
            [(2, "old-long-id", "Old Long"), (3, "new-long-id", "New Long")],
        ]
        get_matched_long_ids.return_value = {2}
        get_existing_match.return_value = (0.10, "old-method")
        get_segments.return_value = [
            {"start": 0.0, "duration": 1.0, "text": "transcript"}
        ]
        find_match.return_value = {"start": 0.0, "end": 900.0, "score": 0.05}

        run_long_episode_matching(
            MagicMock(),
            new_long_episode_transcript_ids={3},
        )

        upsert_match.assert_not_called()


class MainTriggerFlowTests(unittest.TestCase):
    @patch("podcast_vod_indexer.cli.export_matches_html")
    @patch("podcast_vod_indexer.cli.run_matching")
    @patch("podcast_vod_indexer.cli.run_long_episode_matching")
    @patch("podcast_vod_indexer.cli.fetch_missing_transcripts_with_budget")
    @patch("podcast_vod_indexer.cli.process_source")
    @patch("podcast_vod_indexer.cli.prune_vods_before_date")
    @patch("podcast_vod_indexer.cli.get_first_episode_matched_vod_date")
    @patch("podcast_vod_indexer.cli.get_connection")
    @patch("podcast_vod_indexer.cli.init_db")
    def test_passes_run_triggers_into_vod_matching(
        self,
        init_db,
        get_connection,
        get_vod_cutoff,
        prune_vods,
        process_source,
        fetch_transcripts,
        run_long_matching,
        run_vod_matching,
        export_html,
    ) -> None:
        conn = MagicMock()
        get_connection.return_value.__enter__.return_value = conn
        get_vod_cutoff.return_value = "20250305"
        prune_vods.return_value = (0, 0)
        fetch_transcripts.return_value = TranscriptFetchResults(
            episode_ids={1},
            long_episode_ids={2},
            vod_ids={10},
        )
        run_long_matching.return_value = {1}
        order = MagicMock()
        order.attach_mock(fetch_transcripts, "fetch_transcripts")
        order.attach_mock(run_long_matching, "run_long_matching")
        order.attach_mock(run_vod_matching, "run_vod_matching")

        main()

        self.assertEqual(
            [call[0] for call in order.mock_calls],
            ["fetch_transcripts", "run_long_matching", "run_vod_matching"],
        )
        run_vod_matching.assert_called_once_with(
            conn,
            new_vod_transcript_ids={10},
            newly_long_matched_episode_ids={1},
            vod_min_upload_date="20250305",
        )
        run_long_matching.assert_called_once_with(
            conn,
            new_episode_transcript_ids={1},
            new_long_episode_transcript_ids={2},
        )
        fetch_transcripts.assert_called_once_with(
            conn,
            vod_limit=10,
            episode_limit=2,
            long_episode_limit=2,
            vod_min_upload_date="20250305",
        )
        process_source.assert_any_call(
            conn,
            "https://www.youtube.com/@ThePrimeTimeagen/streams",
            kind="vod",
            min_upload_date="20250305",
        )


if __name__ == "__main__":
    unittest.main()
