import unittest
from unittest.mock import patch

from podcast_vod_indexer.matching import (
    find_clip_transcript_match,
    find_best_window_pair_match,
    refine_low_confidence_window_match,
)


def segment(start: float, duration: float, text: str) -> dict:
    return {
        "start": start,
        "duration": duration,
        "text": text,
    }


class RefineLowConfidenceWindowMatchTests(unittest.TestCase):
    def test_finds_better_one_minute_window_near_coarse_match(self) -> None:
        episode_segments = [
            segment(0.0, 60.0, "matching episode opening"),
        ]
        vod_segments = [
            segment(0.0, 60.0, "unrelated zero"),
            segment(60.0, 60.0, "unrelated one"),
            segment(120.0, 60.0, "unrelated two"),
            segment(180.0, 60.0, "matching episode opening"),
            segment(240.0, 60.0, "unrelated four"),
            segment(300.0, 60.0, "unrelated five"),
        ]

        match = refine_low_confidence_window_match(
            episode_segments,
            vod_segments,
            coarse_start_seconds=0.0,
            window_seconds=60.0,
            search_radius_seconds=300.0,
            step_seconds=60.0,
        )

        self.assertIsNotNone(match)
        self.assertEqual(match["start"], 180.0)
        self.assertEqual(match["score"], 1.0)

    def test_does_not_search_outside_radius(self) -> None:
        episode_segments = [
            segment(0.0, 60.0, "matching episode opening"),
        ]
        vod_segments = [
            segment(0.0, 60.0, "nearby unrelated"),
            segment(600.0, 60.0, "matching episode opening"),
        ]

        match = refine_low_confidence_window_match(
            episode_segments,
            vod_segments,
            coarse_start_seconds=0.0,
            window_seconds=60.0,
            search_radius_seconds=300.0,
            step_seconds=60.0,
        )

        self.assertIsNotNone(match)
        self.assertEqual(match["start"], 0.0)


class DeepWindowPairMatchTests(unittest.TestCase):
    def test_finds_later_episode_window_against_vod_windows(self) -> None:
        episode_segments = [
            segment(0.0, 60.0, "unrelated episode opening"),
            segment(60.0, 60.0, "shared discussion about editors"),
        ]
        vod_segments = [
            segment(0.0, 60.0, "unrelated vod opening"),
            segment(60.0, 60.0, "shared discussion about editors"),
        ]

        match = find_best_window_pair_match(
            episode_segments,
            vod_segments,
            window_seconds=60.0,
            episode_step_seconds=60.0,
            vod_step_seconds=60.0,
            min_window_chars=0,
        )

        self.assertIsNotNone(match)
        self.assertEqual(match["episode_start"], 60.0)
        self.assertEqual(match["start"], 60.0)
        self.assertEqual(match["score"], 1.0)

    @patch("podcast_vod_indexer.matching.similarity_score")
    def test_skips_expensive_similarity_for_unrelated_windows(
        self,
        similarity_score,
    ) -> None:
        episode_segments = [
            segment(0.0, 60.0, "kubernetes cluster ingress latency"),
        ]
        vod_segments = [
            segment(0.0, 60.0, "banana violin airport ceramic"),
        ]

        match = find_best_window_pair_match(
            episode_segments,
            vod_segments,
            window_seconds=60.0,
            episode_step_seconds=60.0,
            vod_step_seconds=60.0,
            min_window_chars=0,
        )

        self.assertIsNone(match)
        similarity_score.assert_not_called()

    @patch("podcast_vod_indexer.matching.similarity_score")
    def test_runs_expensive_similarity_for_overlapping_windows(
        self,
        similarity_score,
    ) -> None:
        similarity_score.return_value = 0.42
        episode_segments = [
            segment(0.0, 60.0, "kubernetes cluster ingress latency"),
        ]
        vod_segments = [
            segment(0.0, 60.0, "kubernetes ingress routing latency"),
        ]

        match = find_best_window_pair_match(
            episode_segments,
            vod_segments,
            window_seconds=60.0,
            episode_step_seconds=60.0,
            vod_step_seconds=60.0,
            min_window_chars=0,
        )

        self.assertIsNotNone(match)
        self.assertEqual(match["score"], 0.42)
        similarity_score.assert_called_once()

    @patch("podcast_vod_indexer.matching.similarity_score")
    def test_skips_undersized_deep_windows(
        self,
        similarity_score,
    ) -> None:
        episode_segments = [
            segment(
                0.0,
                60.0,
                "Thank you very much for watching. See you next week.",
            ),
        ]
        vod_segments = [
            segment(
                0.0,
                60.0,
                "Thanks everybody. We'll see you later. Bye.",
            ),
        ]

        match = find_best_window_pair_match(
            episode_segments,
            vod_segments,
            window_seconds=900.0,
            episode_step_seconds=300.0,
            vod_step_seconds=60.0,
        )

        self.assertIsNone(match)
        similarity_score.assert_not_called()


class ClipTranscriptMatchTests(unittest.TestCase):
    def test_finds_clip_inside_episode_transcript(self) -> None:
        clip_segments = [
            segment(0.0, 30.0, "shared clip moment"),
        ]
        target_segments = [
            segment(0.0, 30.0, "unrelated opening"),
            segment(60.0, 30.0, "shared clip moment"),
            segment(120.0, 30.0, "unrelated closing"),
        ]

        match = find_clip_transcript_match(
            clip_segments,
            target_segments,
            min_window_seconds=30.0,
            window_padding_seconds=0.0,
            step_seconds=30.0,
        )

        self.assertIsNotNone(match)
        self.assertEqual(match["start"], 60.0)
        self.assertEqual(match["score"], 1.0)


if __name__ == "__main__":
    unittest.main()
