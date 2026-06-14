import unittest

from podcast_vod_indexer.matching import refine_low_confidence_window_match


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


if __name__ == "__main__":
    unittest.main()
